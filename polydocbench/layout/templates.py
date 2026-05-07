"""Layout template utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_TEMPLATE_PATH = Path("configs/layout_templates.yaml")


def load_layout_templates(path: str | Path = DEFAULT_TEMPLATE_PATH) -> dict[str, Any]:
    config_path = resolve_template_path(path)
    with config_path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def list_template_names(path: str | Path = DEFAULT_TEMPLATE_PATH) -> list[str]:
    config = load_layout_templates(path)
    return sorted(config.get("templates", {}).keys())


def resolve_template_path(path: str | Path = DEFAULT_TEMPLATE_PATH) -> Path:
    config_path = Path(path)
    if config_path.exists():
        return config_path

    legacy_path = Path("render/configs/layout_templates.yaml")
    normalized_path = str(path).replace("\\", "/")
    default_path = str(DEFAULT_TEMPLATE_PATH).replace("\\", "/")
    legacy_path_text = str(legacy_path).replace("\\", "/")

    if normalized_path == default_path and legacy_path.exists():
        return legacy_path

    if normalized_path == legacy_path_text and DEFAULT_TEMPLATE_PATH.exists():
        return DEFAULT_TEMPLATE_PATH

    return config_path
