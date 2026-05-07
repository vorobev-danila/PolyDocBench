"""Formula renderer."""

from __future__ import annotations

from .image import ImageRenderer


class FormulaRenderer(ImageRenderer):
    """Render formula image fallbacks using the image pipeline."""

    supported_types = {"formula"}

    def render(self, element: dict) -> None:
        if element.get("type") not in self.supported_types:
            return

        if self.render_image(element):
            return

        self._render_text_fallback(element)

    def _render_text_fallback(self, element: dict) -> None:
        text = self._get_formula_text(element)
        if not text:
            return

        x, y, _, height = self._get_bbox_coords(element)
        font_size = min(10, max(6, height * 0.18))

        try:
            self.canvas.setFont("Helvetica", font_size)
        except Exception:
            return

        self.canvas.drawString(x, y + height / 2, text[:180])

    @staticmethod
    def _get_formula_text(element: dict) -> str:
        metadata = element.get("metadata") or {}
        for key in ("latex", "alt_text", "alttext", "content"):
            value = metadata.get(key) or element.get(key)
            if value:
                return str(value)
        return ""
