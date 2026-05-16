"""FastAPI integration for PolyDocBench."""

from .services import (
    degrade_pdf_document,
    degrade_pdf_with_gt_document,
    evaluate_ordering_from_gt,
    evaluate_quality_from_gt,
    parse_wikipedia_to_file,
    render_document,
)

__all__ = [
    "degrade_pdf_document",
    "degrade_pdf_with_gt_document",
    "evaluate_ordering_from_gt",
    "evaluate_quality_from_gt",
    "parse_wikipedia_to_file",
    "render_document",
]
