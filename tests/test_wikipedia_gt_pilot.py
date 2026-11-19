import json
from pathlib import Path

import pytest
from PIL import Image

from polydocbench.benchmark.gt_audit import GTAuditPlan, run_gt_audit
from polydocbench.benchmark.manifest import build_manifest
from polydocbench.benchmark.pilot import prepare_pilot
from polydocbench.benchmark.render_snapshot import capture_render_snapshot, verify_render_snapshot
from polydocbench.noise import pdf_to_noisy_dataset
from polydocbench.sources.snapshots import capture_wikipedia_source
from scripts.prepare_wikipedia_gt_pilot import select_pages
import test_wikipedia_snapshots


def test_pilot_keeps_original_media_and_audits_sealed_block_selection(tmp_path, monkeypatch):
    pytest.importorskip("fitz")
    pytest.importorskip("cv2")
    test_wikipedia_snapshots._fake_mediawiki(monkeypatch)
    monkeypatch.setattr(test_wikipedia_snapshots, "HTML", """<div class="mw-parser-output">
        <p>Review the named figure and table.</p>
        <figure><img src="//thumb.wikimedia.org/example.png"><figcaption>Real caption</figcaption></figure>
        <table><caption>Measurements</caption><tr><th>Unit</th><td>5</td></tr></table>
        <table><tr><td><img src="//upload.wikimedia.org/in-cell.png">Nested graphic</td></tr></table>
        <p>Missing glyph: &#x5468;.</p>
        <figure><img src="https://example.com/unapproved.png"></figure></div>""")
    root = tmp_path / "dataset"
    directory = root / "en/example"
    capture_wikipedia_source("https://en.wikipedia.org/wiki/Test_Article", directory)
    original = (directory / "source.json").read_bytes()
    photo = tmp_path / "photo.png"
    Image.new("RGB", (60, 30), (43, 100, 210)).save(photo)

    def get_asset(source):
        assert source == "https://thumb.wikimedia.org/example.png"
        return photo

    monkeypatch.setattr("polydocbench.benchmark.render_snapshot.resolve_image", get_asset)
    render = directory / "technical_report"
    result = capture_render_snapshot(directory / "source.json", render, template="technical_report",
                                     allow_downloads=True, wikipedia_pilot=True)
    evidence = verify_render_snapshot(render)
    assert (directory / "source.json").read_bytes() == original
    ledger = render / "inputs/source_selection.json"
    selection = json.loads(ledger.read_text())
    assert selection["retained_source_indices"] == [1, 2, 3]
    assert [entry["source_index"] for entry in selection["exclusions"]] == [4, 5, 6]
    assert evidence.inputs.source_snapshot_id
    assert (render / evidence.inputs.assets[0].snapshot_path).read_bytes() == photo.read_bytes()
    pdf_to_noisy_dataset(result["pdf_path"], result["gt_path"], render / "noisy/page_001",
                         n_variants=1, dpi=80, profiles=["clean"])
    manifest = build_manifest(root)
    assert not manifest.issues
    pilot = prepare_pilot(manifest, base_pages=1, split="unassigned", profiles=["clean"])
    report = run_gt_audit(GTAuditPlan.freeze(pilot), root, tmp_path / "audit")
    assert report["automatic_error_findings"] == 0
    ledger.write_text("{}")
    with pytest.raises(ValueError, match="source_selection"):
        verify_render_snapshot(render)


def test_mathml_without_image_is_rendered_and_sealed(tmp_path, monkeypatch):
    pytest.importorskip("ziamath")
    pytest.importorskip("svglib")
    fitz = pytest.importorskip("fitz")
    test_wikipedia_snapshots._fake_mediawiki(monkeypatch)
    monkeypatch.setattr(test_wikipedia_snapshots, "HTML", """<div class="mw-parser-output">
        <p>Equation:</p><dl><dd><math class="mwe-math-element-block" display="block"
        xmlns="http://www.w3.org/1998/Math/MathML"><msup><mi>x</mi><mn>2</mn></msup>
        <mo>=</mo><mn>16</mn></math></dd></dl></div>""")
    source = tmp_path / "article"
    capture_wikipedia_source("https://en.wikipedia.org/wiki/Test_Article", source)
    output = tmp_path / "render"
    result = capture_render_snapshot(source / "source.json", output, allow_downloads=True, wikipedia_pilot=True)
    evidence = verify_render_snapshot(output)
    asset, = evidence.inputs.assets
    assert asset.original_reference.startswith("mathml:sha256:")
    assert b"<path " in (output / asset.snapshot_path).read_bytes()
    gt = json.loads(Path(result["gt_path"]).read_text(encoding="utf-8"))
    formula, = (element for element in gt["elements"] if element["type"] == "formula")
    assert "<msup>" in formula["metadata"]["mathml"]
    assert formula["bbox"]["width"] > formula["bbox"]["height"]
    with fitz.open(result["pdf_path"]) as pdf:
        assert pdf[0].get_drawings()


def test_page_selection_prefers_different_media_over_a_repeated_table():
    def block(kind, page, source_index):
        return {"type": kind, "bbox": {"page": page}, "metadata": {"source_index": source_index, "role": "block"}}
    gt = {"pages": [{"page_number": n} for n in range(1, 4)],
          "elements": [block("table", 1, 4), block("image", 1, 5),
                       block("table", 2, 4), block("formula", 3, 8)]}
    assert list(select_pages(gt, 2)) == [1, 3]
