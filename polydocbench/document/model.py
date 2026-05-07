"""Canonical data structures shared by layout, rendering, and GT export."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BBox:
    x: float
    y: float
    width: float
    height: float
    page: int = 1

    def as_dict(self) -> dict[str, float | int]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "page": self.page,
        }


@dataclass
class DocumentElement:
    id: str
    type: str
    content: Any = ""
    bbox: BBox | None = None
    dimensions: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    children: list["DocumentElement"] = field(default_factory=list)


@dataclass
class Container:
    id: str
    x: float
    y: float
    width: float
    height: float
    type: str = "single_column"
    elements: list[DocumentElement] = field(default_factory=list)
    page: int = 1
    cursor_y: float = field(init=False)

    def __post_init__(self) -> None:
        self.cursor_y = self.y + self.height
        self.elements = [] if self.elements is None else self.elements

    @property
    def available_height(self) -> float:
        return max(0.0, self.cursor_y - self.y)

    def can_fit(self, element_height: float) -> bool:
        return element_height <= self.available_height

    def place(self, element_height: float) -> BBox | None:
        if not self.can_fit(element_height):
            return None

        bbox = BBox(
            x=self.x,
            y=self.cursor_y - element_height,
            width=self.width,
            height=element_height,
            page=self.page,
        )
        self.cursor_y -= element_height
        return bbox

    def add_element(self, element: DocumentElement) -> None:
        self.elements.append(element)

    def reset(self) -> None:
        self.cursor_y = self.y + self.height
        self.elements.clear()


@dataclass
class Page:
    number: int
    width: float = 595.0
    height: float = 842.0
    containers: list[Container] = field(default_factory=list)
    elements: list[DocumentElement] = field(default_factory=list)

    def add_container(self, container: Container) -> None:
        self.containers.append(container)

    def create_single_column(self, margins: dict[str, float] | None = None) -> Container:
        if margins is None:
            margins = {"top": 50, "bottom": 50, "left": 50, "right": 50}

        container = Container(
            id="main_content",
            x=margins["left"],
            y=margins["bottom"],
            width=self.width - margins["left"] - margins["right"],
            height=self.height - margins["top"] - margins["bottom"],
            type="single_column",
            page=self.number,
        )
        self.add_container(container)
        return container

    def create_multi_column(
        self,
        num_columns: int = 2,
        gutter: float = 20.0,
        margins: dict[str, float] | None = None,
    ) -> list[Container]:
        if margins is None:
            margins = {"top": 50, "bottom": 50, "left": 50, "right": 50}

        content_width = self.width - margins["left"] - margins["right"]
        content_height = self.height - margins["top"] - margins["bottom"]
        column_width = (content_width - gutter * (num_columns - 1)) / num_columns

        containers = []
        for index in range(num_columns):
            column_x = margins["left"] + index * (column_width + gutter)
            container = Container(
                id=f"column_{index + 1}",
                x=column_x,
                y=margins["bottom"],
                width=column_width,
                height=content_height,
                type=f"column_{num_columns}",
                page=self.number,
            )
            containers.append(container)
            self.add_container(container)

        return containers


@dataclass
class Document:
    title: str = ""
    source_url: str = ""
    pages: list[Page] = field(default_factory=list)
    elements: list[DocumentElement] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
