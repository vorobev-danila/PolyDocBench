"""Ground-truth loading and extraction helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .types import LineDict


def load_gt(path: str | Path) -> dict[str, Any]:
    """Load a PolyDocBench ground-truth JSON file."""

    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def extract_gt_lines(gt_json: dict[str, Any], page_number: int) -> list[LineDict]:
    """Extract line-level GT for a page from the current PolyDocBench schema."""

    lines: list[LineDict] = []
    for page in gt_json.get("pages", []):
        if int(page.get("page_number", -1)) != int(page_number):
            continue

        for container in page.get("containers", []):
            for element in container.get("elements", []):
                if element.get("type") != "text_line":
                    continue

                bbox = element.get("bbox")
                if not bbox or int(bbox.get("page", page_number)) != int(page_number):
                    continue

                lines.append(
                    {
                        "id": element.get("id", ""),
                        "type": "text_line",
                        "text": element.get("content", ""),
                        "bbox": {
                            "x": float(bbox["x"]),
                            "y": float(bbox["y"]),
                            "width": float(bbox["width"]),
                            "height": float(bbox["height"]),
                        },
                        "page_number": int(page_number),
                        "container_id": container.get("id", ""),
                    }
                )

    return lines

