"""Geometric visibility facts, independent of task-specific scoring decisions."""

from __future__ import annotations

import math

from shapely import __version__, geos_version_string
from shapely.geometry import Polygon, box


VISIBILITY_SCHEMA_VERSION = "0.1"


def geometry_engine() -> str:
    return f"shapely-{__version__}/geos-{geos_version_string}"


def polygon_geometry(points):
    if (not isinstance(points, (list, tuple)) or len(points) < 3
            or any(not isinstance(p, (list, tuple)) or len(p) != 2
                   or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in p)
                   for p in points)):
        raise ValueError("Expected at least three finite 2D polygon points")
    geometry = Polygon(points)
    if not geometry.is_valid or geometry.area <= 0:
        raise ValueError("Polygon must be simple and have positive area; invalid shapes are not repaired")
    return geometry


def bbox_geometry(bbox):
    values = [bbox.get(k) for k in ("x", "y", "width", "height")]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise ValueError("Expected a finite numeric bbox")
    x, y, width, height = values
    if min(width, height) <= 0:
        raise ValueError("Prediction bbox must have positive dimensions")
    return box(x, y, x + width, y + height)


def visibility_facts(points, width: int, height: int, *, epsilon: float = 0.05) -> dict:
    if min(width, height) <= 0 or not math.isfinite(epsilon) or epsilon < 0:
        raise ValueError("Canvas dimensions must be positive and epsilon finite/nonnegative")
    geometry = polygon_geometry(points)
    canvas = box(0, 0, width, height)
    clipped = geometry.intersection(canvas)
    fraction = min(1.0, max(0.0, clipped.area / geometry.area))
    inside = box(-epsilon, -epsilon, width + epsilon, height + epsilon).covers(geometry)
    status = "outside" if clipped.area == 0 else "inside" if inside else "partial"
    clipped_points = ([list(point) for point in clipped.exterior.coords[:-1]]
                      if clipped.geom_type == "Polygon" and clipped.area > 0 else [])
    return {"schema_version": VISIBILITY_SCHEMA_VERSION, "coordinate_epsilon_pixels": epsilon, "visible_fraction": fraction,
            "status": status, "clipped_polygon": clipped_points}
