"""Layout template loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from polydocbench.layout.templates import DEFAULT_TEMPLATE_PATH, resolve_template_path


class TemplateManager:
    def __init__(self, config_path: str | Path = DEFAULT_TEMPLATE_PATH) -> None:
        self.config_path = resolve_template_path(config_path)
        self.template_config = self.load_config()

    def load_config(self) -> dict[str, Any]:
        with self.config_path.open("r", encoding="utf-8") as file:
            return yaml.safe_load(file) or {}

    def get_template(self, template_name: str = "simple_article") -> dict[str, Any]:
        templates = self.template_config.get("templates", {})
        if template_name in templates:
            print(f"   Selected template: {template_name}")
            return templates[template_name]

        print(f"   Template '{template_name}' was not found, using 'simple_article'")
        return templates.get("simple_article", {})

    def get_base_settings(self) -> dict[str, Any]:
        return self.template_config.get("base_settings", {})
