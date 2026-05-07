"""Shared lightweight types for evaluation modules."""

from __future__ import annotations

from typing import TypedDict


class BBoxDict(TypedDict):
    x: float
    y: float
    width: float
    height: float


class LineDict(TypedDict, total=False):
    id: str
    type: str
    text: str
    bbox: BBoxDict
    confidence: float
    page_number: int
    container_id: str
    column: int

