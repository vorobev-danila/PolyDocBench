"""Typography settings used by layout placement."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TypographyStyle:
    font_family: str = "DejaVuSans"
    body_size: float = 10
    line_height: float = 1.2
    first_line_indent: float = 20
    paragraph_spacing: float = 10
    heading_sizes: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "TypographyStyle":
        config = config or {}
        return cls(
            font_family=config.get("font_family", cls.font_family),
            body_size=float(config.get("body_size", cls.body_size)),
            line_height=float(config.get("line_height", cls.line_height)),
            first_line_indent=float(config.get("first_line_indent", cls.first_line_indent)),
            paragraph_spacing=float(config.get("paragraph_spacing", cls.paragraph_spacing)),
            heading_sizes={key: float(value) for key, value in config.get("heading_sizes", {}).items()},
        )

    def heading_size(self, element_type: str) -> float:
        level = element_type.replace("heading", "h")
        return self.heading_sizes.get(level, 14)
