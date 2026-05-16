"""Pydantic schemas for PolyDocBench source documents."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


FORMAT_SCHEMA_VERSION = "0.1"


class SourceElement(BaseModel):
    """Flexible source element used before layout normalization."""

    model_config = ConfigDict(extra="allow")

    type: str
    text: str | None = None
    content: str | list["SourceElement"] | None = None
    items: list[dict[str, Any]] | None = None

    @model_validator(mode="after")
    def validate_required_payload(self) -> "SourceElement":
        if self.type in {"paragraph", "hatnote"} and not self._has_text_payload():
            raise ValueError(f"{self.type} elements require 'text' or string 'content'")
        if self.type == "heading" and not self._has_text_payload():
            raise ValueError("heading elements require 'text' or string 'content'")
        if self.type == "list" and self.items is None:
            raise ValueError("list elements require 'items'")
        return self

    def _has_text_payload(self) -> bool:
        return bool(self.text) or isinstance(self.content, str) and bool(self.content.strip())


class SourceDocument(BaseModel):
    """Validated source JSON accepted by the layout engine."""

    model_config = ConfigDict(extra="allow")

    schema_version: str = FORMAT_SCHEMA_VERSION
    title: str = ""
    url: str = ""
    content: list[SourceElement] = Field(default_factory=list)
    elements: list[SourceElement] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_content_or_elements(self) -> "SourceDocument":
        if not self.content and not self.elements:
            raise ValueError("source document requires non-empty 'content' or 'elements'")
        return self

    def source_items(self) -> list[dict[str, Any]]:
        items = self.content or self.elements
        return [item.model_dump(exclude_none=True) for item in items]


def validate_source_document(data: dict[str, Any]) -> SourceDocument:
    return SourceDocument.model_validate(data)
