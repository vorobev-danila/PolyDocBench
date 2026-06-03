"""Structure-level document layout evaluation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import mean
from typing import Any

from .geometry import bbox_iou

TEXT_TYPES = {"paragraph", "heading", "heading1", "heading2", "heading3", "text", "text_line", "title"}

TYPE_ALIASES = {
    "section_header": "heading",
    "section-header": "heading",
    "heading1": "heading",
    "heading2": "heading",
    "heading3": "heading",
    "title": "heading",
    "text": "paragraph",
    "text_line": "paragraph",
    "list_item": "paragraph",
    "picture": "image",
    "figure": "image",
    "formula": "formula",
    "equation": "formula",
}


@dataclass(frozen=True)
class StructureMatch:
    gt: dict[str, Any]
    prediction: dict[str, Any] | None
    iou: float

    @property
    def type_correct(self) -> bool:
        return bool(self.prediction) and normalize_structure_type(self.gt.get("type")) == normalize_structure_type(
            self.prediction.get("type")
        )


def normalize_structure_type(value: Any) -> str:
    """Normalize GT and model labels into a small structure-type vocabulary."""
    text = str(value or "unknown").strip().lower().replace(" ", "_")
    return TYPE_ALIASES.get(text, text)


def extract_gt_structure_elements(gt_json: dict[str, Any], page_number: int = 1) -> list[dict[str, Any]]:
    """Extract visible structure elements from PolyDocBench GT for one image page."""
    block_elements = {
        element["id"]: element
        for element in gt_json.get("elements", [])
        if element.get("metadata", {}).get("role") == "block"
    }
    grouped_text_lines: dict[str, list[dict[str, Any]]] = defaultdict(list)
    visible_non_text_ids: set[str] = set()

    for page in gt_json.get("pages", []):
        if int(page.get("page_number", -1)) != int(page_number):
            continue
        for container in page.get("containers", []):
            for element in container.get("elements", []):
                element_type = str(element.get("type", "")).lower()
                metadata = element.get("metadata", {})
                parent_id = metadata.get("parent_id") or element.get("id", "")
                if element_type == "text_line" and str(element.get("content", "")).strip():
                    grouped_text_lines[parent_id].append(element)
                elif element.get("bbox") and parent_id:
                    parent = block_elements.get(parent_id, element)
                    if normalize_structure_type(parent.get("type")) not in {"paragraph", "heading"}:
                        visible_non_text_ids.add(parent_id)

    elements: list[dict[str, Any]] = []
    for parent_id, lines in grouped_text_lines.items():
        lines.sort(
            key=lambda line: (
                int(line.get("metadata", {}).get("line_index", 10**9)),
                int(line.get("metadata", {}).get("reading_order", 10**9)),
            )
        )
        parent = block_elements.get(parent_id, {})
        elements.append(
            {
                "id": parent_id,
                "type": normalize_structure_type(parent.get("type", "paragraph")),
                "text": " ".join(str(line.get("content", "")).strip() for line in lines),
                "bbox": _union_bbox([line["bbox"] for line in lines]),
                "polygon": parent.get("polygon"),
                "page_number": int(page_number),
                "reading_order": int(
                    parent.get("metadata", {}).get(
                        "reading_order",
                        min(int(line.get("metadata", {}).get("reading_order", 10**9)) for line in lines),
                    )
                ),
                "source": "polydocbench_gt",
                "metadata": {
                    "line_ids": [line["id"] for line in lines],
                    "parent_type": parent.get("type", "paragraph"),
                },
            }
        )

    for parent_id in visible_non_text_ids:
        parent = block_elements.get(parent_id)
        if not parent or not parent.get("bbox"):
            continue
        bbox = parent["bbox"]
        if int(bbox.get("page", page_number)) != int(page_number):
            continue
        elements.append(
            {
                "id": parent_id,
                "type": normalize_structure_type(parent.get("type")),
                "text": str(parent.get("content", "")),
                "bbox": _clean_bbox(bbox),
                "polygon": parent.get("polygon"),
                "page_number": int(page_number),
                "reading_order": int(parent.get("metadata", {}).get("reading_order", 10**9)),
                "source": "polydocbench_gt",
                "metadata": {"parent_type": parent.get("type")},
            }
        )

    return sorted(elements, key=lambda element: (int(element.get("reading_order", 10**9)), str(element["id"])))


def match_structure_elements(
    gt_elements: list[dict[str, Any]],
    predicted_elements: list[dict[str, Any]],
    *,
    iou_threshold: float = 0.5,
) -> list[StructureMatch]:
    """Greedily match structure elements by IoU."""
    candidates: list[tuple[float, int, int]] = []
    for gt_index, gt in enumerate(gt_elements):
        if not gt.get("bbox"):
            continue
        for prediction_index, prediction in enumerate(predicted_elements):
            if not prediction.get("bbox"):
                continue
            score = bbox_iou(gt["bbox"], prediction["bbox"])
            if score >= iou_threshold:
                candidates.append((score, gt_index, prediction_index))

    used_gt: set[int] = set()
    used_predictions: set[int] = set()
    matched_by_gt: dict[int, StructureMatch] = {}
    for score, gt_index, prediction_index in sorted(candidates, key=lambda item: item[0], reverse=True):
        if gt_index in used_gt or prediction_index in used_predictions:
            continue
        used_gt.add(gt_index)
        used_predictions.add(prediction_index)
        matched_by_gt[gt_index] = StructureMatch(gt_elements[gt_index], predicted_elements[prediction_index], score)

    matches: list[StructureMatch] = []
    for gt_index, gt in enumerate(gt_elements):
        matches.append(matched_by_gt.get(gt_index, StructureMatch(gt, None, 0.0)))
    return matches


def evaluate_structure(
    gt_elements: list[dict[str, Any]],
    predicted_elements: list[dict[str, Any]],
    *,
    iou_threshold: float = 0.5,
) -> tuple[dict[str, float | int], list[StructureMatch]]:
    """Evaluate layout structure detection and type classification."""
    matches = match_structure_elements(gt_elements, predicted_elements, iou_threshold=iou_threshold)
    matched = [match for match in matches if match.prediction is not None]
    type_correct = [match for match in matched if match.type_correct]

    gt_count = len(gt_elements)
    prediction_count = len(predicted_elements)
    matched_count = len(matched)
    type_correct_count = len(type_correct)

    detection_precision = matched_count / prediction_count if prediction_count else 0.0
    detection_recall = matched_count / gt_count if gt_count else 0.0
    detection_f1 = _f1(detection_precision, detection_recall)
    type_accuracy = type_correct_count / matched_count if matched_count else 0.0
    mean_iou = mean(match.iou for match in matched) if matched else 0.0
    type_aware_precision = type_correct_count / prediction_count if prediction_count else 0.0
    type_aware_recall = type_correct_count / gt_count if gt_count else 0.0
    type_aware_f1 = _f1(type_aware_precision, type_aware_recall)

    metrics: dict[str, float | int] = {
        "num_gt_elements": gt_count,
        "num_predicted_elements": prediction_count,
        "num_matched_elements": matched_count,
        "num_type_correct": type_correct_count,
        "false_positive_count": max(0, prediction_count - matched_count),
        "false_negative_count": max(0, gt_count - matched_count),
        "detection_precision": detection_precision,
        "detection_recall": detection_recall,
        "detection_F1": detection_f1,
        "mean_iou": mean_iou,
        "type_accuracy": type_accuracy,
        "type_aware_precision": type_aware_precision,
        "type_aware_recall": type_aware_recall,
        "type_aware_F1": type_aware_f1,
        "structure_score": 0.4 * detection_f1 + 0.3 * mean_iou + 0.3 * type_accuracy,
    }
    metrics.update(_per_type_metrics(gt_elements, predicted_elements, matched))
    return metrics, matches


def structure_matches_to_dicts(matches: list[StructureMatch]) -> list[dict[str, Any]]:
    """Serialize structure matches for experiment artifacts."""
    return [
        {
            "gt_id": match.gt.get("id"),
            "gt_type": normalize_structure_type(match.gt.get("type")),
            "prediction_id": match.prediction.get("id") if match.prediction else None,
            "prediction_type": normalize_structure_type(match.prediction.get("type")) if match.prediction else None,
            "iou": match.iou,
            "type_correct": match.type_correct,
        }
        for match in matches
    ]


def _per_type_metrics(
    gt_elements: list[dict[str, Any]], predicted_elements: list[dict[str, Any]], matched: list[StructureMatch]
) -> dict[str, float | int]:
    gt_by_type: defaultdict[str, int] = defaultdict(int)
    pred_by_type: defaultdict[str, int] = defaultdict(int)
    correct_by_type: defaultdict[str, int] = defaultdict(int)
    for element in gt_elements:
        gt_by_type[normalize_structure_type(element.get("type"))] += 1
    for element in predicted_elements:
        pred_by_type[normalize_structure_type(element.get("type"))] += 1
    for match in matched:
        if match.type_correct:
            correct_by_type[normalize_structure_type(match.gt.get("type"))] += 1

    metrics: dict[str, float | int] = {}
    for element_type in sorted(set(gt_by_type) | set(pred_by_type)):
        safe_type = element_type.replace("-", "_")
        precision = correct_by_type[element_type] / pred_by_type[element_type] if pred_by_type[element_type] else 0.0
        recall = correct_by_type[element_type] / gt_by_type[element_type] if gt_by_type[element_type] else 0.0
        metrics[f"per_type_{safe_type}_precision"] = precision
        metrics[f"per_type_{safe_type}_recall"] = recall
        metrics[f"per_type_{safe_type}_F1"] = _f1(precision, recall)
    return metrics


def _f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _union_bbox(bboxes: list[dict[str, Any]]) -> dict[str, float]:
    min_x = min(float(bbox["x"]) for bbox in bboxes)
    min_y = min(float(bbox["y"]) for bbox in bboxes)
    max_x = max(float(bbox["x"]) + float(bbox["width"]) for bbox in bboxes)
    max_y = max(float(bbox["y"]) + float(bbox["height"]) for bbox in bboxes)
    return {"x": min_x, "y": min_y, "width": max_x - min_x, "height": max_y - min_y}


def _clean_bbox(bbox: dict[str, Any]) -> dict[str, float]:
    return {
        "x": float(bbox["x"]),
        "y": float(bbox["y"]),
        "width": float(bbox["width"]),
        "height": float(bbox["height"]),
    }
