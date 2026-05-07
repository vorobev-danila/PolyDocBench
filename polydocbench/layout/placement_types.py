"""Shared placement result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from polydocbench.document import BBox


class PlacementStatus(Enum):
    PLACED = "placed"
    NEED_NEW_COLUMN = "need_new_column"
    NEED_NEW_PAGE = "need_new_page"
    TOO_LARGE = "too_large"


@dataclass
class PlacedLine:
    """A placed text line or atomic graphic element."""

    text: str
    bbox: BBox
    font_size: float
    font_family: str
    ascent: float
    descent: float
    is_first_line: bool
    container_id: str
    page_number: int
    line_index: int
    paragraph_id: Optional[str] = None
    element_type: Optional[str] = None


@dataclass
class PlacementResult:
    success: bool
    placed_lines: list[PlacedLine] = field(default_factory=list)
    remaining_text: Optional[str] = None
    paragraph_bbox: Optional[BBox] = None
    total_height: float = 0.0
    column_index: Optional[int] = None
    message: str = ""

    @property
    def line_count(self) -> int:
        return len(self.placed_lines)

    def add_line(self, line: PlacedLine) -> None:
        self.placed_lines.append(line)
        self.total_height += line.bbox.height
