from typing import Dict, Any
from reportlab.pdfbase.pdfmetrics import stringWidth
from .base import BaseElementRenderer


class HeadingRenderer(BaseElementRenderer):
    """Рендерер заголовков уровней 1..6"""

    def render(self, element: Dict[str, Any]) -> None:
        """
        Рендерит заголовок в PDF.
        Использует:
        - bbox.x, bbox.y как точку начала
        - dimensions.font_size / font_name
        - content или lines (если есть)
        """
        # --- координаты bbox ---
        x, y, width, height = self._get_bbox_coords(element)

        # --- параметры шрифта ---
        dimensions = element.get("dimensions", {})
        font_size = float(dimensions.get("font_size", 14))
        font_name = dimensions.get("font_name", self.font_manager.get_font_family())

        # fallback для шрифта
        try:
            self.canvas.setFont(font_name, font_size)
        except Exception:
            font_name = self.font_manager.get_font_family()
            try:
                self.canvas.setFont(font_name, font_size)
            except Exception:
                self.canvas.setFont("Helvetica", font_size)
                font_name = "Helvetica"

        # --- текст для рендеринга ---
        lines = dimensions.get("lines", [])
        if not lines:
            content = element.get("content", "")
            lines = [content]

        # --- line_height ---
        line_height = dimensions.get("line_height", font_size * 1.2)

        # --- рендерим строки ---
        for i, line_text in enumerate(lines):
            if not line_text.strip():
                continue

            # координата baseline (y — нижняя граница bbox)
            baseline_y = y + (height - font_size) - i * line_height

            # горизонтальное позиционирование: слева bbox.x
            line_x = x

            self.canvas.drawString(line_x, baseline_y, str(line_text))

