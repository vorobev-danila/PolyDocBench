"""Docling adapter for structure evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .structure import normalize_structure_type


def extract_docling_structure(
    input_path: str | Path,
    *,
    raw_output_path: str | Path | None = None,
    page_number: int = 1,
) -> list[dict[str, Any]]:
    """Run Docling and return normalized structure elements."""
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as exc:
        raise RuntimeError('Install Docling dependencies with: uv pip install -e ".[structure]"') from exc

    converter = DocumentConverter()
    result = converter.convert(str(input_path))
    document = result.document
    if hasattr(document, "export_to_dict"):
        payload = document.export_to_dict()
    elif hasattr(document, "model_dump"):
        payload = document.model_dump(mode="json")
    else:
        raise RuntimeError("Docling document does not provide export_to_dict() or model_dump().")

    if raw_output_path:
        raw_path = Path(raw_output_path)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return parse_docling_structure(payload, page_number=page_number)


def parse_docling_structure(docling_json: dict[str, Any], *, page_number: int = 1) -> list[dict[str, Any]]:
    """Parse a DoclingDocument dictionary into PolyDocBench structure elements."""
    page_heights = _page_heights(docling_json)
    candidates: list[dict[str, Any]] = []
    reading_order = 0
    for collection_name, default_type in (("texts", "paragraph"), ("tables", "table"), ("pictures", "image")):
        for index, item in enumerate(docling_json.get(collection_name, []) or []):
            element = _parse_item(
                item,
                fallback_id=f"docling_{collection_name}_{index}",
                default_type=default_type,
                page_heights=page_heights,
                fallback_reading_order=reading_order,
            )
            reading_order += 1
            if element and int(element.get("page_number", page_number)) == int(page_number):
                candidates.append(element)

    if not candidates:
        for index, item in enumerate(docling_json.get("elements", []) or []):
            element = _parse_item(
                item,
                fallback_id=f"docling_element_{index}",
                default_type="unknown",
                page_heights=page_heights,
                fallback_reading_order=index,
            )
            if element and int(element.get("page_number", page_number)) == int(page_number):
                candidates.append(element)

    return sorted(candidates, key=lambda element: (int(element.get("reading_order", 10**9)), str(element["id"])))


def _parse_item(
    item: dict[str, Any],
    *,
    fallback_id: str,
    default_type: str,
    page_heights: dict[int, float],
    fallback_reading_order: int,
) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    provenance = _first_provenance(item)
    bbox = _extract_bbox(item, provenance, page_heights)
    if not bbox:
        return None
    page_number = int(provenance.get("page_no") or provenance.get("page") or bbox.get("page", 1))
    raw_type = item.get("label") or item.get("type") or item.get("category") or default_type
    text = str(item.get("text") or item.get("orig") or item.get("caption_text") or "")
    return {
        "id": str(item.get("self_ref") or item.get("id") or fallback_id),
        "type": normalize_structure_type(raw_type),
        "text": text,
        "bbox": {key: float(bbox[key]) for key in ("x", "y", "width", "height")},
        "page_number": page_number,
        "reading_order": int(item.get("reading_order", fallback_reading_order)),
        "source": "docling",
        "metadata": {"raw_type": str(raw_type), "collection": default_type},
    }


def _first_provenance(item: dict[str, Any]) -> dict[str, Any]:
    provenance = item.get("prov") or item.get("provenance") or []
    if isinstance(provenance, list) and provenance:
        return provenance[0] if isinstance(provenance[0], dict) else {}
    return provenance if isinstance(provenance, dict) else {}


def _extract_bbox(
    item: dict[str, Any], provenance: dict[str, Any], page_heights: dict[int, float]
) -> dict[str, float] | None:
    bbox = item.get("bbox") or provenance.get("bbox")
    if not isinstance(bbox, dict):
        return None
    page_number = int(provenance.get("page_no") or provenance.get("page") or bbox.get("page", 1))
    if all(key in bbox for key in ("x", "y", "width", "height")):
        return {
            "x": float(bbox["x"]),
            "y": float(bbox["y"]),
            "width": float(bbox["width"]),
            "height": float(bbox["height"]),
            "page": float(page_number),
        }
    left = bbox.get("l", bbox.get("left"))
    right = bbox.get("r", bbox.get("right"))
    top = bbox.get("t", bbox.get("top"))
    bottom = bbox.get("b", bbox.get("bottom"))
    if None in (left, right, top, bottom):
        return None
    left_f, right_f, top_f, bottom_f = float(left), float(right), float(top), float(bottom)
    origin = str(bbox.get("coord_origin") or bbox.get("origin") or "").lower()
    if "bottom" in origin and page_number in page_heights:
        page_height = page_heights[page_number]
        y = page_height - max(top_f, bottom_f)
    else:
        y = min(top_f, bottom_f)
    return {
        "x": min(left_f, right_f),
        "y": y,
        "width": abs(right_f - left_f),
        "height": abs(bottom_f - top_f),
        "page": float(page_number),
    }


def _page_heights(docling_json: dict[str, Any]) -> dict[int, float]:
    pages = docling_json.get("pages") or {}
    result: dict[int, float] = {}
    if isinstance(pages, dict):
        iterable = pages.items()
    elif isinstance(pages, list):
        iterable = enumerate(pages, start=1)
    else:
        iterable = []
    for key, page in iterable:
        if not isinstance(page, dict):
            continue
        size = page.get("size") or page
        height = size.get("height") if isinstance(size, dict) else None
        if height is not None:
            result[int(page.get("page_no") or page.get("page") or key)] = float(height)
    return result
