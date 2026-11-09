import json
import shutil
import subprocess
from collections import Counter
from copy import deepcopy

import numpy as np
import pytest

from polydocbench.gt.audit import audit_gt_document
from polydocbench.gt.audit_geometry import audit_image_gt, visible_polygon_fraction
from polydocbench.noise.geometry import transform_gt_to_image_gt


def document():
    block = {"id": "p", "type": "paragraph", "content": "Alpha beta", "bbox": {"x": 10, "y": 20, "width": 60, "height": 10, "page": 1},
             "metadata": {"role": "block", "source_index": 1, "reading_order": 1}}
    line = {"id": "l", "type": "text_line", "content": "Alpha beta", "bbox": deepcopy(block["bbox"]),
            "metadata": {"role": "line", "parent_id": "p", "line_index": 1, "source_index": 1, "reading_order": 1}}
    return {"schema_version": "0.1", "metadata": {}, "elements": [block, line], "reading_order": {"blocks": ["p"], "lines": ["l"]},
            "pages": [{"page_number": 1, "width": 100, "height": 80,
                       "containers": [{"id": "main", "element_count": 1, "elements": [deepcopy(line)]}]}]}


def codes(result):
    return Counter(f.code for f in result.findings)


def transformed(data=None, matrix=None):
    return transform_gt_to_image_gt(data or document(), "scan.png", "source.pdf", "source_gt.json", 1, 2, 160,
                                    200, 160, matrix or [[1, 0, 0], [0, 1, 0]], "clean", 0, 144)


def test_flat_and_container_copies_are_not_duplicate_ids():
    result = audit_gt_document(document(), coordinate_system="pdf", source_items=[{"type": "paragraph", "content": "Alpha beta"}])
    assert result.passed and not result.findings
    assert result.counts["source_text_items_checked"] == 1


@pytest.mark.parametrize("mutation,expected", [
    (lambda d: d["elements"].append(deepcopy(d["elements"][0])), "duplicate_id"),
    (lambda d: d["elements"][0]["bbox"].update(x=float("nan")), "bbox_invalid"),
    (lambda d: d["elements"][0]["bbox"].update(width=-1), "bbox_extent"),
    (lambda d: d["elements"][0]["bbox"].update(page=2), "element_page"),
    (lambda d: d["elements"][0]["bbox"].update(x=101), "bbox_outside_page"),
    (lambda d: d["reading_order"]["lines"].append("l"), "reading_order_coverage"),
    (lambda d: d["elements"][1]["metadata"].update(parent_id="missing"), "parent_missing"),
    (lambda d: d["elements"][1]["metadata"].update(parent_id="l"), "parent_cycle"),
    (lambda d: d["elements"][1]["metadata"].update(reading_order=3), "reading_order_index"),
    (lambda d: d["pages"][0]["containers"][0]["elements"][0].update(content="Different"), "container_copy"),
    (lambda d: d["elements"][1].update(content="Missing words"), "parent_text"),
])
def test_structural_defects_are_detected(mutation, expected):
    data = document()
    mutation(data)
    result = audit_gt_document(data, coordinate_system="pdf")
    assert not result.passed and expected in codes(result)


def test_source_text_and_missing_items_are_not_silently_approved():
    result = audit_gt_document(document(), coordinate_system="pdf", source_items=[
        {"type": "paragraph", "content": "Alpha beta gamma"}, {"type": "image", "src": "x.png"}])
    assert {"source_text", "source_item_missing"} <= set(codes(result))


def test_missing_all_lines_does_not_pass_when_parent_text_remains():
    data = document()
    data["elements"] = data["elements"][:1]
    data["pages"][0]["containers"][0].update(elements=[], element_count=0)
    data["reading_order"]["lines"] = []
    assert "missing_text_lines" in codes(audit_gt_document(data, coordinate_system="pdf"))


def test_container_allocations_and_source_indices_are_checked():
    data = document()
    data["pages"][0]["containers"][0]["bbox"] = {"x": 0, "y": 0, "width": 5, "height": 5, "page": 1}
    data["elements"][0]["metadata"]["source_index"] = 2
    result = audit_gt_document(data, coordinate_system="pdf", source_items=[{"type": "paragraph", "content": "Alpha beta"}])
    assert {"container_bounds", "source_index"} <= set(codes(result))


def test_legacy_heading_types_are_missing_from_current_quality_line_scope():
    from polydocbench.eval.gt import extract_gt_lines

    data = document()
    data["elements"][0]["type"] = "heading2"
    data["elements"][1]["type"] = "heading2"
    data["pages"][0]["containers"][0]["elements"][0]["type"] = "heading2"
    assert extract_gt_lines(data, page_number=1) == []
    assert "missing_text_lines" in codes(audit_gt_document(data, coordinate_system="pdf"))


@pytest.mark.parametrize("fault,expected", [("reference", "metadata_invalid"), ("rows", "metadata_invalid"), ("text", "text_content_type")])
def test_schema_permitted_semantic_type_errors_do_not_crash_audit(fault, expected):
    data = document()
    if fault == "reference":
        data["elements"][1]["metadata"]["parent_id"] = {"bad": "reference"}
    elif fault == "rows":
        data["elements"][0]["metadata"]["row_indexes"] = None
    else:
        data["elements"][1]["content"] = 123
    result = audit_gt_document(data, coordinate_system="pdf")
    assert not result.passed and expected in codes(result)


@pytest.mark.parametrize("matrix", [
    [[1, 0, 0], [0, 1, 0]], [[0, -1, 150], [1, 0, 0]],
    [[0.99, 0.2, -3], [-0.1, 1.01, 7]], [[1, 0.5, 100], [0, 1, 0]],
])
def test_independent_oracle_known_affine_answers(matrix):
    data = transformed(matrix=matrix)
    result = audit_image_gt(data, document(), source_page_number=1, image_size=(200, 160), dpi=144)
    assert result.passed
    assert result.counts["checked_transform_elements"] == 2
    assert result.max_geometry_error_pixels == pytest.approx(0)


@pytest.mark.parametrize("fault,expected", [
    ("polygon", "transformed_geometry"), ("bbox", "transformed_geometry"), ("content", "transformed_content"),
    ("missing", "transformed_membership"), ("order", "transformed_order"), ("units", "image_coordinates"),
])
def test_transformed_gt_faults_are_detected(fault, expected):
    data = transformed()
    if fault == "polygon":
        data["elements"][0]["polygon"][0][0] += 3
    elif fault == "bbox":
        data["elements"][0]["bbox"]["width"] -= 2
    elif fault == "content":
        data["elements"][0]["content"] = "changed"
    elif fault == "missing":
        data["elements"].pop()
    elif fault == "order":
        data["reading_order"]["lines"] = []
    else:
        data["metadata"]["coordinate_system"]["unit"] = "points"
    result = audit_image_gt(data, document(), source_page_number=1, image_size=(200, 160), dpi=144)
    assert not result.passed and expected in codes(result)


def test_clipping_uses_polygon_area_and_is_not_automatic_exclusion():
    assert visible_polygon_fraction([[-10, 0], [10, 0], [10, 10], [-10, 10]], 100, 100) == pytest.approx(0.5)
    data = transformed(matrix=[[1, 0, 180], [0, 1, 0]])
    result = audit_image_gt(data, document(), source_page_number=1, image_size=(200, 160), dpi=144)
    assert result.passed and result.counts["fully_clipped_elements"] == 2
    assert len(data["elements"]) == 2 and all(f.severity == "warning" for f in result.findings)


def test_affine_image_landmark_matches_independent_coordinate_oracle():
    cv2 = pytest.importorskip("cv2")
    source = np.zeros((160, 200), dtype=np.uint8)
    source[65:68, 54:57] = 255
    matrix = cv2.getRotationMatrix2D((100, 80), 7, 1)
    output = cv2.warpAffine(source, matrix, (200, 160))
    ys, xs = np.nonzero(output > 0)
    expected = matrix @ np.array([55, 66, 1])
    assert np.linalg.norm(np.array([xs.mean(), ys.mean()]) - expected) < 0.6
    gt = document()
    # This PDF box has raster center (55, 66); test the PDF-origin conversion too.
    landmark_box = {"x": 26.5, "y": 46, "width": 2, "height": 2, "page": 1}
    for element in gt["elements"]:
        element["bbox"] = deepcopy(landmark_box)
    gt["pages"][0]["containers"][0]["elements"][0]["bbox"] = deepcopy(landmark_box)
    data = transformed(data=gt, matrix=matrix.tolist())
    result = audit_image_gt(data, gt, source_page_number=1, image_size=(200, 160), dpi=144)
    assert result.passed
    polygon_center = np.asarray(data["elements"][0]["polygon"]).mean(axis=0)
    assert np.linalg.norm(polygon_center - np.array([xs.mean(), ys.mean()])) < 0.6


@pytest.fixture
def complex_layout(tmp_path):
    pytest.importorskip("fitz")
    from test_complex_layout import layout, table

    return layout(tmp_path, [
        {"type": "heading", "level": 1, "text": "GT audit"},
        {"type": "paragraph", "text": "Known page-spanning text. " * 75}, table(24),
    ], small=True)


def test_complex_tables_repeats_and_source_coverage(complex_layout, tmp_path):
    from polydocbench.layout.content_loader import ContentLoader

    gt = complex_layout.ground_truth
    result = audit_gt_document(gt, coordinate_system="pdf", source_items=ContentLoader.load_json(tmp_path / "source.json"))
    assert result.passed, [f.model_dump() for f in result.findings]
    assert result.counts["table_cell"] > 24
    assert any(e["metadata"].get("repeated_header") for e in gt["elements"])
    page2 = transform_gt_to_image_gt(gt, "scan.png", "source.pdf", "source_gt.json", 2, 1, 240,
                                     280, 240, [[1, 0, 0], [0, 1, 0]], "clean", 0, 72)
    checked = audit_image_gt(page2, gt, source_page_number=2, image_size=(280, 240), dpi=72)
    assert checked.passed, [f.model_dump() for f in checked.findings]


@pytest.mark.parametrize("fault,expected", [
    ("span", "cell_span"), ("overlap", "cell_overlap"), ("header", "repeated_header_flag"),
    ("caption", "caption_owner"), ("text", "source_table_cell"),
])
def test_table_and_caption_defects(complex_layout, tmp_path, fault, expected):
    from polydocbench.layout.content_loader import ContentLoader

    gt = deepcopy(complex_layout.ground_truth)
    cell = next(e for e in gt["elements"] if e["type"] == "table_cell")
    if fault == "span":
        cell["metadata"]["rowspan"] = 100
    elif fault == "overlap":
        next(e for e in gt["elements"] if e["type"] == "table_cell" and e["id"] != cell["id"])["metadata"].update(
            row_index=cell["metadata"]["row_index"], column_index=cell["metadata"]["column_index"])
    elif fault == "header":
        cell["metadata"]["repeated_header"] = True
    elif fault == "caption":
        next(e for e in gt["elements"] if e["type"] == "caption")["metadata"]["caption_for"] = "missing"
    else:
        cell["content"] = "wrong"
    result = audit_gt_document(gt, coordinate_system="pdf", source_items=ContentLoader.load_json(tmp_path / "source.json"))
    assert not result.passed and expected in codes(result)


def test_audit_runner_seals_evidence_and_never_auto_reviews(tmp_path):
    pytest.importorskip("cv2")
    pytest.importorskip("fitz")
    from test_complex_layout import layout
    from polydocbench.benchmark.gt_audit import AuditReviews, GTAuditPlan, rebuild_gt_audit, run_gt_audit
    from polydocbench.benchmark.manifest import build_manifest
    from polydocbench.benchmark.pilot import prepare_pilot
    from polydocbench.noise import pdf_to_noisy_dataset
    from polydocbench.render import PDFRenderer

    root = tmp_path / "dataset"
    case = root / "en" / "test_case"
    case.mkdir(parents=True)
    placed = layout(case, [{"type": "paragraph", "text": "Known searchable text."}], small=True)
    template = case / "technical_report"
    template.mkdir()
    rendered = PDFRenderer(debug=False).render(placed, template / "document.pdf")
    pdf_to_noisy_dataset(rendered["pdf_path"], rendered["gt_path"], template / "noisy/page_001",
                         profiles=["clean", "medium_scan"], n_variants=1, dpi=72)
    pilot = prepare_pilot(build_manifest(root), base_pages=1, profiles=["clean", "medium_scan"], split="unassigned")
    plan = GTAuditPlan.freeze(pilot)
    assert GTAuditPlan.model_validate_json(plan.model_dump_json()) == plan
    output = tmp_path / "audit"
    summary = run_gt_audit(plan, root, output)
    assert summary["automatic_error_findings"] == 0
    assert summary["manual_review_statuses"] == {"pending": 3}
    assert summary["images_without_errors"] == 2 and summary["documents_without_errors"] == 1
    assert (output / "index.html").is_file()
    _check_audit_filters(output / "index.html")
    assert all(row["result"]["checks"]["pixel_replay"] == "passed"
               for row in map(json.loads, (output / "image_results.jsonl").read_text().splitlines()))
    from scripts.run_gt_audit import main

    inventory_path = root / "manifest.json"
    inventory_path.write_text(build_manifest(root).model_dump_json(), encoding="utf-8")
    assert main(["--manifest", str(inventory_path), "--input-dir", str(root), "--output-dir", str(tmp_path / "cli_audit"),
                 "--split", "unassigned", "--all-base-pages", "--profiles", "clean", "medium_scan"]) == 0
    from scripts.prepare_gt_audit_fixture import prepare_fixture_dataset
    from polydocbench.provenance import json_sha256

    unsafe = build_manifest(root)
    bad = unsafe.records[0].model_copy(update={"language": "../escape"})
    bad = bad.model_copy(update={"artifact_id": json_sha256(bad.identity_payload())})
    unsafe.records[0] = bad
    inventory_path.write_text(unsafe.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="Language/source path mismatch"):
        prepare_fixture_dataset(tmp_path / "unsafe_output", ["technical_report"],
                                text_manifest=inventory_path, text_input_dir=root)
    assert not (tmp_path / "unsafe_output").exists()
    review_path = output / "reviews.json"
    review = json.loads(review_path.read_text())
    review["reviews"][0].update(status="accepted", reviewer="Test reviewer", reviewed_at="2026-11-09T12:00:00+03:00")
    review_path.write_text(json.dumps(review), encoding="utf-8")
    assert rebuild_gt_audit(output, root)["manual_review_statuses"] == {"accepted": 1, "pending": 2}
    review["reviews"][0]["reviewer"] = ""
    with pytest.raises(ValueError, match="named reviewer"):
        AuditReviews.model_validate(review)
    review["reviews"] = review["reviews"][1:]
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly this frozen"):
        rebuild_gt_audit(output, root)
    with pytest.raises(ValueError, match="new or empty"):
        run_gt_audit(plan, root, output)
    evidence = output / "image_results.jsonl"
    evidence.write_text(evidence.read_text() + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="evidence changed"):
        rebuild_gt_audit(output, root)


@pytest.mark.parametrize("values", [
    {"status": "accepted"},
    {"status": "defect", "reviewer": "R", "reviewed_at": "2026-11-09T12:00:00Z"},
    {"status": "accepted", "reviewer": "R", "reviewed_at": "2026-11-09T12:00:00"},
])
def test_review_decisions_require_identity_time_and_defect_notes(values):
    from polydocbench.benchmark.gt_audit import PageReview

    with pytest.raises(ValueError):
        PageReview(unit_id="test", **values)


def _check_audit_filters(path):
    if shutil.which("node") is None:
        return
    from bs4 import BeautifulSoup

    page = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    figures = [{key.removeprefix("data-"): value for key, value in figure.attrs.items() if key.startswith("data-")}
               for figure in page.find_all("figure")]
    controls = {select["id"]: [option.get("value", option.text) for option in select.find_all("option")]
                for select in page.find_all("select")}
    script = page.find("script").string
    check = r"""
const assert=require('node:assert/strict'),vm=require('node:vm');
const input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const nodes=Object.fromEntries(Object.keys(input.controls).map(id=>[id,{value:'',addEventListener(){}}]));
nodes.visible={textContent:''};const figures=input.figures.map(dataset=>({dataset,hidden:false}));
const context=vm.createContext({document:{getElementById:id=>nodes[id],querySelectorAll:()=>figures}});
vm.runInContext(input.script,context);
for(const [name,options] of Object.entries(input.controls))for(const value of options){
 Object.values(nodes).forEach(n=>n.value='');nodes[name].value=value;vm.runInContext('filter()',context);
 const expected=figures.filter(f=>!value||(name==='findings'?Number(f.dataset[value])>0:f.dataset[name]===value)).length;
 assert.equal(figures.filter(f=>!f.hidden).length,expected);
 assert.equal(nodes.visible.textContent,expected+' preview units shown');
}
"""
    result = subprocess.run([shutil.which("node"), "-e", check],
                            input=json.dumps({"figures": figures, "controls": controls, "script": script}),
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
