"""Text line renderer."""

from __future__ import annotations

from typing import Any

from .base import BaseElementRenderer


class TextRenderer(BaseElementRenderer):
    def render(self, element: dict[str, Any]) -> None:
        if element.get("type") != "text_line":
            return
        self._render_text_line(element)

    def _render_text_line(self, element: dict[str, Any]) -> None:
        x, y, _, _ = self._get_bbox_coords(element)
        text = element.get("content", "")
        if not text.strip():
            return

        dimensions = element.get("dimensions") or {}
        try:
            font_size = float(dimensions.get("font_size", self.config.get("render.default_font_size", 10)))
        except (TypeError, ValueError):
            font_size = 10.0

        font_name = dimensions.get("font_name", self.font_manager.get_font_family())
        indent = float(dimensions.get("indent", 0.0))
        ascent = dimensions.get("ascent", font_size * 0.2)

        try:
            self.canvas.setFont(font_name, font_size)
        except Exception:
            self.canvas.setFont("Helvetica", font_size)

        self.canvas.drawString(x + indent, y + ascent, text)

