import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import ValidationError

from polydocbench.benchmark import (
    build_manifest, capture_render_snapshot, replay_render_snapshot, verify_manifest, verify_render_snapshot,
)
from polydocbench.benchmark.render_snapshot import RenderInputSnapshot, _validate_asset
from polydocbench.benchmark.files import fingerprint_file, json_sha256
from polydocbench.noise import pdf_to_noisy_dataset
from scripts.run_tesseract_ocr_experiment import ArticleCase, _run_template_case, build_parser


@pytest.fixture
def source(tmp_path):
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    Image.new("RGB", (60, 30), (200, 40, 60)).save(source_dir / "chart.png")
    path = source_dir / "source.json"
    path.write_text(json.dumps({
        "schema_version": "0.1", "url": "https://en.wikipedia.org/wiki/Test", "content": [
            {"type": "heading", "level": 1, "text": "Snapshot test", "content": []},
            {"type": "paragraph", "text": "A deterministic document with symbols 10\u00b3\u2070."},
            {"type": "image", "src": "chart.png", "caption": "A sealed local figure."},
            {"type": "table", "rows": [[{"text": "Header", "is_header": True}, {"text": "Value", "is_header": True}],
                                       [{"text": "Cell"}, {"text": "42"}]]},
        ],
    }), encoding="utf-8")
    return path


def _capture(source, target):
    return capture_render_snapshot(source, target, template="technical_report")


def test_capture_records_exact_inputs_code_and_output_binding(source, tmp_path):
    root = tmp_path / "snapshot"
    result = _capture(source, root)
    evidence = verify_render_snapshot(root)
    assert result["render_snapshot_id"] == evidence.inputs.snapshot_id
    assert (root / "inputs/source.original.json").read_bytes() == source.read_bytes()
    assert evidence.inputs.source_revision_status == "not_verified"
    assert evidence.inputs.rights_review_status == "not_reviewed"
    assert len(evidence.inputs.assets) == 1
    assert len(evidence.inputs.fonts) >= 2
    assert any(file.role == "license" for file in evidence.inputs.files)
    assert any(file.role == "generator_code" for file in evidence.inputs.files)
    assert not any(".env" in file.path or "/PDB/" in file.path or ".git/" in file.path for file in evidence.inputs.files)
    gt = json.loads((root / "document_gt.json").read_text(encoding="utf-8"))
    assert gt["metadata"]["render_snapshot_id"] == evidence.inputs.snapshot_id
    assert gt["metadata"]["timestamp"] == gt["metadata"]["export_time"] == "1970-01-01T00:00:00Z"
    assert str(root) not in json.dumps(gt)


def test_replay_uses_copied_resources_after_original_inputs_disappear(source, tmp_path):
    root = tmp_path / "snapshot"
    _capture(source, root)
    (source.parent / "chart.png").unlink()
    source.unlink()
    replay = replay_render_snapshot(root, tmp_path / "replay")
    assert replay["replay_verified"]
    assert (root / "document.pdf").read_bytes() == Path(replay["pdf_path"]).read_bytes()
    assert (root / "document_gt.json").read_bytes() == Path(replay["gt_path"]).read_bytes()


def test_explicit_render_configuration_freezes_font_variants(source, tmp_path):
    root = tmp_path / "snapshot"
    capture_render_snapshot(source, root, render_config_path="configs/render_config.yaml")
    evidence = verify_render_snapshot(root)
    assert "DejaVuSans-Bold" in evidence.inputs.fonts
    assert "DejaVuSans-Oblique" in evidence.inputs.fonts
    assert replay_render_snapshot(root, tmp_path / "replay")["replay_verified"]


def test_prepared_source_uses_the_same_active_branch_as_content_loader(source, tmp_path):
    data = json.loads(source.read_text())
    data["elements"] = [{"type": "image", "src": "unused_missing.png"}]
    source.write_text(json.dumps(data), encoding="utf-8")
    root = tmp_path / "snapshot"
    _capture(source, root)
    evidence = verify_render_snapshot(root)
    prepared = json.loads((root / "inputs/source.json").read_text(encoding="utf-8"))
    assert len(evidence.inputs.assets) == 1
    assert "unused_missing.png" not in json.dumps(prepared)
    assert all(reference.location.startswith("/elements/") for reference in evidence.inputs.assets)


def test_relocated_snapshot_replays_in_fresh_process_without_original_bundle(source, tmp_path):
    root, relocated = tmp_path / "original", tmp_path / "relocated"
    _capture(source, root)
    shutil.copytree(root, relocated)
    # Both fixed targets are children of this test's private temporary directory.
    assert root.resolve().is_relative_to(tmp_path.resolve())
    root.rename(tmp_path / "archived")
    source.unlink()
    (source.parent / "chart.png").unlink()
    result = subprocess.run([sys.executable, "-m", "polydocbench", "replay-render-snapshot", str(relocated),
                             "-o", str(tmp_path / "replay")], check=True, capture_output=True, text=True, encoding="utf-8")
    assert "Byte-identical PDF/GT replay verified" in result.stdout


@pytest.mark.parametrize("role", ["original_source", "prepared_source", "layout_config", "render_config", "font", "asset", "generator_code"])
def test_verification_detects_modified_input_files(source, tmp_path, role):
    root = tmp_path / "snapshot"
    _capture(source, root)
    evidence = verify_render_snapshot(root)
    file = next(file for file in evidence.inputs.files if file.role == role)
    with (root / file.path).open("ab") as output:
        output.write(b"changed")
    with pytest.raises(ValueError, match="differs"):
        verify_render_snapshot(root)
    with pytest.raises(ValueError):
        replay_render_snapshot(root, tmp_path / "replay")


def test_snapshot_rejects_seal_changes_and_unsafe_paths(source, tmp_path):
    root = tmp_path / "snapshot"
    _capture(source, root)
    evidence = verify_render_snapshot(root)
    payload = evidence.inputs.model_dump()
    payload["source_url"] = "https://example.org/changed"
    with pytest.raises(ValidationError, match="snapshot ID"):
        RenderInputSnapshot.model_validate(payload)
    payload["files"][0]["path"] = "../outside"
    with pytest.raises(ValidationError, match="relative POSIX"):
        RenderInputSnapshot.model_validate(payload)


@pytest.mark.parametrize("reference", ["asset", "font"])
def test_replay_does_not_follow_unsealed_references_even_in_resealed_inputs(source, tmp_path, reference):
    root = tmp_path / "snapshot"
    _capture(source, root)
    evidence = verify_render_snapshot(root).model_dump()
    role = "prepared_source" if reference == "asset" else "render_config"
    entry = next(file for file in evidence["inputs"]["files"] if file["role"] == role)
    path = root / entry["path"]
    data = json.loads(path.read_text(encoding="utf-8"))
    if reference == "asset":
        next(item for item in data["elements"] if item["type"] == "image")["src"] = "https://example.invalid/unsealed.png"
    else:
        data["render"]["fonts"]["dejavu"]["path"] = "../unsealed.ttf"
    path.write_text(json.dumps(data), encoding="utf-8")
    entry.update(fingerprint_file(root, path).model_dump())
    evidence["inputs"]["snapshot_id"] = json_sha256({key: value for key, value in evidence["inputs"].items() if key != "snapshot_id"})
    (root / "render_inputs.json").write_text(json.dumps(evidence["inputs"]), encoding="utf-8")
    (root / "document_provenance.json").write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(ValueError, match="outside the sealed"):
        replay_render_snapshot(root, tmp_path / "replay")


@pytest.mark.parametrize("output", ["document.pdf", "document_gt.json"])
def test_verification_detects_modified_output(source, tmp_path, output):
    root = tmp_path / "snapshot"
    _capture(source, root)
    with (root / output).open("ab") as file:
        file.write(b"changed")
    with pytest.raises(ValueError, match="differs"):
        verify_render_snapshot(root)


def test_replay_rejects_environment_and_generator_drift(source, tmp_path, monkeypatch):
    import polydocbench.benchmark.render_snapshot as module

    root = tmp_path / "snapshot"
    _capture(source, root)
    original = module._environment
    monkeypatch.setattr(module, "_environment", lambda: {"python": "different"})
    with pytest.raises(ValueError, match="environment differs"):
        replay_render_snapshot(root, tmp_path / "replay")
    monkeypatch.setattr(module, "_environment", original)
    monkeypatch.setattr(module, "ROOT", tmp_path / "other_generator")
    with pytest.raises(ValueError, match="generator file set"):
        replay_render_snapshot(root, tmp_path / "replay")


def test_replay_rejects_conflicting_registered_font(source, tmp_path, monkeypatch):
    import polydocbench.benchmark.render_snapshot as module

    root = tmp_path / "snapshot"
    _capture(source, root)
    bad_font = tmp_path / "different.ttf"
    bad_font.write_bytes(b"not the captured font")
    original = module.pdfmetrics.getFont
    monkeypatch.setattr(module.pdfmetrics, "getFont", lambda name: SimpleNamespace(face=SimpleNamespace(filename=str(bad_font)))
                        if name == "DejaVuSans" else original(name))
    with pytest.raises(ValueError, match="registered font differs"):
        replay_render_snapshot(root, tmp_path / "replay")


def test_capture_is_offline_by_default_and_requires_explicit_network_permission(source, tmp_path, monkeypatch):
    import polydocbench.benchmark.render_snapshot as module

    data = json.loads(source.read_text())
    data["content"][2]["src"] = "https://example.invalid/chart.png"
    source.write_text(json.dumps(data), encoding="utf-8")
    calls = []

    def resolve(url):
        calls.append(url)
        return source.parent / "chart.png"

    monkeypatch.setattr(module, "resolve_image", resolve)
    with pytest.raises(ValueError, match="allow-downloads"):
        _capture(source, tmp_path / "blocked")
    assert calls == []
    capture_render_snapshot(source, tmp_path / "allowed", allow_downloads=True)
    assert calls == ["https://example.invalid/chart.png"]
    prepared = (tmp_path / "allowed/inputs/source.json").read_text()
    assert "https://example.invalid/chart.png" not in prepared


def test_snapshot_never_overwrites_existing_directory(source, tmp_path):
    root = tmp_path / "snapshot"
    _capture(source, root)
    before = (root / "document_provenance.json").read_bytes()
    with pytest.raises(ValueError, match="new or empty"):
        _capture(source, root)
    with pytest.raises(ValueError, match="new or empty"):
        replay_render_snapshot(root, root)
    assert (root / "document_provenance.json").read_bytes() == before


def test_unknown_template_does_not_silently_fall_back(source, tmp_path):
    with pytest.raises(ValueError, match="Unknown snapshot template"):
        capture_render_snapshot(source, tmp_path / "snapshot", template="typo")
    assert not (tmp_path / "snapshot").exists()


@pytest.mark.parametrize("graphic", [{"type": "image", "src": "missing.png"}, {"type": "formula", "latex": "x+y"}])
def test_snapshot_refuses_missing_graphical_assets(source, tmp_path, graphic):
    data = json.loads(source.read_text())
    data["content"][2] = graphic
    source.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        _capture(source, tmp_path / "snapshot")
    assert not (tmp_path / "snapshot/document_provenance.json").exists()


def test_formula_raster_is_resolved_without_using_its_original_directory(source, tmp_path):
    data = json.loads(source.read_text())
    data["content"][2] = {"type": "formula", "src": "chart.png", "latex": "x+y", "height": 40, "width": 80}
    source.write_text(json.dumps(data), encoding="utf-8")
    root = tmp_path / "snapshot"
    _capture(source, root)
    (source.parent / "chart.png").unlink()
    assert replay_render_snapshot(root, tmp_path / "replay")["replay_verified"]


@pytest.mark.parametrize("svg", [
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><image href="https://example.invalid/x.png"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><text>x</text></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><style>@import "https://example.invalid/x";</style></svg>',
])
def test_untracked_svg_resources_are_rejected_even_under_png_extension(tmp_path, svg):
    path = tmp_path / "disguised.png"
    path.write_text(svg, encoding="utf-8")
    with pytest.raises(ValueError):
        _validate_asset(path)


def test_manifest_binds_render_snapshot_and_noise_without_inventing_rights(source, tmp_path):
    pytest.importorskip("cv2")
    pytest.importorskip("fitz")
    root = tmp_path / "corpus"
    case = root / "en/history_russia"
    case.mkdir(parents=True)
    shutil.copyfile(source, case / "source.json")
    shutil.copyfile(source.parent / "chart.png", case / "chart.png")
    template = case / "technical_report"
    _capture(case / "source.json", template)
    pdf_to_noisy_dataset(template / "document.pdf", template / "document_gt.json", template / "noisy/page_001",
                         dpi=72, n_variants=1, profiles=["clean"])
    manifest = build_manifest(root)
    assert not manifest.issues and len(manifest.records) == 1
    record = manifest.records[0]
    assert record.render_snapshot_id and record.provenance_files
    assert "render_configuration_not_snapshotted" not in record.provenance_gaps
    assert "font_and_asset_provenance_not_recorded" not in record.provenance_gaps
    assert "font_and_asset_rights_not_verified" in record.provenance_gaps
    assert "source_revision_not_verified" in record.provenance_gaps
    assert verify_manifest(manifest, root) == []
    media = next(path for path in template.glob("inputs/assets/*"))
    with media.open("ab") as output:
        output.write(b"changed")
    assert verify_manifest(manifest, root)
    assert build_manifest(root).issues


def test_tesseract_snapshot_mode_records_inputs_and_can_reuse_them(source, tmp_path, monkeypatch):
    pytest.importorskip("cv2")
    pytest.importorskip("fitz")
    args = build_parser().parse_args(["--snapshot-inputs", "--profiles", "clean", "--dpi", "72", "--variants", "1"])
    monkeypatch.setattr("scripts.run_tesseract_ocr_experiment.extract_tesseract_lines", lambda *args, **kwargs: [])
    case = ArticleCase("en", "eng", "English", "history_russia", "Test", "https://en.wikipedia.org/wiki/Test")
    rows = _run_template_case(case, args, source.parent, source, "technical_report")
    assert len(rows) == 1 and rows[0]["profile"] == "clean"
    assert (source.parent / "technical_report/document_provenance.json").exists()
    args.reuse = True
    assert len(_run_template_case(case, args, source.parent, source, "technical_report")) == 1
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Snapshot reuse"):
        _run_template_case(case, args, source.parent, source, "technical_report")
