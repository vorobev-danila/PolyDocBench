"""Independent affine/canvas oracle; does not call the production GT transformer."""

from __future__ import annotations

import math

import numpy as np

from .audit import GTAuditResult, audit_gt_document


def _area(points):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))) / 2


def visible_polygon_fraction(points, width, height):
    """Clip a convex affine box with Sutherland-Hodgman against the canvas."""
    original = _area(points)
    clipped = list(points)
    for axis, bound, sign in ((0, 0, 1), (0, width, -1), (1, 0, 1), (1, height, -1)):
        previous = clipped
        clipped = []
        for a, b in zip(previous, previous[1:] + previous[:1]):
            inside_a, inside_b = sign * (a[axis] - bound) >= 0, sign * (b[axis] - bound) >= 0
            if inside_a != inside_b:
                t = (bound - a[axis]) / (b[axis] - a[axis])
                clipped.append([a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])])
            if inside_b:
                clipped.append(b)
    return min(1.0, max(0.0, _area(clipped) / original)) if original else 0.0


def audit_image_gt(data: dict, source_gt: dict, *, source_page_number: int, image_size: tuple[int, int],
                   dpi: int, tolerance: float = 0.05) -> GTAuditResult:
    result = audit_gt_document(data, coordinate_system="image", tolerance=tolerance)
    if "structure" not in result.checks:
        return result
    width, height = image_size
    if min(width, height, dpi) <= 0:
        raise ValueError("Image dimensions/DPI must be positive")
    metadata = data.get("metadata", {})
    units = metadata.get("coordinate_system", {})
    zoom_valid = isinstance(metadata.get("zoom"), (int, float)) and math.isclose(metadata["zoom"], dpi / 72)
    if (not isinstance(units, dict) or units.get("unit") != "pixels" or units.get("origin") != "top-left"
            or units.get("image_width") != width or units.get("image_height") != height
            or data.get("image", {}).get("width") != width or data.get("image", {}).get("height") != height
            or metadata.get("dpi") != dpi or not zoom_valid):
        result.add("image_coordinates", "Image metadata does not match actual pixel dimensions/DPI")
    if len(data["pages"]) != 1 or data["pages"][0]["page_number"] != 1 or (data["pages"][0]["width"], data["pages"][0]["height"]) != image_size:
        result.add("image_page", "Single-image GT must use page 1 and actual pixel dimensions")
    try:
        matrix = np.asarray(metadata["transform"]["matrix"], dtype=float)
        if matrix.shape != (2, 3) or not np.isfinite(matrix).all() or abs(np.linalg.det(matrix[:, :2])) < 1e-12:
            raise ValueError("Invalid affine matrix")
    except (KeyError, TypeError, ValueError):
        result.add("affine_matrix", "Need a finite nondegenerate 2x3 transform")
        return result
    trace = metadata.get("noise_generation")
    if trace:
        composed = np.eye(3)
        for operation in trace.get("operations", []):
            if operation["name"] != "random_affine":
                continue
            params = operation["parameters"]
            angle = math.radians(params["angle_degrees"])
            c, s = math.cos(angle), math.sin(angle)
            cx, cy = width / 2, height / 2
            expected = np.array([[c, s + params["shear"], (1 - c) * cx - s * cy],
                                 [-s, c, s * cx + (1 - c) * cy]])
            if not np.allclose(expected, params["matrix"], atol=1e-8, rtol=0):
                result.add("affine_parameters", "Recorded affine matrix differs from angle/shear")
            homogeneous = np.eye(3)
            homogeneous[:2] = expected
            composed = homogeneous @ composed
        if not np.allclose(matrix, composed[:2], atol=1e-8, rtol=0):
            result.add("trace_transform", "GT matrix differs from the independent operation composition")
        result.checks["trace_affine_parameters"] = "checked"
    else:
        result.checks["trace_affine_parameters"] = "unavailable_legacy_trace"
        result.add("legacy_trace", "No operation trace; coordinate consistency does not verify pixel generation", severity="warning")
    sources = [e for e in source_gt.get("elements", []) if (e.get("bbox") or {}).get("page") == source_page_number]
    if source_page_number not in {page["page_number"] for page in source_gt.get("pages", [])}:
        result.add("source_page_missing", "Source GT does not describe the requested PDF page")
    actual = {e["id"]: e for e in data["elements"]}
    source_ids = {e["id"] for e in sources}
    if source_ids != set(actual):
        result.add("transformed_membership", f"Missing {len(source_ids - set(actual))}, extra {len(set(actual) - source_ids)} transformed IDs")
    expected_order = {k: [i for i in order if i in source_ids] for k, order in source_gt.get("reading_order", {}).items()}
    if data.get("reading_order") != expected_order:
        result.add("transformed_order", "Image reading order differs from the source-page subsequence")
    maximum = 0.0
    checked = partially = fully = 0
    for source in sources:
        entry = actual.get(source["id"])
        if entry is None:
            continue
        box = source["bbox"]
        if not all(isinstance(box.get(k), (int, float)) and math.isfinite(box[k]) for k in ("x", "y", "width", "height")):
            result.add("source_bbox_invalid", "Cannot transform a nonfinite source bbox", source)
            continue
        zoom = dpi / 72
        x0, x1 = box["x"] * zoom, (box["x"] + box["width"]) * zoom
        y0, y1 = height - (box["y"] + box["height"]) * zoom, height - box["y"] * zoom
        corners = np.array([[x0, y0, 1], [x1, y0, 1], [x1, y1, 1], [x0, y1, 1]])
        expected = corners @ matrix.T
        try:
            polygon = np.asarray(entry["polygon"], dtype=float)
            bbox = entry["bbox"]
            if polygon.shape != (4, 2) or not np.isfinite(polygon).all():
                raise ValueError("Expected four finite corners")
            low, high = np.clip(expected.min(axis=0), [0, 0], [width, height]), np.clip(expected.max(axis=0), [0, 0], [width, height])
            expected_box = [*low, *(high - low)]
            observed_box = [bbox[k] for k in ("x", "y", "width", "height")]
            error = max(float(np.abs(polygon - expected).max()), float(np.abs(np.array(observed_box) - expected_box).max()))
            if not math.isfinite(error):
                raise ValueError("Nonfinite geometry")
            maximum = max(maximum, error)
            checked += 1
            if error > tolerance:
                result.add("transformed_geometry", f"Maximum coordinate error {error:.6g} pixels exceeds {tolerance}", entry)
        except (KeyError, TypeError, ValueError):
            result.add("polygon_invalid", "Missing/malformed polygon or bbox", entry)
        if any(entry.get(k) != source.get(k) for k in ("content", "type")):
            result.add("transformed_content", "Text/type changed during image GT transformation", entry)
        for key in ("parent_id", "caption_for", "source_cell_id", "source_index", "role", "repeated_header"):
            if entry.get("metadata", {}).get(key) != source.get("metadata", {}).get(key):
                result.add("transformed_reference", f"Metadata {key} changed", entry)
        fraction = visible_polygon_fraction(expected.tolist(), width, height)
        if fraction < 1 - 1e-9:
            fully += int(fraction < 1e-9)
            partially += int(fraction >= 1e-9)
            result.add("fully_clipped" if fraction < 1e-9 else "partially_clipped",
                       f"Geometric visible area fraction {fraction:.6f}; visibility policy needs review", entry, severity="warning")
    result.counts.update(expected_transform_elements=len(sources), checked_transform_elements=checked,
                         partially_clipped_elements=partially, fully_clipped_elements=fully)
    result.max_geometry_error_pixels = maximum if checked else None
    result.checks["affine_oracle"] = "checked" if checked == len(sources) and sources else "incomplete"
    return result
