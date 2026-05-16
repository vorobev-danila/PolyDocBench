"""Geometry helpers for transform-aware degraded GT."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from polydocbench.document.schema import FORMAT_SCHEMA_VERSION
from polydocbench.gt.schema import validate_gt_document


Point = tuple[float, float]
Matrix = list[list[float]]


def pdf_bbox_to_pixel_bbox(bbox: dict[str, Any], zoom: float, image_height: int) -> dict[str, float]:
    """Convert a PDF point bbox with bottom-left origin into image pixels with top-left origin."""

    x = float(bbox["x"]) * zoom
    width = float(bbox["width"]) * zoom
    height = float(bbox["height"]) * zoom
    y = image_height - (float(bbox["y"]) + float(bbox["height"])) * zoom
    return {"x": x, "y": y, "width": width, "height": height}


def bbox_to_polygon(bbox: dict[str, float]) -> list[Point]:
    x = float(bbox["x"])
    y = float(bbox["y"])
    width = float(bbox["width"])
    height = float(bbox["height"])
    return [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]


def transform_point(point: Point, matrix: Matrix) -> Point:
    x, y = point
    return (
        float(matrix[0][0]) * x + float(matrix[0][1]) * y + float(matrix[0][2]),
        float(matrix[1][0]) * x + float(matrix[1][1]) * y + float(matrix[1][2]),
    )


def transform_polygon(polygon: list[Point], matrix: Matrix) -> list[Point]:
    return [transform_point(point, matrix) for point in polygon]


def polygon_to_bbox(polygon: list[Point], image_width: int | None = None, image_height: int | None = None) -> dict[str, float]:
    min_x = min(point[0] for point in polygon)
    min_y = min(point[1] for point in polygon)
    max_x = max(point[0] for point in polygon)
    max_y = max(point[1] for point in polygon)

    if image_width is not None:
        min_x = max(0.0, min(float(image_width), min_x))
        max_x = max(0.0, min(float(image_width), max_x))
    if image_height is not None:
        min_y = max(0.0, min(float(image_height), min_y))
        max_y = max(0.0, min(float(image_height), max_y))

    return {"x": min_x, "y": min_y, "width": max(0.0, max_x - min_x), "height": max(0.0, max_y - min_y)}


def transform_pdf_bbox_to_pixel_geometry(
    bbox: dict[str, Any],
    zoom: float,
    source_image_height: int,
    transform_matrix: Matrix,
    output_width: int,
    output_height: int,
) -> tuple[dict[str, float], list[list[float]]]:
    pixel_bbox = pdf_bbox_to_pixel_bbox(bbox, zoom=zoom, image_height=source_image_height)
    polygon = transform_polygon(bbox_to_polygon(pixel_bbox), transform_matrix)
    transformed_bbox = polygon_to_bbox(polygon, image_width=output_width, image_height=output_height)
    return transformed_bbox, [[x, y] for x, y in polygon]


def transform_gt_to_image_gt(
    source_gt: dict[str, Any],
    image_path: str | Path,
    source_pdf_path: str | Path,
    source_gt_path: str | Path,
    page_number: int,
    zoom: float,
    source_image_height: int,
    output_width: int,
    output_height: int,
    transform_matrix: Matrix,
    profile: str,
    variant: int,
    dpi: int,
) -> dict[str, Any]:
    """Create pixel-coordinate GT paired with one degraded image."""

    top_level_elements: list[dict[str, Any]] = []
    for element in source_gt.get("elements", []):
        transformed = _transform_element(
            element,
            page_number,
            zoom,
            source_image_height,
            output_width,
            output_height,
            transform_matrix,
        )
        if transformed is not None:
            top_level_elements.append(transformed)
    container_elements: list[dict[str, Any]] = []
    for page in source_gt.get("pages", []):
        if int(page.get("page_number", -1)) != int(page_number):
            continue
        for container in page.get("containers", []):
            for element in container.get("elements", []):
                transformed = _transform_element(
                    element,
                    page_number,
                    zoom,
                    source_image_height,
                    output_width,
                    output_height,
                    transform_matrix,
                )
                if transformed is not None:
                    transformed.setdefault("metadata", {})["container_id"] = container.get("id", "")
                    container_elements.append(transformed)

    degraded_gt = {
        "schema_version": FORMAT_SCHEMA_VERSION,
        "metadata": {
            "generator": "PolyDocBench",
            "format_version": FORMAT_SCHEMA_VERSION,
            "source_pdf": str(source_pdf_path),
            "source_gt": str(source_gt_path),
            "profile": profile,
            "variant": variant,
            "dpi": dpi,
            "zoom": zoom,
            "coordinate_system": {
                "unit": "pixels",
                "origin": "top-left",
                "image_width": output_width,
                "image_height": output_height,
            },
            "transform": {
                "type": "affine",
                "matrix": transform_matrix,
            },
        },
        "image": {
            "path": str(image_path),
            "width": output_width,
            "height": output_height,
        },
        "reading_order": copy.deepcopy(source_gt.get("reading_order", {"blocks": [], "lines": []})),
        "pages": [
            {
                "page_number": 1,
                "width": output_width,
                "height": output_height,
                "containers": [
                    {
                        "id": f"page_{page_number}_image",
                        "type": "degraded_image",
                        "bbox": {"x": 0, "y": 0, "width": output_width, "height": output_height, "page": 1},
                        "element_count": len(container_elements),
                        "elements": container_elements,
                    }
                ],
            }
        ],
        "elements": top_level_elements,
    }
    validate_gt_document(degraded_gt)
    return degraded_gt


def _transform_element(
    element: dict[str, Any],
    page_number: int,
    zoom: float,
    source_image_height: int,
    output_width: int,
    output_height: int,
    transform_matrix: Matrix,
) -> dict[str, Any] | None:
    bbox = element.get("bbox")
    if not bbox or int(bbox.get("page", page_number)) != int(page_number):
        return None

    transformed = copy.deepcopy(element)
    new_bbox, polygon = transform_pdf_bbox_to_pixel_geometry(
        bbox,
        zoom=zoom,
        source_image_height=source_image_height,
        transform_matrix=transform_matrix,
        output_width=output_width,
        output_height=output_height,
    )
    new_bbox["page"] = 1
    transformed["bbox"] = new_bbox
    transformed["polygon"] = polygon
    transformed.setdefault("metadata", {})["source_bbox"] = copy.deepcopy(bbox)
    transformed["metadata"]["coordinate_system"] = "pixels-top-left"
    return transformed
