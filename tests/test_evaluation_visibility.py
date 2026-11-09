from copy import deepcopy
import json

import pytest

from polydocbench.eval.scoped import evaluate_with_visibility
from polydocbench.eval.scope import VisibilityPolicy, prepare_scope
from polydocbench.eval.protocol import result_protocol_version
from polydocbench.eval.quality import aggregate_ocr_counts
from polydocbench.gt.visibility import visibility_facts
from polydocbench.noise.geometry import transform_gt_to_image_gt
from test_gt_audit import document


def image_gt(*, shift=0, figure=True, more_text=False):
    source = document()
    if more_text:
        for index, y in ((2, 40), (3, 60)):
            block = {"id": f"p{index}", "type": "paragraph", "content": f"Block {index}",
                     "bbox": {"x": 10, "y": y, "width": 20, "height": 10, "page": 1},
                     "metadata": {"role": "block", "source_index": index, "reading_order": index}}
            line = {**deepcopy(block), "id": f"l{index}", "type": "text_line",
                    "metadata": {"role": "line", "source_index": index, "reading_order": index,
                                 "parent_id": f"p{index}", "line_index": 1}}
            source["elements"].extend([block, line])
            source["reading_order"]["blocks"].append(block["id"])
            source["reading_order"]["lines"].append(line["id"])
            source["pages"][0]["containers"][0]["elements"].append(deepcopy(line))
    if figure:
        block = {"id": "figure", "type": "image", "content": "",
                 "bbox": {"x": 75, "y": 35, "width": 20, "height": 20, "page": 1},
                 "metadata": {"role": "block", "source_index": 10, "reading_order": len(source["reading_order"]["blocks"]) + 1}}
        source["elements"].append(block)
        source["reading_order"]["blocks"].append("figure")
        source["pages"][0]["containers"][0]["elements"].append(deepcopy(block))
    container = source["pages"][0]["containers"][0]
    container["element_count"] = len(container["elements"])
    return transform_gt_to_image_gt(source, "image.png", "document.pdf", "document_gt.json", 1, 2, 160,
                                    200, 160, [[1, 0, shift], [0, 1, 0]], "example", 0, 144)


def prediction(text="Alpha beta", x=20, y=100, width=120, height=20, **kwargs):
    return {"text": text, "bbox": {"x": x, "y": y, "width": width, "height": height}, **kwargs}


def evaluate(gt, predictions, task="quality", **kwargs):
    return evaluate_with_visibility(gt, predictions, task=task, policy=VisibilityPolicy(), **kwargs)


def test_new_gt_has_visibility_facts_without_task_specific_eligibility():
    gt = image_gt(shift=100)
    fact = gt["elements"][0]["metadata"]["geometry_visibility"]
    assert fact["status"] == "partial" and fact["visible_fraction"] == pytest.approx(2 / 3)
    assert "eligible" not in fact
    assert visibility_facts([[0, 0], [10, 0], [10, 10], [0, 10]], 200, 160)["status"] == "inside"


def test_figure_text_is_ignored_but_real_insertion_is_penalized():
    output = evaluate(image_gt(), [prediction(), prediction("Plot labels", x=155, y=55, width=20, height=10),
                                   prediction("spurious", x=5, y=5, width=20, height=10)])
    assert output.metrics["evaluation_protocol_version"] == "0.3"
    assert output.metrics["scope_ignored_predictions"] == 1
    assert output.scope["retained_prediction_indices"] == [0, 2]
    assert output.metrics["char_errors"] == len("spurious")
    assert output.metrics["false_positive_lines"] == 1
    assert output.metrics["micro_CER"] > 0


def test_clipped_full_text_is_not_compared_to_truncated_prediction_and_null_is_not_perfect():
    output = evaluate(image_gt(shift=100), [prediction("Alpha", x=125, y=100, width=60),
                                             prediction("extra", x=5, y=5, width=20, height=10)])
    assert output.metrics["scope_excluded_partially_clipped"] == 1
    assert output.metrics["scope_eligible_gt"] == 0
    assert output.metrics["micro_CER"] is None and output.metrics["line_F1"] is None
    assert output.metrics["char_errors"] == 5 and output.metrics["false_positive_lines"] == 1
    assert aggregate_ocr_counts([output.metrics])["micro_CER"] is None
    normal = evaluate(image_gt(), [prediction()])
    pooled = aggregate_ocr_counts([normal.metrics, output.metrics])
    assert pooled["micro_CER"] == pytest.approx(5 / len("Alpha beta"))


def test_eligible_gt_overlap_prevents_ignoring_wrong_text_or_duplicates():
    gt = image_gt()
    for e in [*gt["elements"], *gt["pages"][0]["containers"][0]["elements"]]:
        if e["id"] == "figure":
            e["polygon"] = [[0, 0], [200, 0], [200, 160], [0, 160]]
            e["bbox"] = {"x": 0, "y": 0, "width": 200, "height": 160, "page": 1}
            e["metadata"].pop("geometry_visibility", None)
    output = evaluate(gt, [prediction(), prediction("wrong text")])
    assert output.metrics["scope_ignored_predictions"] == 0
    assert output.metrics["scope_protected_predictions"] == 2
    assert output.metrics["false_positive_lines"] == 1 and output.metrics["char_errors"] > 0


def test_mixed_prediction_crossing_ignored_and_scored_space_is_never_trimmed():
    output = evaluate(image_gt(), [prediction("Mixed hallucination", x=0, y=50, width=200, height=80)])
    assert output.metrics["scope_ignored_predictions"] == 0
    assert output.scope["predictions"][0]["reason"] == "eligible_gt_overlap"


def test_native_order_is_preserved_and_incomplete_blocks_are_excluded_whole():
    gt = image_gt(shift=100, figure=False, more_text=True)
    predictions = [prediction("Block 3", x=120, y=20, width=40),
                   prediction("Alpha", x=125, y=100, width=60), prediction("Block 2", x=120, y=60, width=40)]
    output = evaluate(gt, predictions, task="ordering")
    assert output.scope["retained_prediction_indices"] == [0, 2]
    assert output.metrics["scope_excluded_incomplete_text_block"] == 1
    assert output.metrics["pairwise_accuracy"] == 0
    assert output.metrics["scope_eligible_gt_pairs"] == 1
    assert output.metrics["scope_input_gt_pairs"] == 3


def test_ordering_unlocalized_predictions_are_retained_not_text_filtered():
    output = evaluate(image_gt(), [{"text": "Unknown plot text without a bbox"}], task="ordering")
    assert output.metrics["scope_unlocalized_predictions"] == 1
    assert output.metrics["num_predicted_blocks"] == 1
    assert output.metrics["ordered_WER"] > 0


def test_structure_does_not_ignore_wrong_class_inside_a_target_image():
    output = evaluate(image_gt(), [prediction("plot", x=150, y=50, width=40, height=40, type="paragraph")], task="structure")
    assert output.metrics["scope_ignored_predictions"] == 0
    assert output.metrics["num_gt_elements"] == 2
    assert output.metrics["num_type_correct"] == 0


def test_structure_partial_policy_is_explicit_and_affects_policy_identity():
    gt = image_gt(shift=100, figure=False)
    conservative = evaluate(gt, [], task="structure")
    visible = evaluate_with_visibility(gt, [], task="structure", policy=VisibilityPolicy(structure_partial="visible"))
    assert conservative.metrics["structure_score"] is None
    assert visible.metrics["num_gt_elements"] == 1 and visible.metrics["structure_score"] == 0
    with pytest.raises(ValueError, match="visibility policies"):
        result_protocol_version([conservative.metrics, visible.metrics])


def test_scoped_structure_has_one_caption_target_per_stable_block_id():
    from polydocbench.eval.structure import extract_gt_structure_elements

    gt = image_gt()
    caption = gt["elements"][0]
    caption["type"] = "caption"
    caption["metadata"]["caption_for"] = "figure"
    container = gt["pages"][0]["containers"][0]
    container["elements"].append(deepcopy(caption))
    container["element_count"] += 1
    assert len(extract_gt_structure_elements(gt)) == 3
    prepared = prepare_scope(gt, "structure", VisibilityPolicy())
    assert len(prepared.gt) == 2 and len({e["id"] for e in prepared.gt}) == 2


def test_manual_regions_are_task_specific_and_union_area_is_not_double_counted():
    gt = image_gt(figure=False)
    gt["metadata"]["evaluation_ignore_regions"] = [
        {"id": "a", "tasks": ["quality"], "reason": "unannotated_stamp", "polygon": [[0, 0], [20, 0], [20, 20], [0, 20]]},
        {"id": "b", "tasks": ["quality"], "reason": "unannotated_stamp", "polygon": [[10, 0], [30, 0], [30, 20], [10, 20]]},
    ]
    output = evaluate(gt, [prediction(), prediction("stamp", x=5, y=5, width=20, height=10)])
    assert output.metrics["scope_ignored_predictions"] == 1
    assert output.metrics["scope_ignored_area_fraction"] == pytest.approx(600 / (200 * 160))
    assert evaluate(gt, [], task="structure").metrics["scope_ignore_region_count"] == 0


@pytest.mark.parametrize("fault", ["polygon", "facts", "pdf", "metadata"])
def test_invalid_gt_fails_closed_before_exclusion(fault):
    gt = image_gt()
    if fault == "polygon":
        gt["elements"][0].pop("polygon")
    elif fault == "facts":
        gt["elements"][0]["metadata"]["geometry_visibility"]["visible_fraction"] = 0
    elif fault == "pdf":
        gt["metadata"]["coordinate_system"] = "points"
    else:
        gt["reading_order"]["lines"] = []
    with pytest.raises(ValueError):
        evaluate(gt, [])


def test_off_canvas_hallucination_is_not_silently_ignored():
    output = evaluate(image_gt(shift=100), [prediction("outside", x=300, y=100)])
    assert output.metrics["scope_ignored_predictions"] == 0 and output.metrics["false_positive_lines"] == 1


def test_scope_identity_binds_gt_text_and_predictions_and_does_not_mutate_inputs():
    gt, predictions = image_gt(), [prediction()]
    before = deepcopy((gt, predictions))
    output = evaluate(gt, predictions)
    assert (gt, predictions) == before
    changed = image_gt()
    for e in [*changed["elements"], *changed["pages"][0]["containers"][0]["elements"]]:
        if e["id"] in {"p", "l"}:
            e["content"] = "Different"
    assert evaluate(changed, predictions).metrics["scope_id"] != output.metrics["scope_id"]
    with pytest.raises(ValueError, match="different evaluation protocols"):
        result_protocol_version([output.metrics, {"evaluation_protocol_version": "0.2"}])


def test_conflicting_prediction_polygon_cannot_hide_a_bbox_error_over_eligible_gt():
    pred = prediction("wrong text", polygon=[[155, 55], [175, 55], [175, 65], [155, 65]])
    output = evaluate(image_gt(), [pred])
    assert output.metrics["scope_ignored_predictions"] == 0
    assert output.metrics["char_errors"] > 0


def test_forged_gt_polygon_cannot_create_an_ignore_mask():
    gt = image_gt()
    for e in [*gt["elements"], *gt["pages"][0]["containers"][0]["elements"]]:
        if e["id"] == "l":
            e["polygon"] = [[180, 100], [280, 100], [280, 120], [180, 120]]
            e["metadata"].pop("geometry_visibility", None)
    with pytest.raises(ValueError, match="polygon envelope"):
        evaluate(gt, [])


def test_line_ordering_uses_explicit_gt_order_and_top_left_image_coordinates():
    gt = image_gt(figure=False, more_text=True)
    gt["reading_order"]["lines"] = ["l3", "l2", "l"]
    output = evaluate(gt, [prediction(), prediction("Block 2", y=60, width=40),
                            prediction("Block 3", y=20, width=40)], task="line_ordering")
    assert output.metrics["pairwise_accuracy"] == 1
    assert output.metrics["ordering_mode"] == "geometric_top_left_lines"


@pytest.mark.parametrize("task,writer_name", [("quality", "write_ocr_dashboard"), ("ordering", "write_ordering_dashboard"), ("structure", "write_structure_dashboard")])
def test_empty_scope_reports_are_nullable_and_include_coverage(tmp_path, monkeypatch, task, writer_name):
    pytest.importorskip("plotly")
    import polydocbench.eval as evaluation
    import plotly.graph_objects as go

    captured = []
    original = go.Figure.write_html

    def capture(self, *args, **kwargs):
        captured.append(self.to_plotly_json())
        return original(self, *args, **kwargs)

    monkeypatch.setattr(go.Figure, "write_html", capture)

    result = evaluate(image_gt(shift=100, figure=False), [], task=task)
    row = {"language": "en", "template": "simple_article", "profile": "clean", "article_id": "fixture",
           "language_name": "English", "tesseract_lang": "eng", "model": "stub", **result.metrics}
    target = tmp_path / f"{task}.html"
    getattr(evaluation, writer_name)(target, [row])
    table = next(trace for trace in captured[0]["data"] if trace["type"] == "table")
    assert "GT kept/total" in table["header"]["values"]
    assert len(table["header"]["values"]) == len(table["cells"]["values"])
    if task == "quality":
        from scripts.run_tesseract_ocr_experiment import _write_summary
    elif task == "ordering":
        from scripts.run_dotsocr_ordering_experiment import _write_summary
    else:
        from scripts.run_docling_structure_experiment import _write_summary
    _write_summary(tmp_path / f"{task}.csv", [row])
    assert "scope_empty_gt_images" in (tmp_path / f"{task}.csv").read_text()


@pytest.mark.parametrize("route,prediction_key", [("quality", "predicted_lines"), ("ordering", "predicted_lines"), ("structure", "predicted_elements")])
def test_api_exposes_opt_in_policy_and_full_decision_ledger(tmp_path, route, prediction_key):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from polydocbench.api.app import app

    path = tmp_path / "image_gt.json"
    path.write_text(json.dumps(image_gt()), encoding="utf-8")
    response = TestClient(app).post(f"/evaluate/{route}", json={"gt_path": str(path), prediction_key: [], "visibility_policy": {}})
    assert response.status_code == 200, response.text
    assert response.json()["evaluation_protocol_version"] == "0.3"
    assert response.json()["evaluation_scope"]["policy_id"] == response.json()["scope_policy_id"]


def test_policy_is_frozen_and_existing_metrics_are_not_overwritten(tmp_path):
    from argparse import Namespace
    from polydocbench.eval.scoped import check_result_output, visibility_from_args

    path = tmp_path / "policy.json"
    path.write_text(VisibilityPolicy().model_dump_json())
    args = Namespace(visibility_policy=path)
    frozen = visibility_from_args(args)
    path.write_text(VisibilityPolicy(structure_partial="visible").model_dump_json())
    assert visibility_from_args(args) == frozen
    output = tmp_path / "results"
    check_result_output(output, frozen)
    (output / "metrics.jsonl").write_text('{"evaluation_protocol_version":"0.2"}\n')
    with pytest.raises(ValueError, match="new metrics"):
        check_result_output(output, frozen)


def test_scoped_worker_records_ledger_and_rejects_bad_gt_before_inference(tmp_path):
    from polydocbench.benchmark.pilot import prepare_pilot
    from polydocbench.benchmark.pilot_runtime import default_model_config
    from polydocbench.benchmark.pilot_worker import PilotAdapter, run_worker
    from test_benchmark_pilot import make_inventory

    plan = prepare_pilot(make_inventory(profiles=("clean",)), base_pages=1, profiles=["clean"], split="unassigned")
    record = plan.selection.records[0]
    path = tmp_path / record.image_gt.path
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(image_gt()), encoding="utf-8")
    config = {**default_model_config(), "visibility_policy": VisibilityPolicy().model_dump()}

    class Adapter(PilotAdapter):
        calls = 0

        def predict(self, *args):
            self.calls += 1
            return [prediction(), prediction("plot", x=155, y=55, width=20, height=10)]

    job = {"plan": plan.model_dump(), "input_dir": str(tmp_path), "engine": "tesseract", "config": config}
    output = tmp_path / "valid"
    output.mkdir()
    adapter = Adapter("tesseract", config)
    run_worker(job, output, adapter)
    events = [json.loads(x) for x in (output / "events.jsonl").read_text().splitlines()]
    row = next(r for r in events if r["event"] == "result")
    assert row["status"] == "success" and row["metrics"]["scope_ignored_predictions"] == 1
    assert (output / row["scope_path"]).exists() and adapter.calls == 1
    data = image_gt()
    data["reading_order"]["lines"] = []
    path.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "invalid"
    output.mkdir()
    adapter.calls = 0
    run_worker(job, output, adapter)
    row = next(json.loads(x) for x in (output / "events.jsonl").read_text().splitlines() if json.loads(x)["event"] == "result")
    assert row["status"] == "failed" and row["failed_stage"] == "validation" and adapter.calls == 0
