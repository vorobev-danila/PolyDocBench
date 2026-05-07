"""Font registration and measurement helpers."""

from __future__ import annotations

from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont


class FontManager:
    def __init__(self, config) -> None:
        self.config = config
        self.registered_fonts: dict[str, str] = {}
        self._default_font_family = "Helvetica"

    def register_fonts(self) -> bool:
        font_settings = self.config.get("render.fonts", {})

        for font_name, font_config in font_settings.items():
            if not font_config.get("embedded", True):
                continue

            font_path = Path(font_config.get("path", ""))
            family = font_config.get("family", font_name)
            if not font_path.exists():
                continue

            try:
                if family not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(family, str(font_path)))
                self.registered_fonts[font_name] = family
                self._register_variant(font_config, "bold_path", f"{family}-Bold")
                self._register_variant(font_config, "italic_path", f"{family}-Oblique")
            except Exception:
                continue

        default_font_name = self.config.get("render.default_font", "dejavu")
        self._default_font_family = self.registered_fonts.get(default_font_name, "Helvetica")
        return bool(self.registered_fonts)

    def get_font_family(self, font_name: str | None = None) -> str:
        if font_name and font_name in self.registered_fonts:
            return self.registered_fonts[font_name]
        return self._default_font_family

    def measure_text(self, text: str, font_name: str, font_size: float) -> float:
        try:
            return stringWidth(text, font_name, font_size)
        except Exception:
            return stringWidth(text, "Helvetica", font_size)

    @staticmethod
    def _register_variant(font_config: dict, path_key: str, family: str) -> None:
        variant_path = Path(font_config.get(path_key, ""))
        if variant_path.exists() and family not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(family, str(variant_path)))

