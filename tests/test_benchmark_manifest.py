import json
import shutil
from collections import Counter
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError
from reportlab.pdfgen import canvas

from polydocbench.benchmark import (DatasetManifest, SourceFamilyCatalog, apply_split_plan, build_manifest,
                                    draft_source_catalog, freeze_split_plan, load_benchmark_spec, verify_manifest)
from polydocbench.benchmark.manifest import FileFingerprint
from polydocbench.layout.templates import list_template_names
from polydocbench.provenance import fingerprint_file, json_sha256
from polydocbench.sources.snapshots import (PARSER_FILES, ROOT, WikipediaInputs, WikipediaProvenance,
                                            _parser_environment)
from scripts.build_benchmark_manifest import main


def _write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def _make_dataset(root: Path, *, language="en", variant=0) -> Path:
    case = root / language / "history_russia"
    template = case / "scientific_paper"
    page = template / "noisy" / "page_001"
    page.mkdir(parents=True, exist_ok=True)
    _write_json(case / "source.json", {
        "schema_version": "0.1", "title": "Test", "url": f"https://{language}.wikipedia.org/wiki/Test",
        "content": [{"type": "paragraph", "text": "A test document."}],
    })
    pdf = canvas.Canvas(str(template / "document.pdf"), pagesize=(40, 20), invariant=1)
    pdf.drawString(1, 10, "Test")
    pdf.save()
    _write_json(template / "document_gt.json", {
        "schema_version": "0.1", "pages": [{"page_number": 1, "width": 40, "height": 20}],
    })
    stem = f"medium_scan_{variant}"
    Image.new("RGB", (40, 20), "white").save(page / f"{stem}.jpg")
    gt_path = page / f"{stem}_gt.json"
    _write_json(gt_path, {
        "schema_version": "0.1",
        "metadata": {
            "profile": "medium_scan", "variant": variant, "dpi": 72,
            "coordinate_system": {"unit": "pixels", "origin": "top-left", "image_width": 40, "image_height": 20},
            "transform": {"type": "affine", "matrix": [[1, 0, 0], [0, 1, 0]]},
        },
        "image": {"width": 40, "height": 20},
        "pages": [{"page_number": 1, "width": 40, "height": 20}],
    })
    return gt_path


def _rename_source(root: Path, language: str, article_id: str):
    original = root / language / "history_russia"
    target = root / language / article_id
    original.rename(target)
    source = json.loads((target / "source.json").read_text(encoding="utf-8"))
    source["title"] = article_id
    source["url"] = f"https://{language}.wikipedia.org/wiki/{article_id}"
    _write_json(target / "source.json", source)


def test_draft_specification_counts_and_templates():
    spec = load_benchmark_spec("configs/benchmark_icdar2027.json")
    assert spec.status == "draft"
    assert spec.target_counts() == {
        "source_documents": 120, "rendered_documents": 720, "base_pages": 2160, "images": 8640,
    }
    assert set(spec.templates) <= set(list_template_names())
    repeated = spec.model_copy(update={"variants_per_noisy_condition": 3})
    assert repeated.target_counts()["images"] == 21600


@pytest.mark.parametrize("change", [
    {"languages": ["en", "en"]}, {"templates": [""]}, {"conditions": ["medium_scan"]},
    {"development_fraction": 1}, {"master_seed": -1}, {"schema_version": "99"},
    {"unknown_option": True},
])
def test_draft_specification_rejects_invalid_settings(change):
    spec = load_benchmark_spec("configs/benchmark_icdar2027.json")
    with pytest.raises(ValidationError):
        type(spec).model_validate({**spec.model_dump(), **change})


def test_inventory_is_deterministic_and_explicit_about_unknown_provenance(tmp_path):
    _make_dataset(tmp_path)
    first = build_manifest(tmp_path)
    second = build_manifest(tmp_path)
    assert first == second
    assert first.discovered_count == 1
    assert not first.issues
    record = first.records[0]
    assert record.source_page_number == record.image_page_number == 1
    assert record.width == 40 and record.height == 20
    assert record.source.path == "en/history_russia/source.json"
    assert record.split == "unassigned"
    assert record.family_assignment == "inferred_from_article_id"
    assert "generation_seed_not_recorded" in record.provenance_gaps
    assert first.generation_reproducibility == "not_established"
    assert verify_manifest(first, tmp_path) == []
    assert DatasetManifest.model_validate_json(first.model_dump_json()) == first


def test_inventory_can_be_relocated_without_absolute_paths(tmp_path):
    original = tmp_path / "original"
    _make_dataset(original)
    manifest = build_manifest(original)
    copied = tmp_path / "copied"
    shutil.copytree(original, copied)
    assert verify_manifest(manifest, copied) == []
    assert build_manifest(copied) == manifest


def test_legacy_schema_defaults_are_not_reported_as_declared_versions(tmp_path):
    gt_path = _make_dataset(tmp_path)
    for path in (gt_path, tmp_path / "en/history_russia/source.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["schema_version"]
        _write_json(path, data)
    record = build_manifest(tmp_path).records[0]
    assert record.source_schema_version is record.gt_schema_version is None
    assert "source_schema_version_not_declared" in record.provenance_gaps
    assert "gt_schema_version_not_declared" in record.provenance_gaps


def test_parent_files_are_hashed_once_per_build(tmp_path, monkeypatch):
    import polydocbench.benchmark.manifest as module

    _make_dataset(tmp_path, variant=0)
    _make_dataset(tmp_path, variant=1)
    calls = Counter()
    original = module._fingerprint

    def fingerprint(root, path):
        calls[path.name] += 1
        return original(root, path)

    monkeypatch.setattr(module, "_fingerprint", fingerprint)
    manifest = build_manifest(tmp_path)
    assert len(manifest.records) == 2
    assert calls["source.json"] == calls["document.pdf"] == calls["document_gt.json"] == 1


def test_filters_and_cross_language_family_are_visible(tmp_path):
    _make_dataset(tmp_path, language="en")
    _make_dataset(tmp_path, language="ru")
    manifest = build_manifest(tmp_path)
    assert manifest.summary()["sources"] == 2
    assert manifest.summary()["inferred_source_families"] == 1
    assert manifest.summary()["provenance_gaps"]["source_family_not_reviewed"] == 2
    selected = build_manifest(tmp_path, languages=["ru"], templates=["scientific_paper"])
    assert [record.language for record in selected.records] == ["ru"]
    assert build_manifest(tmp_path, templates=["missing"]).records == []


@pytest.mark.parametrize("target", ["source", "pdf", "pdf_gt", "image", "image_gt"])
def test_verification_detects_changed_files(tmp_path, target):
    _make_dataset(tmp_path)
    manifest = build_manifest(tmp_path)
    path = tmp_path / getattr(manifest.records[0], target).path
    with path.open("ab") as file:
        file.write(b"changed")
    issues = verify_manifest(manifest, tmp_path)
    assert len(issues) == 1
    assert issues[0].path == getattr(manifest.records[0], target).path


def test_missing_image_is_an_error_not_a_skipped_artifact(tmp_path):
    gt_path = _make_dataset(tmp_path)
    gt_path.with_name("medium_scan_0.jpg").unlink()
    manifest = build_manifest(tmp_path)
    assert manifest.discovered_count == 1
    assert manifest.records == []
    assert len(manifest.issues) == 1
    assert manifest.issues[0].error_type == "FileNotFoundError"


@pytest.mark.parametrize("change", [
    lambda data: data["metadata"].update(profile="light_scan"),
    lambda data: data["metadata"].update(variant=2),
    lambda data: data["metadata"]["coordinate_system"].update(origin="bottom-left"),
    lambda data: data["metadata"]["coordinate_system"].update(image_width=45),
    lambda data: data["image"].update(height=25),
    lambda data: data["pages"][0].update(page_number=2),
    lambda data: data["metadata"]["transform"].update(matrix=[[1, 0], [0, 1]]),
    lambda data: data["metadata"]["transform"].update(matrix=[[1, 0, float("nan")], [0, 1, 0]]),
])
def test_inventory_rejects_inconsistent_gt(tmp_path, change):
    gt_path = _make_dataset(tmp_path)
    data = json.loads(gt_path.read_text(encoding="utf-8"))
    change(data)
    _write_json(gt_path, data)
    manifest = build_manifest(tmp_path)
    assert manifest.records == []
    assert len(manifest.issues) == 1


def test_duplicate_logical_artifact_is_reported(tmp_path):
    gt_path = _make_dataset(tmp_path)
    shutil.copytree(gt_path.parent, gt_path.parent.with_name("page_01"))
    manifest = build_manifest(tmp_path)
    assert len(manifest.records) == len(manifest.issues) == 1
    assert "Duplicate artifact" in manifest.issues[0].message


@pytest.mark.parametrize("value", ["../outside", "/absolute", "C:/outside", "dir\\file", ".", ""])
def test_fingerprints_reject_unsafe_paths(value):
    with pytest.raises(ValidationError):
        FileFingerprint(path=value, sha256="0" * 64, size_bytes=0)


def test_manifest_rejects_modified_identity_and_bad_counts(tmp_path):
    _make_dataset(tmp_path)
    manifest = build_manifest(tmp_path)
    data = manifest.model_dump()
    data["records"][0]["image"]["sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="artifact_id"):
        DatasetManifest.model_validate(data)
    with pytest.raises(ValidationError, match="Discovery count"):
        DatasetManifest.model_validate({**manifest.model_dump(), "discovered_count": 0})


def test_cli_build_verify_strict_and_integrity_failure(tmp_path):
    _make_dataset(tmp_path)
    args = ["--input-dir", str(tmp_path)]
    assert main(args) == 0
    manifest_path = tmp_path / "benchmark_inventory" / "manifest.json"
    report = json.loads((manifest_path.parent / "inventory_report.json").read_text(encoding="utf-8"))
    assert report["accepted"] == 1 and report["draft_target_counts"]["images"] == 8640
    assert main(args + ["--strict"]) == 2
    assert main(args + ["--verify", str(manifest_path)]) == 0
    assert main(args + ["--verify", str(manifest_path), "--strict"]) == 2
    (tmp_path / "en/history_russia/source.json").unlink()
    assert main(args + ["--verify", str(manifest_path)]) == 1


def test_cli_empty_selection_returns_failure_and_preserves_report(tmp_path):
    assert main(["--input-dir", str(tmp_path)]) == 1
    report = json.loads((tmp_path / "benchmark_inventory/inventory_report.json").read_text())
    assert report["discovered"] == report["accepted"] == 0


def test_reviewed_family_split_is_deterministic_and_applies_to_all_variants(tmp_path):
    for language, article_id in (("en", "history_russia"), ("ru", "linear_algebra"), ("fr", "cell_biology")):
        _make_dataset(tmp_path, language=language, variant=0)
        if article_id != "history_russia":
            _rename_source(tmp_path, language, article_id)
    page = tmp_path / "en/history_russia/scientific_paper/noisy/page_001"
    shutil.copyfile(page / "medium_scan_0.jpg", page / "medium_scan_1.jpg")
    gt = json.loads((page / "medium_scan_0_gt.json").read_text(encoding="utf-8"))
    gt["metadata"]["variant"] = 1
    _write_json(page / "medium_scan_1_gt.json", gt)

    manifest = build_manifest(tmp_path)
    draft = draft_source_catalog(manifest)
    assert draft.review_status == "draft"
    with pytest.raises(ValueError, match="Review"):
        freeze_split_plan(draft)

    reviewed = SourceFamilyCatalog.model_validate({
        **draft.model_dump(),
        "review_status": "reviewed",
        "reviewed_by": "test-reviewer",
        "reviewed_at": "2026-11-02T10:00:00Z",
    })
    plan = freeze_split_plan(reviewed, seed=7, development_fraction=0.34)
    assert plan == freeze_split_plan(reviewed, seed=7, development_fraction=0.34)
    assigned = apply_split_plan(manifest, plan)

    assert assigned.split_plan == plan
    assert {record.split for record in assigned.records} == {"dev", "test"}
    for family in {record.source_family for record in assigned.records}:
        assert len({record.split for record in assigned.records if record.source_family == family}) == 1
    history = [record for record in assigned.records if record.article_id == "history_russia"]
    assert len(history) == 2 and len({record.split for record in history}) == 1
    assert all("source_family_not_reviewed" not in record.provenance_gaps for record in assigned.records)
    assert all("split_not_assigned" not in record.provenance_gaps for record in assigned.records)


def test_family_catalog_rejects_identity_leakage_across_families():
    member = {
        "language": "en", "article_id": "one", "source_sha256": "a" * 64,
        "canonical_url": "https://en.wikipedia.org/wiki/One", "page_id": 10,
        "wikidata_item_id": "Q42",
    }
    with pytest.raises(ValidationError, match="cross families"):
        SourceFamilyCatalog.model_validate({
            "families": [
                {"family_id": "first", "members": [member]},
                {"family_id": "second", "members": [{
                    **member, "article_id": "two", "source_sha256": "b" * 64,
                    "canonical_url": "https://en.wikipedia.org/wiki/Two",
                }]},
            ]
        })


def test_manifest_records_verified_wikipedia_revision_evidence(tmp_path):
    _make_dataset(tmp_path)
    case = tmp_path / "en/history_russia"
    query = {"query": {"pages": [{
        "pageid": 7, "ns": 0, "title": "Test", "pageprops": {"wikibase_item": "Q42"},
        "revisions": [{"revid": 123, "timestamp": "2026-11-01T10:00:00Z", "sha1": "abc"}],
    }]}}
    html = '<div class="mw-parser-output"><p>A test document.</p></div>'
    parsed = {"parse": {"pageid": 7, "title": "Test", "revid": 123, "text": html}}
    _write_json(case / "query.json", query)
    _write_json(case / "parse.json", parsed)
    (case / "page.html").write_text(html, encoding="utf-8")
    input_payload = {
        "schema_version": "0.1", "method": "mediawiki_revision_parse",
        "requested_url": "https://en.wikipedia.org/wiki/Test", "requested_revision_id": None,
        "language": "en", "canonical_title": "Test", "canonical_url": "https://en.wikipedia.org/wiki/Test",
        "permanent_url": "https://en.wikipedia.org/w/index.php?oldid=123", "page_id": 7,
        "revision_id": 123, "revision_timestamp": "2026-11-01T10:00:00Z", "revision_sha1": "abc",
        "wikidata_item_id": "Q42", "retrieved_at": "2026-11-02T10:00:00Z",
        "query_response": fingerprint_file(case, case / "query.json").model_dump(),
        "parse_response": fingerprint_file(case, case / "parse.json").model_dump(),
        "html": fingerprint_file(case, case / "page.html").model_dump(),
        "parser_files": [fingerprint_file(ROOT, ROOT / path).model_dump() for path in PARSER_FILES],
        "parser_environment": _parser_environment(),
    }
    inputs = WikipediaInputs(snapshot_id=json_sha256(input_payload), **input_payload)
    source_path = case / "source.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["metadata"] = {"wikipedia_snapshot_id": inputs.snapshot_id,
                          "wikipedia_provenance": "source_provenance.json"}
    _write_json(source_path, source)
    evidence = WikipediaProvenance(
        schema_version="0.1", inputs=inputs, source=fingerprint_file(case, source_path)
    )
    _write_json(case / "source_provenance.json", evidence.model_dump())

    manifest = build_manifest(tmp_path)
    record = manifest.records[0]
    assert record.source_revision_id == 123
    assert record.source_page_id == 7
    assert record.wikidata_item_id == "Q42"
    assert record.source_snapshot_id == inputs.snapshot_id
    assert "source_revision_not_verified" not in record.provenance_gaps
    assert verify_manifest(manifest, tmp_path) == []
