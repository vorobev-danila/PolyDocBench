"""
Менеджер шрифтов для PolyDocBench
"""

import os
from typing import Dict, Optional
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth


class FontManager:
    """Менеджер шрифтов для PDF рендеринга"""
    
    def __init__(self, config):
        self.config = config
        self.registered_fonts = {}
        self._default_font_family = None
    
    def register_fonts(self) -> bool:
        """Регистрирует все шрифты из конфигурации"""
        try:
            font_settings = self.config.get("render.fonts", {})
            
            for font_name, font_config in font_settings.items():
                if font_config.get("embedded", True) and "path" in font_config:
                    font_path = font_config["path"]
                    
                    if os.path.exists(font_path):
                        try:
                            # Основной шрифт
                            pdfmetrics.registerFont(
                                TTFont(font_config["family"], font_path)
                            )
                            self.registered_fonts[font_name] = font_config["family"]
                            
                            # Bold вариант
                            bold_path = font_config.get("bold_path")
                            if bold_path and os.path.exists(bold_path):
                                bold_family = f"{font_config['family']}-Bold"
                                pdfmetrics.registerFont(
                                    TTFont(bold_family, bold_path)
                                )
                            
                            # Italic вариант
                            italic_path = font_config.get("italic_path")
                            if italic_path and os.path.exists(italic_path):
                                italic_family = f"{font_config['family']}-Oblique"
                                pdfmetrics.registerFont(
                                    TTFont(italic_family, italic_path)
                                )
                            
                        except Exception as e:
                            print(f"   ⚠️ Ошибка регистрации шрифта {font_name}: {e}")
            
            # Устанавливаем шрифт по умолчанию
            default_font_name = self.config.get("render.default_font", "dejavu")
            if default_font_name in self.registered_fonts:
                self._default_font_family = self.registered_fonts[default_font_name]
            else:
                self._default_font_family = "Helvetica"
                print(f"   ⚠️ DejaVu не настроен, используем Helvetica")
            
            return True
            
        except Exception as e:
            print(f"   ⚠️ Ошибка при регистрации шрифтов: {e}")
            self._default_font_family = "Helvetica"
            return False
    
    def get_font_family(self, font_name: Optional[str] = None) -> str:
        """Возвращает семейство шрифтов"""
        if font_name and font_name in self.registered_fonts:
            return self.registered_fonts[font_name]
        return self._default_font_family
    
    def measure_text(self, text: str, font_name: str, font_size: float) -> float:
        """Измеряет ширину текста"""
        try:
            return stringWidth(text, font_name, font_size)
        except:
            return stringWidth(text, "Helvetica", font_size)