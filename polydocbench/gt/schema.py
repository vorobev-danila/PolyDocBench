"""Pydantic schemas for PolyDocBench ground-truth JSON."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from polydocbench.document.schema import FORMAT_SCHEMA_VERSION


class GTBBox(BaseModel):
    model_config = ConfigDict(extra="allow")

    x: float
    y: float
    width: float
    height: float
    page: int = 1


class GTElement(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    type: str
    content: Any = ""
    bbox: GTBBox | None = None
    dimensions: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GTContainer(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    type: str = "single_column"
    bbox: GTBBox | None = None
    element_count: int = 0
    available_height: float | None = None
    elements: list[GTElement] = Field(default_factory=list)


class GTPage(BaseModel):
    model_config = ConfigDict(extra="allow")

    page_number: int = 1
    width: float
    height: float
    containers: list[GTContainer] = Field(default_factory=list)


class GTReadingOrder(BaseModel):
    model_config = ConfigDict(extra="allow")

    blocks: list[str] = Field(default_factory=list)
    lines: list[str] = Field(default_factory=list)


class GTDocument(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str = FORMAT_SCHEMA_VERSION
    metadata: dict[str, Any] = Field(default_factory=dict)
    reading_order: GTReadingOrder = Field(default_factory=GTReadingOrder)
    pages: list[GTPage] = Field(default_factory=list)
    elements: list[GTElement] = Field(default_factory=list)


def validate_gt_document(data: dict[str, Any]) -> GTDocument:
    return GTDocument.model_validate(data)
