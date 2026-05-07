"""Line matching utilities based on geometry overlap."""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import bbox_iou
from .types import LineDict


@dataclass(frozen=True)
class LineMatch:
    gt: LineDict
    prediction: LineDict | None
    iou: float


def match_lines(
    gt_lines: list[LineDict],
    predicted_lines: list[LineDict],
    iou_threshold: float = 0.3,
    one_to_one: bool = True,
) -> list[LineMatch]:
    """Match GT lines to predicted lines by best IoU."""

    matches: list[LineMatch] = []
    used_prediction_ids: set[int] = set()

    for gt in gt_lines:
        best_index: int | None = None
        best_iou = 0.0

        for index, prediction in enumerate(predicted_lines):
            if one_to_one and index in used_prediction_ids:
                continue

            score = bbox_iou(gt["bbox"], prediction["bbox"])
            if score > best_iou:
                best_iou = score
                best_index = index

        if best_index is not None and best_iou >= iou_threshold:
            used_prediction_ids.add(best_index)
            matches.append(LineMatch(gt, predicted_lines[best_index], best_iou))
        else:
            matches.append(LineMatch(gt, None, 0.0))

    return matches

