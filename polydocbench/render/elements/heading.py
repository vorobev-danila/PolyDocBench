"""Heading renderer."""

from __future__ import annotations

from typing import Any

from .base import BaseElementRenderer


class HeadingRenderer(BaseElementRenderer):
    def render(self, element: dict[str, Any]) -> None:
        if not element.get("type", "").startswith("heading"):
            return

        dimensions = element.get("dimensions") or {}
        for line in dimensions.get("placed_lines", []):
            bbox = line.get("bbox")
            if not bbox:
                continue

            text = line.get("text", "")
            if not text.strip():
                continue

            font_size = line.get("font_size", 14)
            font_name = line.get("font_family", "Helvetica-Bold")
            ascent = line.get("ascent", font_size * 0.8)

            try:
                self.canvas.setFont(font_name, font_size)
            except Exception:
                self.canvas.setFont("Helvetica-Bold", font_size)

            self.canvas.drawString(bbox.get("x", 0), bbox.get("y", 0) + ascent, text)

