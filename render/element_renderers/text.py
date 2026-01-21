"""
Рендерер текстовых элементов (paragraph / text_line)

ВАЖНО:
- renderer НЕ рассчитывает вертикальный layout
- bbox всегда считается ДО рендеринга (layout engine)
- text_line — атом рендеринга
"""

from typing import Dict, Any
from .base import BaseElementRenderer


class TextRenderer(BaseElementRenderer):
    """Рендерер текстовых элементов"""

    def render(self, element: Dict[str, Any]) -> None:
        """
        Точка входа рендеринга текста.

        Поддерживаем два режима:
        - text_line  → line-based rendering (НОВЫЙ)
        - paragraph → legacy paragraph rendering (ВРЕМЕННО)
        """
        element_type = element.get("type")

        if element_type == "text_line":
            self._render_text_line(element)
        else:
            self._render_paragraph_legacy(element)

    # ------------------------------------------------------------------
    # LINE-BASED RENDERING (основной режим)
    # ------------------------------------------------------------------

    def _render_text_line(self, element: Dict[str, Any]) -> None:
        """
        Рендерит одну строку текста.
        bbox.y — НИЖНЯЯ граница строки
        """
        x, y, width, height = self._get_bbox_coords(element)

        text = element.get("content", "")
        if not text.strip():
            return

        dimensions = element.get("dimensions", {})

        # --- font size ---
        raw_font_size = dimensions.get(
            "font_size",
            self.config.get("render.default_font_size", 10)
        )
        try:
            font_size = float(raw_font_size)
        except (TypeError, ValueError):
            font_size = 10.0

        # --- font family ---
        font_name = dimensions.get(
            "font_name",
            self.font_manager.get_font_family()
        )

        indent = float(dimensions.get("indent", 0.0))

        # --- font setup ---
        try:
            self.canvas.setFont(font_name, font_size)
        except Exception:
            self.canvas.setFont("Helvetica", font_size)

        # --- baseline ---
        # ascent либо передаётся layout'ом, либо fallback
        ascent = dimensions.get("ascent", font_size * 0.2)

        baseline_y = y + ascent

        self.canvas.drawString(
            x + indent,
            baseline_y,
            text
        )


    # ------------------------------------------------------------------
    # LEGACY PARAGRAPH RENDERING (поддержка старого pipeline)
    # ------------------------------------------------------------------

    def _render_paragraph_legacy(self, element: Dict[str, Any]) -> None:
        """
        Старый paragraph-based рендеринг.

        ОСТАВЛЕН ВРЕМЕННО:
        - для совместимости
        - для тестов
        - будет удалён после полной миграции на text_line
        """
        x, y, width, height = self._get_bbox_coords(element)

        dimensions = element.get("dimensions")
        if not dimensions or "lines" not in dimensions:
            return

        lines = dimensions.get("lines", [])

        font_size = dimensions.get(
            "font_size",
            self.config.get("render.default_font_size", 10)
        )

        font_name = dimensions.get(
            "font_name",
            self.font_manager.get_font_family()
        )

        line_height = dimensions.get(
            "line_height",
            font_size * 1.2
        )

        try:
            self.canvas.setFont(font_name, font_size)
        except Exception:
            self.canvas.setFont("Helvetica", font_size)

        current_y = y + height

        for i, line_text in enumerate(lines):
            if not line_text.strip():
                continue

            line_y = current_y - (i + 1) * line_height

            # legacy first-line indent
            indent = 20 if i == 0 else 0

            self.canvas.drawString(
                x,
                line_y,
                line_text
            )
