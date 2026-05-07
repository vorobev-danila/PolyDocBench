"""Ground-truth schema types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from polydocbench.document import BBox


@dataclass
class GTElement:
    id: str
    type: str
    bbox: BBox
    text: str = ""
    reading_order: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GTPage:
    page_number: int
    width: float
    height: float
    elements: list[GTElement] = field(default_factory=list)

