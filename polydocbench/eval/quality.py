"""High-level OCR quality evaluation."""

from __future__ import annotations

from typing import Any

from .matching import match_lines
from .protocol import EVALUATION_PROTOCOL_VERSION
from .text_metrics import edit_distance, normalize_text
from .types import LineDict


def evaluate_ocr_quality(
    gt_lines: list[LineDict],
    predicted_lines: list[LineDict],
    iou_threshold: float = 0.3,
) -> dict[str, float | int | str]:
    """Report legacy line means and insertion-aware micro text/detection scores.

    Matching remains greedy one-to-one bbox IoU. Micro errors include deletions
    for missing GT lines and insertions for every unmatched prediction.
    """

    matches = match_lines(gt_lines, predicted_lines, iou_threshold=iou_threshold)
    total_cer = 0.0
    total_wer = 0.0
    total_iou = 0.0
    matched = 0
    char_errors = word_errors = gt_char_count = gt_word_count = 0
    used_predictions: set[int] = set()

    for match in matches:
        prediction_text = match.prediction["text"] if match.prediction else ""
        total_iou += match.iou
        matched += int(match.prediction is not None)
        if match.prediction_index is not None:
            used_predictions.add(match.prediction_index)
        gt_text = normalize_text(match.gt["text"])
        predicted_text = normalize_text(prediction_text)
        gt_char_count += len(gt_text)
        gt_word_count += len(gt_text.split())
        line_char_errors = edit_distance(gt_text, predicted_text)
        line_word_errors = edit_distance(gt_text.split(), predicted_text.split())
        char_errors += line_char_errors
        word_errors += line_word_errors
        total_cer += line_char_errors / max(1, len(gt_text))
        total_wer += line_word_errors / max(1, len(gt_text.split()))

    for index, prediction in enumerate(predicted_lines):
        if index not in used_predictions:
            text = normalize_text(prediction["text"])
            char_errors += len(text)
            word_errors += len(text.split())

    count = len(matches)
    precision = matched / len(predicted_lines) if predicted_lines else 0.0
    recall = matched / count if count else 0.0
    return {
        "evaluation_protocol_version": EVALUATION_PROTOCOL_VERSION,
        "matching_iou_threshold": iou_threshold,
        "CER": total_cer / max(1, count),
        "WER": total_wer / max(1, count),
        "macro_CER": total_cer / max(1, count),
        "macro_WER": total_wer / max(1, count),
        "IoU": total_iou / max(1, count),
        "matched_ratio": recall,
        "micro_CER": char_errors / max(1, gt_char_count),
        "micro_WER": word_errors / max(1, gt_word_count),
        "char_errors": char_errors,
        "word_errors": word_errors,
        "gt_char_count": gt_char_count,
        "gt_word_count": gt_word_count,
        "num_gt_lines": count,
        "num_predicted_lines": len(predicted_lines),
        "num_matched_lines": matched,
        "false_positive_lines": len(predicted_lines) - matched,
        "false_negative_lines": count - matched,
        "line_precision": precision,
        "line_recall": recall,
        "line_F1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
    }


def aggregate_ocr_counts(rows: list[dict[str, Any]]) -> dict[str, float | int | None]:
    """Pool sufficient statistics; legacy files cannot supply micro scores."""
    keys = (
        "char_errors", "word_errors", "gt_char_count", "gt_word_count",
        "num_gt_lines", "num_predicted_lines", "num_matched_lines",
    )
    if not rows or any(row.get(key) is None for row in rows for key in keys):
        return {
            "micro_CER": None, "micro_WER": None,
            "line_precision": None, "line_recall": None, "line_F1": None,
        }
    totals = {key: sum(row[key] for row in rows) for key in keys}
    matched = totals["num_matched_lines"]
    precision = matched / totals["num_predicted_lines"] if totals["num_predicted_lines"] else 0.0
    recall = matched / totals["num_gt_lines"] if totals["num_gt_lines"] else 0.0
    return {
        **totals,
        "micro_CER": totals["char_errors"] / max(1, totals["gt_char_count"]),
        "micro_WER": totals["word_errors"] / max(1, totals["gt_word_count"]),
        "line_precision": precision,
        "line_recall": recall,
        "line_F1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
    }

