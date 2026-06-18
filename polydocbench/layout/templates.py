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

    project_path = Path(__file__).resolve().parents[2] / config_path
    if project_path.exists():
        return project_path

    return config_path
