"""Rendering configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class RenderConfig:
    """Nested render configuration with defaults and dotted-key access."""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self._default_config = self._get_default_config()
        self._config: dict[str, Any] = {}
        self.load_config(config_path)

    def load_config(self, config_path: str | Path | None = None) -> None:
        if config_path and Path(config_path).exists():
            with Path(config_path).open("r", encoding="utf-8") as file:
                self._config = yaml.safe_load(file) or {}
        else:
            self._config = {}

    def get(self, key: str, default: Any = None) -> Any:
        value = self._lookup(self._config, key, missing=None)
        if value is not None:
            return value
        return self._lookup(self._default_config, key, missing=default)

    @staticmethod
    def _lookup(config: dict[str, Any], key: str, missing: Any = None) -> Any:
        value: Any = config
        for part in key.split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return missing
        return value

    @staticmethod
    def _get_default_config() -> dict[str, Any]:
        return {
            "render": {
                "default_font": "dejavu",
                "default_font_size": 10,
                "debug": {
                    "show_bboxes": True,
                    "bbox_alpha": 0.3,
                    "show_ids": False,
                    "bbox_line_width": 0.5,
                    "show_line_debug": False,
                },
                "pdf": {
                    "metadata": {
                        "title": "Generated PolyDocBench document",
                        "author": "PolyDocBench Generator",
                        "subject": "Synthetic OCR benchmark",
                        "creator": "PolyDocBench",
                        "producer": "PolyDocBench",
                        "keywords": "OCR, document analysis, ground truth",
                    }
                },
                "fonts": {
                    "dejavu": {
                        "family": "DejaVuSans",
                        "path": "DejaVu Sans/DejaVuSans.ttf",
                        "embedded": True,
                    }
                },
                "colors": {
                    "debug": {
                        "text_bbox": "#FF0000",
                        "heading_bbox": "#00FF00",
                        "image_bbox": "#0000FF",
                        "table_bbox": "#800080",
                        "formula_bbox": "#FFA500",
                        "container": "#FFA500",
                    }
                },
                "export": {
                    "pretty_print": True,
                    "indent_size": 2,
                },
            }
        }

