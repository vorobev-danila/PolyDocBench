"""Evaluation helpers for OCR quality and reading order experiments."""

from .geometry import bbox_iou, to_xyxy
from .gt import extract_gt_lines, load_gt
from .matching import LineMatch, match_lines
from .ocr import extract_tesseract_lines
from .ordering import evaluate_ordering
from .quality import evaluate_ocr_quality
from .text_metrics import cer, normalize_text, wer
from .dashboard import write_ocr_dashboard
from .dotsocr import extract_dotsocr_blocks, parse_dotsocr_blocks_response
from .block_matching import BlockMatch, extract_visible_gt_blocks, match_semantic_blocks
from .ordered_text import evaluate_semantic_ordering, join_ordered_text, token_bag_scores
from .ordering_dashboard import write_ordering_dashboard

__all__ = [
    "LineMatch",
    "bbox_iou",
    "cer",
    "evaluate_ocr_quality",
    "evaluate_ordering",
    "extract_gt_lines",
    "extract_tesseract_lines",
    "extract_dotsocr_blocks",
    "extract_visible_gt_blocks",
    "load_gt",
    "match_lines",
    "normalize_text",
    "to_xyxy",
    "wer",
    "write_ocr_dashboard",
    "write_ordering_dashboard",
    "parse_dotsocr_blocks_response",
    "BlockMatch",
    "match_semantic_blocks",
    "evaluate_semantic_ordering",
    "join_ordered_text",
    "token_bag_scores",
]
