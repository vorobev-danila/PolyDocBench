"""Semantic-block extraction and matching for reading-order experiments."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from .geometry import bbox_iou
from .text_metrics import normalize_text


@dataclass(frozen=True)
class BlockMatch:
    prediction_index: int
    prediction: dict[str, Any]
    gt_blocks: tuple[dict[str, Any], ...]
    similarity: float

    @property
    def gt_ids(self) -> list[str]:
        return [block["id"] for block in self.gt_blocks]


def extract_visible_gt_blocks(gt_json: dict[str, Any], page_number: int = 1) -> list[dict[str, Any]]:
    """Build visible textual blocks by grouping transformed GT lines by their parent id."""
    block_elements = {
        element["id"]: element
        for element in gt_json.get("elements", [])
        if element.get("metadata", {}).get("role") == "block"
    }
    grouped_lines: dict[str, list[dict[str, Any]]] = {}
    for page in gt_json.get("pages", []):
        if int(page.get("page_number", -1)) != int(page_number):
            continue
        for container in page.get("containers", []):
            for element in container.get("elements", []):
                if element.get("type") != "text_line" or not str(element.get("content", "")).strip():
                    continue
                parent_id = element.get("metadata", {}).get("parent_id") or element["id"]
                grouped_lines.setdefault(parent_id, []).append(element)

    visible_blocks: list[dict[str, Any]] = []
    for parent_id, lines in grouped_lines.items():
        lines.sort(
            key=lambda line: (
                int(line.get("metadata", {}).get("line_index", 10**9)),
                int(line.get("metadata", {}).get("reading_order", 10**9)),
            )
        )
        parent = block_elements.get(parent_id, {})
        visible_blocks.append(
            {
                "id": parent_id,
                "category": parent.get("type", "text"),
                "text": " ".join(str(line.get("content", "")).strip() for line in lines),
                "bbox": _union_bbox([line["bbox"] for line in lines]),
                "reading_order": int(
                    parent.get("metadata", {}).get(
                        "reading_order",
                        min(int(line.get("metadata", {}).get("reading_order", 10**9)) for line in lines),
                    )
                ),
                "line_ids": [line["id"] for line in lines],
            }
        )
    return sorted(visible_blocks, key=lambda block: block["reading_order"])


def match_semantic_blocks(
    gt_blocks: list[dict[str, Any]],
    predicted_blocks: list[dict[str, Any]],
    *,
    min_similarity: float = 0.3,
    max_gt_span: int = 3,
    geometry_weight: float = 0.05,
) -> list[BlockMatch]:
    """Match a predicted block to one or more adjacent GT blocks using text-first similarity."""
    candidates: list[tuple[float, int, int, int]] = []
    for prediction_index, prediction in enumerate(predicted_blocks):
        for start in range(len(gt_blocks)):
            for span in range(1, min(max_gt_span, len(gt_blocks) - start) + 1):
                candidate_blocks = gt_blocks[start : start + span]
                candidate_text = " ".join(block["text"] for block in candidate_blocks)
                text_score = SequenceMatcher(
                    None, normalize_text(candidate_text), normalize_text(str(prediction.get("text", "")))
                ).ratio()
                geometry_score = _span_iou(candidate_blocks, prediction)
                score = text_score
                if geometry_score is not None:
                    score = (1.0 - geometry_weight) * text_score + geometry_weight * geometry_score
                if score >= min_similarity:
                    candidates.append((score, prediction_index, start, span))

    used_predictions: set[int] = set()
    used_gt_indexes: set[int] = set()
    matches: list[BlockMatch] = []
    for score, prediction_index, start, span in sorted(candidates, key=lambda item: item[0], reverse=True):
        indexes = set(range(start, start + span))
        if prediction_index in used_predictions or indexes & used_gt_indexes:
            continue
        used_predictions.add(prediction_index)
        used_gt_indexes.update(indexes)
        matches.append(
            BlockMatch(
                prediction_index=prediction_index,
                prediction=predicted_blocks[prediction_index],
                gt_blocks=tuple(gt_blocks[start : start + span]),
                similarity=score,
            )
        )
    return sorted(matches, key=lambda match: match.prediction_index)


def _span_iou(gt_blocks: list[dict[str, Any]], prediction: dict[str, Any]) -> float | None:
    if not prediction.get("bbox") or not gt_blocks or any(not block.get("bbox") for block in gt_blocks):
        return None
    return bbox_iou(_union_bbox([block["bbox"] for block in gt_blocks]), prediction["bbox"])


def _union_bbox(bboxes: list[dict[str, Any]]) -> dict[str, float]:
    min_x = min(float(bbox["x"]) for bbox in bboxes)
    min_y = min(float(bbox["y"]) for bbox in bboxes)
    max_x = max(float(bbox["x"]) + float(bbox["width"]) for bbox in bboxes)
    max_y = max(float(bbox["y"]) + float(bbox["height"]) for bbox in bboxes)
    return {"x": min_x, "y": min_y, "width": max_x - min_x, "height": max_y - min_y}
