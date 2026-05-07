"""Canonical layout result used by rendering and GT export."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from polydocbench.document import DocumentElement, Page
from polydocbench.gt.reading_order import assign_reading_order


@dataclass
class LayoutResult:
    pages: list[Page] = field(default_factory=list)
    elements: list[DocumentElement] = field(default_factory=list)
    ground_truth: dict[str, Any] = field(default_factory=dict)

    def add_page(self, page: Page) -> None:
        self.pages.append(page)

    def add_element(self, element: DocumentElement) -> None:
        self.elements.append(element)

    def prepare_ground_truth(self, generator_name: str = "PolyDocBench") -> None:
        reading_order = assign_reading_order(self.elements)
        pages_gt = []
        for page in self.pages:
            page_info = {
                "page_number": page.number,
                "width": page.width,
                "height": page.height,
                "containers": [],
            }

            for container in page.containers:
                page_info["containers"].append(
                    {
                        "id": container.id,
                        "type": container.type,
                        "bbox": {
                            "x": container.x,
                            "y": container.y,
                            "width": container.width,
                            "height": container.height,
                            "page": page.number,
                        },
                        "element_count": len(container.elements),
                        "available_height": container.available_height,
                        "elements": [self._element_to_dict(element) for element in container.elements],
                    }
                )

            pages_gt.append(page_info)

        self.ground_truth = {
            "metadata": {
                "generator": generator_name,
                "version": "1.0",
                "page_count": len(self.pages),
                "element_count": len(self.elements),
                "timestamp": datetime.now().isoformat(),
            },
            "reading_order": reading_order,
            "pages": pages_gt,
            "elements": [self._element_to_dict(element) for element in self.elements],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "pages": [
                {
                    "number": page.number,
                    "width": page.width,
                    "height": page.height,
                    "containers": [
                        {
                            "id": container.id,
                            "type": container.type,
                            "x": container.x,
                            "y": container.y,
                            "width": container.width,
                            "height": container.height,
                            "elements": [self._element_to_dict(element) for element in container.elements],
                        }
                        for container in page.containers
                    ],
                }
                for page in self.pages
            ],
            "elements": [self._element_to_dict(element) for element in self.elements],
        }

    @staticmethod
    def _element_to_dict(element: DocumentElement) -> dict[str, Any]:
        return {
            "id": element.id,
            "type": element.type,
            "content": element.content,
            "bbox": element.bbox.as_dict() if element.bbox else None,
            "dimensions": element.dimensions,
            "metadata": element.metadata,
        }
