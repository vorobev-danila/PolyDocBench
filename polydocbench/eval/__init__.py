"""Evaluation helpers for OCR quality and reading order experiments."""

from .geometry import bbox_iou, to_xyxy
from .gt import extract_gt_lines, load_gt
from .matching import LineMatch, match_lines
from .ocr import extract_tesseract_lines
from .ordering import evaluate_ordering
from .text_metrics import cer, normalize_text, wer

__all__ = [
    "LineMatch",
    "bbox_iou",
    "cer",
    "evaluate_ordering",
    "extract_gt_lines",
    "extract_tesseract_lines",
    "load_gt",
    "match_lines",
    "normalize_text",
    "to_xyxy",
    "wer",
]

