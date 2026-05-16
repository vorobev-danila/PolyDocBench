"""Canonical document model used between sources, layout, render, and GT."""

from .model import BBox, Container, Document, DocumentElement, Page
from .schema import FORMAT_SCHEMA_VERSION, SourceDocument, SourceElement, validate_source_document

__all__ = [
    "BBox",
    "Container",
    "Document",
    "DocumentElement",
    "FORMAT_SCHEMA_VERSION",
    "Page",
    "SourceDocument",
    "SourceElement",
    "validate_source_document",
]
