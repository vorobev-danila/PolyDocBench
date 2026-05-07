"""High-level OCR quality evaluation."""

from __future__ import annotations

from .matching import match_lines
from .text_metrics import cer, wer
from .types import LineDict


def evaluate_ocr_quality(
    gt_lines: list[LineDict],
    predicted_lines: list[LineDict],
    iou_threshold: float = 0.3,
) -> dict[str, float]:
    """Compute mean CER, WER and IoU over GT lines."""

    matches = match_lines(gt_lines, predicted_lines, iou_threshold=iou_threshold)
    if not matches:
        return {"CER": 0.0, "WER": 0.0, "IoU": 0.0, "matched_ratio": 0.0}

    total_cer = 0.0
    total_wer = 0.0
    total_iou = 0.0
    matched = 0

    for match in matches:
        prediction_text = match.prediction["text"] if match.prediction else ""
        total_cer += cer(match.gt["text"], prediction_text)
        total_wer += wer(match.gt["text"], prediction_text)
        total_iou += match.iou
        matched += int(match.prediction is not None)

    count = len(matches)
    return {
        "CER": total_cer / count,
        "WER": total_wer / count,
        "IoU": total_iou / count,
        "matched_ratio": matched / count,
    }

