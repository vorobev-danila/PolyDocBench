"""Shared caption layout for tables and figures."""

from __future__ import annotations

import math

from polydocbench.document import BBox, DocumentElement


def caption_lines(context, text: str, width: float, font_size: float):
    if not all(math.isfinite(value) and value > 0 for value in (width, font_size)):
        raise ValueError("Text allocation width and font size must be finite and positive")
    lines = context.bbox_calculator.split_into_lines(
        text, width, font_size, first_line_indent=0, hyphenate=False,
        add_hyphen_on_force_split=False,
    )
    if any(line.width > width + 0.01 for line in lines):
        raise ValueError("Text cannot fit its allocated width; increase column width or reduce font size")
    return lines


def make_caption(context, text: str, lines, top: float, x: float, width: float,
                 element_id: str, owner_id: str, source_index: int) -> list[DocumentElement]:
    if not lines:
        return []
    height = sum(line.height for line in lines)
    container_id = context.current_container.id
    metadata = {"source_index": source_index, "container_id": container_id, "caption_for": owner_id}
    elements = [DocumentElement(
        id=element_id, type="caption", content=text,
        bbox=BBox(x, top - height, width, height, context.current_page_number),
        metadata={**metadata, "role": "block"},
    )]
    y = top
    for index, line in enumerate(lines, 1):
        y -= line.height
        elements.append(DocumentElement(
            id=f"{element_id}_line_{index:04d}", type="text_line", content=line.text,
            bbox=BBox(x, y, line.width, line.height, context.current_page_number),
            dimensions={"font_family": line.font_family, "font_size": line.font_size,
                        "ascent": line.ascent, "descent": line.descent},
            metadata={**metadata, "role": "line", "parent_id": element_id, "line_index": index},
        ))
    return elements
