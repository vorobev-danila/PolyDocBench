"""Ground-truth validation helpers."""

from __future__ import annotations

from typing import Any


def validate_basic_gt(gt_data: dict[str, Any]) -> list[str]:
    """Return human-readable validation errors for the current GT JSON shape."""

    errors: list[str] = []
    if "pages" not in gt_data:
        errors.append("Missing 'pages'")
    if "metadata" not in gt_data:
        errors.append("Missing 'metadata'")

    for page_index, page in enumerate(gt_data.get("pages", []), start=1):
        if "page_number" not in page:
            errors.append(f"Page {page_index}: missing page_number")
        for container in page.get("containers", []):
            for element in container.get("elements", []):
                if not element.get("bbox"):
                    errors.append(f"Element {element.get('id', '<unknown>')}: missing bbox")

    return errors

