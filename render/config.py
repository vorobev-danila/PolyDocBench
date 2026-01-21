"""
Конфигурация рендеринга для PolyDocBench
"""

import os
import yaml
from typing import Dict, Any



class RenderConfig:
    """Конфигурация рендеринга"""
    
    def __init__(self, config_path: str = None):
        self._default_config = self._get_default_config()
        self._config = {}
        self.load_config(config_path)
    
    def load_config(self, config_path: str = None) -> None:
        """Загружает конфигурацию из файла"""
        try:
            if config_path and os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    loaded_config = yaml.safe_load(f)
                self._config = loaded_config or {}
            else:
                self._config = {}
        except Exception as e:
            print(f"   ⚠️ Ошибка загрузки конфига: {e}")
            self._config = {}
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Возвращает конфигурацию по умолчанию"""
        return {
            "render": {
                "default_font": "dejavu",
                "default_font_size": 10,
                "debug": {
                    "show_bboxes": True,
                    "bbox_alpha": 0.3,
                    "show_ids": False,
                    "bbox_line_width": 0.5,
                    "show_line_debug": False
                },
                "pdf": {
                    "metadata": {
                        "title": "Сгенерированный документ PolyDocBench",
                        "author": "PolyDocBench Generator",
                        "subject": "Синтетический бенчмарк для OCR",
                        "creator": "PolyDocBench v1.0",
                        "producer": "PolyDocBench",
                        "keywords": "OCR, document analysis, ground truth"
                    }
                },
                "fonts": {
                    "dejavu": {
                        "family": "DejaVuSans",
                        "path": "DejaVu Sans/DejaVuSans.ttf",
                        "embedded": True
                    }
                },
                "colors": {
                    "debug": {
                        "text_bbox": "#FF0000",
                        "heading_bbox": "#00FF00", 
                        "image_bbox": "#0000FF",
                        "table_bbox": "#800080",
                        "formula_bbox": "#FFA500"
                    }
                },
                "export": {
                    "pretty_print": True,
                    "indent_size": 2
                }
            }
        }
    
    def get(self, key: str, default: Any = None) -> Any:
        """Получает значение из конфигурации"""
        keys = key.split('.')
        value = self._config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                # Проверяем в дефолтном конфиге
                default_value = self._default_config
                for k2 in keys:
                    if isinstance(default_value, dict) and k2 in default_value:
                        default_value = default_value[k2]
                    else:
                        return default
                return default_value
        
        return value if value is not None else default