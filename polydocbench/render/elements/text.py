"""Text line renderer."""

from __future__ import annotations

from typing import Any

from .base import BaseElementRenderer
from polydocbench.document.fonts import draw_text, measure_text


class TextRenderer(BaseElementRenderer):
    def render(self, element: dict[str, Any]) -> None:
        if element.get("type") != "text_line":
            return
        self._render_text_line(element)

    def _render_text_line(self, element: dict[str, Any]) -> None:
        x, y, bbox_width, _ = self._get_bbox_coords(element)
        text = element.get("content", "")
        if not text.strip():
            return

        dimensions = element.get("dimensions") or {}
        try:
            font_size = float(dimensions.get("font_size", self.config.get("render.default_font_size", 10)))
        except (TypeError, ValueError):
            font_size = 10.0

        font_name = dimensions.get("font_name") or dimensions.get("font_family") or self.font_manager.get_font_family()
        indent = float(dimensions.get("indent", 0.0))
        ascent = dimensions.get("ascent", font_size * 0.2)

        try:
            self.canvas.setFont(font_name, font_size)
        except Exception:
            font_name = "Helvetica"
            self.canvas.setFont(font_name, font_size)

        if dimensions.get("justify"):
            self._draw_justified_text(
                text=text,
                x=x + indent,
                y=y + ascent,
                font_name=font_name,
                font_size=font_size,
                target_width=float(dimensions.get("target_width") or bbox_width),
                text_width=float(dimensions.get("text_width") or 0.0),
            )
            return

        draw_text(self.canvas, text, x + indent, y + ascent, font_name, font_size)

    def _draw_justified_text(
        self,
        text: str,
        x: float,
        y: float,
        font_name: str,
        font_size: float,
        target_width: float,
        text_width: float,
    ) -> None:
        words = text.split()
        if len(words) < 2:
            draw_text(self.canvas, text, x, y, font_name, font_size)
            return

        measured_text_width = text_width or measure_text(text, font_name, font_size)
        extra_width = max(0.0, target_width - measured_text_width)
        extra_gap_width = extra_width / (len(words) - 1)
        space_width = measure_text(" ", font_name, font_size)

        cursor_x = x
        for index, word in enumerate(words):
            draw_text(self.canvas, word, cursor_x, y, font_name, font_size)
            cursor_x += measure_text(word, font_name, font_size)
            if index < len(words) - 1:
                cursor_x += space_width + extra_gap_width
