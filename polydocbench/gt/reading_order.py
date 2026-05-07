"""Reading-order assignment for layout ground truth."""

from __future__ import annotations

from typing import Iterable

from polydocbench.document import DocumentElement


def assign_reading_order(elements: Iterable[DocumentElement]) -> dict[str, list[str]]:
    """Assign block and line reading-order indices in-place."""

    element_list = list(elements)
    blocks = _sort_elements(element for element in element_list if element.metadata.get("role") == "block")
    lines = _sort_elements(element for element in element_list if element.metadata.get("role") == "line")

    for index, element in enumerate(blocks, start=1):
        element.metadata["reading_order"] = index

    for index, element in enumerate(lines, start=1):
        element.metadata["reading_order"] = index

    return {
        "blocks": [element.id for element in blocks],
        "lines": [element.id for element in lines],
    }


def _sort_elements(elements: Iterable[DocumentElement]) -> list[DocumentElement]:
    return sorted(elements, key=_reading_order_key)


def _reading_order_key(element: DocumentElement) -> tuple[float, float, float, str]:
    if element.bbox is None:
        return (float("inf"), float("inf"), float("inf"), element.id)

    source_index = element.metadata.get("source_index")
    if source_index is not None and element.metadata.get("role") == "block":
        return (element.bbox.page, float(source_index), 0.0, element.id)

    return (element.bbox.page, element.bbox.x, -element.bbox.y, element.id)
