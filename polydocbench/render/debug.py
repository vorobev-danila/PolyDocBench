"""Debug rendering helpers."""

from __future__ import annotations

from typing import Any

from reportlab.pdfgen import canvas


class DebugRenderer:
    def __init__(self, canvas_obj: canvas.Canvas, config) -> None:
        self.canvas = canvas_obj
        self.config = config

    def render_bbox(self, element: dict[str, Any], x: float, y: float, width: float, height: float) -> None:
        element_type = element.get("type", "")
        if element_type == "paragraph":
            return

        debug_config = self.config.get("render.debug", {})
        if not debug_config.get("show_bboxes", True):
            return

        color_hex = self._color_for_type(element_type)
        r, g, b = self._hex_to_rgb(color_hex)
        self.canvas.setStrokeColorRGB(r, g, b, alpha=debug_config.get("bbox_alpha", 0.3))
        self.canvas.setLineWidth(debug_config.get("bbox_line_width", 0.8))
        self.canvas.rect(x, y, width, height, stroke=1, fill=0)

        if debug_config.get("show_ids", False):
            self.canvas.setFont("Helvetica", 6)
            self.canvas.setFillColorRGB(r, g, b, alpha=0.8)
            self.canvas.drawString(x + 2, y + height - 8, f"ID: {element.get('id', 'unknown')}")

    def render_line_debug(
        self,
        element: dict[str, Any],
        lines: list,
        x: float,
        y: float,
        line_height: float,
        font_size: float,
    ) -> None:
        debug_config = self.config.get("render.debug", {})
        if not debug_config.get("show_line_debug", False):
            return

        width = element.get("bbox", {}).get("width", 0)
        self.canvas.setStrokeColorRGB(0, 0, 1, alpha=0.2)
        self.canvas.setLineWidth(0.3)
        for index in range(len(lines) + 1):
            line_y = y + (line_height * index)
            self.canvas.line(x, line_y, x + width, line_y)
            if index < len(lines):
                self.canvas.setFont("Helvetica", 6)
                self.canvas.setFillColorRGB(0, 0, 1, alpha=0.5)
                self.canvas.drawString(x + 5, line_y - 10, f"line {index + 1}")

    def _color_for_type(self, element_type: str) -> str:
        colors = self.config.get("render.colors.debug", {})
        if element_type in {"text", "paragraph"}:
            return colors.get("text_bbox", "#FF0000")
        if element_type.startswith("heading"):
            return colors.get("heading_bbox", "#00FF00")
        if element_type == "image":
            return colors.get("image_bbox", "#0000FF")
        if element_type == "text_line":
            return colors.get("table_bbox", "#800080")
        if element_type.startswith("column") or element_type == "single_column":
            return colors.get("container", "#FFA500")
        return "#888888"

    @staticmethod
    def _hex_to_rgb(color_hex: str) -> tuple[float, float, float]:
        if not color_hex.startswith("#") or len(color_hex) != 7:
            return 1.0, 0.0, 0.0
        return (
            int(color_hex[1:3], 16) / 255.0,
            int(color_hex[3:5], 16) / 255.0,
            int(color_hex[5:7], 16) / 255.0,
        )

