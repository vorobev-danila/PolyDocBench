"""FastAPI integration for PolyDocBench."""

from .services import (
    evaluate_ordering_from_gt,
    evaluate_quality_from_gt,
    parse_wikipedia_to_file,
    render_document,
)

__all__ = [
    "evaluate_ordering_from_gt",
    "evaluate_quality_from_gt",
    "parse_wikipedia_to_file",
    "render_document",
]
