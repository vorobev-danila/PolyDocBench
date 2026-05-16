"""Load and normalize source content for layout."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from polydocbench.document.normalize import flatten_source_content
from polydocbench.document.schema import FORMAT_SCHEMA_VERSION, validate_source_document


class ContentLoader:
    """Load parsed source JSON and convert it to layout element dictionaries."""

    @staticmethod
    def load_json(json_path: str | Path) -> list[dict[str, Any]]:
        print(f"   Reading file: {json_path}")

        with Path(json_path).open("r", encoding="utf-8") as file:
            data = json.load(file)

        document = validate_source_document(data)
        source_items = document.source_items()

        if document.content:
            elements = flatten_source_content(source_items)
        else:
            elements = source_items

        print(f"   Loaded elements: {len(elements)}")
        print(f"   Element types: {ContentLoader.count_element_types(elements)}")
        return elements

    @staticmethod
    def count_element_types(elements: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for element in elements:
            element_type = element.get("type", "unknown")
            counts[element_type] = counts.get(element_type, 0) + 1
        return counts

    @staticmethod
    def save_processed_content(elements: list[dict[str, Any]], output_path: str | Path) -> None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(
                {
                    "schema_version": FORMAT_SCHEMA_VERSION,
                    "elements": elements,
                    "metadata": {
                        "element_count": len(elements),
                        "types": ContentLoader.count_element_types(elements),
                    },
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"   Processed content saved: {output_path}")
