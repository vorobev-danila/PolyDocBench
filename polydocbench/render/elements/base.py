"""Base element renderer."""

from __future__ import annotations

from typing import Any

from reportlab.pdfgen import canvas


class BaseElementRenderer:
    def __init__(self, canvas_obj: canvas.Canvas, config, font_manager) -> None:
        self.canvas = canvas_obj
        self.config = config
        self.font_manager = font_manager

    def render(self, element: dict[str, Any]) -> None:
        raise NotImplementedError

    @staticmethod
    def _get_bbox_coords(element: dict[str, Any]) -> tuple[float, float, float, float]:
        bbox = element.get("bbox", {})
        return (
            bbox.get("x", 0),
            bbox.get("y", 0),
            bbox.get("width", 0),
            bbox.get("height", 0),
        )

