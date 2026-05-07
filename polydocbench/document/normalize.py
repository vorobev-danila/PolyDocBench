"""Normalization helpers for source documents."""

from __future__ import annotations

from typing import Any


def flatten_source_content(content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten nested source sections into a linear stream for layout input."""

    flattened: list[dict[str, Any]] = []

    for item in content:
        item_type = item.get("type")
        if item_type == "heading":
            level = item.get("level", 1)
            flattened.append(
                {
                    "type": f"heading{level}",
                    "content": item.get("text", ""),
                    "metadata": {"level": level, "source_id": item.get("id", "")},
                }
            )
            flattened.extend(flatten_source_content(item.get("content", [])))
        elif item_type == "paragraph":
            flattened.append({"type": "paragraph", "content": item.get("text", ""), "metadata": {}})
        elif item_type == "hatnote":
            flattened.append(
                {
                    "type": "paragraph",
                    "content": item.get("text", ""),
                    "metadata": {"source_type": "hatnote"},
                }
            )
        elif item_type == "list":
            flattened.extend(_flatten_list(item))
        else:
            flattened.append(item)

    return flattened


def _flatten_list(item: dict[str, Any]) -> list[dict[str, Any]]:
    list_type = item.get("list_type", "unordered")
    flattened: list[dict[str, Any]] = []

    for index, list_item in enumerate(item.get("items", []), start=1):
        text = str(list_item.get("text", "")).strip()
        if not text:
            continue

        marker = f"{index}." if list_type == "ordered" else "-"
        flattened.append(
            {
                "type": "paragraph",
                "content": f"{marker} {text}",
                "metadata": {
                    "source_type": "list",
                    "list_type": list_type,
                    "list_index": index,
                },
            }
        )

    return flattened
