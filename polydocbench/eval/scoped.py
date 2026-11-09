"""Document-aware, opt-in evaluation protocol 0.3; legacy metrics stay unchanged."""

from dataclasses import dataclass, replace
import json
from pathlib import Path

from .scope import Task, VisibilityPolicy, prepare_scope
from .protocol import result_protocol_version

SCOPED_EVALUATION_PROTOCOL_VERSION = "0.3"


@dataclass
class ScopedEvaluation:
    metrics: dict
    matches: list
    scope: dict


def evaluate_with_visibility(gt: dict, predictions: list[dict], *, task: Task,
                             policy: VisibilityPolicy | dict, page_number: int = 1,
                             iou_threshold: float | None = None, min_similarity: float = 0.3,
                             max_gt_span: int = 3, num_columns: int = 1) -> ScopedEvaluation:
    prepared = prepare_scope(gt, task, policy, page_number=page_number)
    kept, ledger, coverage = prepared.filter_predictions(predictions)
    matches = []
    if task == "quality":
        from .quality import evaluate_ocr_quality

        metrics = evaluate_ocr_quality(prepared.gt, kept, iou_threshold=0.3 if iou_threshold is None else iou_threshold)
        undefined = ("CER", "WER", "macro_CER", "macro_WER", "micro_CER", "micro_WER", "IoU",
                     "matched_ratio", "line_precision", "line_recall", "line_F1")
    elif task == "ordering":
        from .ordered_text import evaluate_semantic_ordering

        metrics, matches = evaluate_semantic_ordering(prepared.gt, kept, min_similarity=min_similarity, max_gt_span=max_gt_span)
        matches = [replace(match, prediction_index=ledger["retained_prediction_indices"][match.prediction_index]) for match in matches]
        undefined = ("ordered_CER", "ordered_WER", "token_precision", "token_recall", "token_F1",
                     "matched_block_ratio", "matched_prediction_ratio", "order_pair_coverage", "pairwise_accuracy", "kendall_tau")
    elif task == "line_ordering":
        from .ordering import assign_columns, evaluate_order_pairs, _project_predictions_to_gt_order

        threshold = 0.3 if iou_threshold is None else iou_threshold
        spatial = sorted(assign_columns([dict(p) for p in kept], num_columns),
                         key=lambda p: (p.get("column", 0), p["bbox"]["y"], p["bbox"]["x"]))
        sequence = _project_predictions_to_gt_order(prepared.gt, spatial, threshold)
        metrics = {**evaluate_order_pairs([e["id"] for e in prepared.gt], [[i] for i in sequence]),
                   "num_matched": len(sequence), "num_gt": len(prepared.gt), "num_columns": num_columns,
                   "matching_iou_threshold": threshold, "ordering_mode": "geometric_top_left_lines"}
        undefined = ("order_pair_coverage", "pairwise_accuracy", "kendall_tau")
    else:
        from .structure import evaluate_structure

        metrics, matches = evaluate_structure(prepared.gt, kept, iou_threshold=0.5 if iou_threshold is None else iou_threshold)
        undefined = tuple(key for key, value in metrics.items() if isinstance(value, float))
    if not prepared.gt:
        metrics.update({key: None for key in undefined})
    if task in {"ordering", "line_ordering"} and len(prepared.gt) < 2:
        metrics["order_pair_coverage"] = None
    metrics.update(coverage)
    metrics["evaluation_protocol_version"] = SCOPED_EVALUATION_PROTOCOL_VERSION
    return ScopedEvaluation(metrics, matches, ledger)


def visibility_from_args(args):
    from .scope import load_visibility_policy

    if not hasattr(args, "_frozen_visibility_policy"):
        path = getattr(args, "visibility_policy", None)
        args._frozen_visibility_policy = load_visibility_policy(path) if path is not None else None
    return args._frozen_visibility_policy


def check_result_output(output: Path, policy: VisibilityPolicy | None):
    path = output / "metrics.jsonl"
    if policy is not None and path.exists():
        raise ValueError("Visibility evaluation requires a new metrics output directory; preserve historical results")
    if path.exists() and any(json.loads(line).get("evaluation_protocol_version") == "0.3"
                             for line in path.read_text(encoding="utf-8").splitlines() if line.strip()):
        raise ValueError("Do not overwrite visibility results with a legacy run; choose a new directory")
    if policy is not None:
        output.mkdir(parents=True, exist_ok=True)
        config_path = output / "visibility_policy.json"
        if config_path.exists() and json.loads(config_path.read_text(encoding="utf-8")) != policy.model_dump():
            raise ValueError("Output directory contains a different visibility policy")
        config_path.write_text(policy.model_dump_json(indent=2), encoding="utf-8")
    elif (output / "visibility_policy.json").exists():
        raise ValueError("Output directory is reserved for visibility evaluation")


def scope_summary(rows):
    if not rows or not any(r.get("evaluation_protocol_version") == "0.3" for r in rows):
        return {}
    result_protocol_version(rows)
    keys = ("scope_input_gt", "scope_eligible_gt", "scope_excluded_gt", "scope_input_predictions",
            "scope_retained_predictions", "scope_ignored_predictions", "scope_unlocalized_predictions",
            "scope_protected_predictions", "scope_empty_gt_images", "scope_canvas_area_pixels", "scope_ignored_area_pixels",
            "scope_excluded_fully_clipped", "scope_excluded_partially_clipped", "scope_excluded_incomplete_text_block", "scope_excluded_manual_region")
    result = {key: sum(r[key] for r in rows) for key in keys}
    result.update(scope_policy_id=rows[0]["scope_policy_id"], scope_task=rows[0]["scope_task"],
                  scope_unit=rows[0]["scope_unit"], scope_policy_status=rows[0]["scope_policy_status"],
                  scope_eligible_gt_fraction=result["scope_eligible_gt"] / result["scope_input_gt"] if result["scope_input_gt"] else None,
                  scope_ignored_area_fraction=result["scope_ignored_area_pixels"] / result["scope_canvas_area_pixels"])
    return result


def scope_table_columns(rows):
    if not rows or "scope_input_gt" not in rows[0]:
        return [], []
    return ["GT kept/total", "Pred ignored/total", "Empty GT images"], [
        [f"{r['scope_eligible_gt']}/{r['scope_input_gt']}" for r in rows],
        [f"{r['scope_ignored_predictions']}/{r['scope_input_predictions']}" for r in rows],
        [r["scope_empty_gt_images"] for r in rows]]
