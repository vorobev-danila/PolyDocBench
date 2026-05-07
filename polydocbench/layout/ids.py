"""Stable layout element identifiers."""

from __future__ import annotations

import re


class ElementIdGenerator:
    """Generate deterministic ids for block and line elements within a layout run."""

    def block_id(self, element_type: str, source_index: int) -> str:
        return f"{_slug(element_type)}_{source_index:04d}"

    def line_id(self, block_id: str, line_index: int) -> str:
        return f"{block_id}_line_{line_index:03d}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "element"
