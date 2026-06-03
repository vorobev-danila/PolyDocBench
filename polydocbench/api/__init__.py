"""FastAPI integration for PolyDocBench."""

from .services import (
    evaluate_ordering_from_gt,
    evaluate_quality_from_gt,
    evaluate_structure_from_gt,
    noise_pdf_document,
    noise_pdf_with_gt_document,
    parse_wikipedia_to_file,
    render_document,
)

__all__ = [
    "evaluate_ordering_from_gt",
    "evaluate_quality_from_gt",
    "evaluate_structure_from_gt",
    "noise_pdf_document",
    "noise_pdf_with_gt_document",
    "parse_wikipedia_to_file",
    "render_document",
]
