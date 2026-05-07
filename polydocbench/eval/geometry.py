"""Geometry helpers for document evaluation."""

from __future__ import annotations

from .types import BBoxDict


def to_xyxy(bbox: BBoxDict) -> tuple[float, float, float, float]:
    """Convert ``x, y, width, height`` to ``x0, y0, x1, y1``."""

    x0 = float(bbox["x"])
    y0 = float(bbox["y"])
    return x0, y0, x0 + float(bbox["width"]), y0 + float(bbox["height"])


def bbox_iou(first: BBoxDict, second: BBoxDict) -> float:
    """Return intersection-over-union for two bottom-left-origin bboxes."""

    ax0, ay0, ax1, ay1 = to_xyxy(first)
    bx0, by0, bx1, by1 = to_xyxy(second)

    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)

    intersection = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - intersection

    return intersection / union if union > 0 else 0.0

