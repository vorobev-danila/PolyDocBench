"""Text measurement utilities for layout."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont


class TextMetrics:
    """Measure text and expose basic font metrics."""

    def __init__(self, font_path: str | Path | None = None, font_name: str = "DejaVuSans") -> None:
        self.font_name = font_name
        if font_path and font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font_name, str(font_path)))

    def get_font_metrics(self, font_size: float) -> dict[str, float]:
        try:
            font = pdfmetrics.getFont(self.font_name)
            face: Any = font.face
            return {
                "ascent": (face.ascent / face.unitsPerEm) * font_size,
                "descent": abs(face.descent / face.unitsPerEm) * font_size,
                "line_height": font_size * 1.2,
            }
        except Exception:
            return {
                "ascent": font_size * 0.8,
                "descent": font_size * 0.2,
                "line_height": font_size * 1.2,
            }

    def measure_text_width(self, text: str, font_size: float) -> float:
        return stringWidth(text, self.font_name, font_size)

    def can_fit_in_width(self, text: str, max_width: float, font_size: float) -> bool:
        return self.measure_text_width(text, font_size) <= max_width
