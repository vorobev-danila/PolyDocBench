"""Element-level layout specifications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ElementLayoutSpec:
    element_type: str
    width: float = 100
    height: float = 100

    @classmethod
    def from_element(cls, element_data: dict[str, Any]) -> "ElementLayoutSpec":
        return cls(
            element_type=element_data.get("type", "paragraph"),
            width=_positive_float(element_data.get("width"), default=100),
            height=_positive_float(element_data.get("height"), default=100),
        )

    def width_for_container(self, container_width: float) -> float:
        return min(self.width, container_width)


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default

    return parsed if parsed > 0 else default
