"""Reading-order evaluation helpers."""

from __future__ import annotations

from .geometry import bbox_iou
from .types import LineDict


def assign_columns(lines: list[LineDict], num_columns: int) -> list[LineDict]:
    """Assign simple geometric column ids by line center x-coordinate."""

    if not lines or num_columns <= 1:
        for line in lines:
            line["column"] = 0
        return lines

    centers = [line["bbox"]["x"] + line["bbox"]["width"] / 2 for line in lines]
    min_x = min(centers)
    width = max(centers) - min_x
    if width == 0:
        for line in lines:
            line["column"] = 0
        return lines

    for line in lines:
        center = line["bbox"]["x"] + line["bbox"]["width"] / 2
        column = int(((center - min_x) / width) * num_columns)
        line["column"] = min(column, num_columns - 1)

    return lines


def sort_gt_reading_order(lines: list[LineDict]) -> list[LineDict]:
    """Sort GT lines by container order, then top-to-bottom within container."""

    return sorted(lines, key=lambda line: (line.get("container_id", ""), -line["bbox"]["y"], line["bbox"]["x"]))


def sort_predicted_reading_order(lines: list[LineDict]) -> list[LineDict]:
    """Sort OCR lines by assigned column, then top-to-bottom."""

    return sorted(lines, key=lambda line: (line.get("column", 0), -line["bbox"]["y"], line["bbox"]["x"]))


def build_order_sequences(
    gt_lines: list[LineDict],
    predicted_lines: list[LineDict],
    num_columns: int,
    iou_threshold: float = 0.3,
) -> tuple[list[str], list[str]]:
    """Return GT id order and predicted order expressed in GT ids."""

    gt_sorted = sort_gt_reading_order(gt_lines)
    predicted_sorted = sort_predicted_reading_order(assign_columns(predicted_lines, num_columns))

    gt_order = [line["id"] for line in gt_sorted]
    predicted_order = _project_predictions_to_gt_order(
        gt_sorted,
        predicted_sorted,
        iou_threshold=iou_threshold,
    )
    return gt_order, predicted_order


def _project_predictions_to_gt_order(
    gt_lines: list[LineDict],
    predicted_lines: list[LineDict],
    iou_threshold: float,
) -> list[str]:
    """Match predictions in predicted order and return the matched GT ids."""

    predicted_order: list[str] = []
    used_gt_indexes: set[int] = set()

    for prediction in predicted_lines:
        best_index: int | None = None
        best_iou = 0.0

        for index, gt in enumerate(gt_lines):
            if index in used_gt_indexes:
                continue

            score = bbox_iou(gt["bbox"], prediction["bbox"])
            if score > best_iou:
                best_iou = score
                best_index = index

        if best_index is not None and best_iou >= iou_threshold:
            used_gt_indexes.add(best_index)
            predicted_order.append(gt_lines[best_index]["id"])

    return predicted_order


def kendall_tau(gt_order: list[str], predicted_order: list[str]) -> float:
    """Kendall tau over predicted ids projected into GT order."""

    gt_index = {line_id: index for index, line_id in enumerate(gt_order)}
    ranks = [gt_index[line_id] for line_id in predicted_order if line_id in gt_index]

    concordant = 0
    discordant = 0
    for i in range(len(ranks)):
        for j in range(i + 1, len(ranks)):
            if ranks[i] < ranks[j]:
                concordant += 1
            else:
                discordant += 1

    total = concordant + discordant
    return (concordant - discordant) / total if total else 0.0


def pairwise_accuracy(gt_order: list[str], predicted_order: list[str]) -> float:
    """Fraction of correctly ordered line pairs."""

    return (kendall_tau(gt_order, predicted_order) + 1.0) / 2.0


def evaluate_ordering(
    gt_lines: list[LineDict],
    predicted_lines: list[LineDict],
    num_columns: int,
    iou_threshold: float = 0.3,
) -> dict[str, float | int]:
    """Evaluate reading order with Kendall tau and pairwise accuracy."""

    gt_order, predicted_order = build_order_sequences(
        gt_lines,
        predicted_lines,
        num_columns=num_columns,
        iou_threshold=iou_threshold,
    )
    return {
        "kendall_tau": kendall_tau(gt_order, predicted_order),
        "pairwise_accuracy": pairwise_accuracy(gt_order, predicted_order),
        "num_matched": len(predicted_order),
        "num_gt": len(gt_order),
    }
