"""Debug visualization helpers for noisy image GT."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw


OverlayMode = Literal["polygon", "bbox", "both"]


def draw_gt_overlay(
    image_path: str | Path,
    gt_path: str | Path,
    output_path: str | Path,
    mode: OverlayMode = "polygon",
    polygon_color: str = "red",
    bbox_color: str = "blue",
    line_width: int = 2,
) -> str:
    """Draw transformed GT polygons and/or bboxes over a noisy image."""

    if mode not in {"polygon", "bbox", "both"}:
        raise ValueError("mode must be one of: polygon, bbox, both")
    if line_width < 1:
        raise ValueError("line_width must be at least 1")

    gt = json.loads(Path(gt_path).read_text(encoding="utf-8"))
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)

    for element in _iter_elements(gt):
        if mode in {"polygon", "both"} and element.get("polygon"):
            points = [tuple(point) for point in element["polygon"]]
            draw.line(points + [points[0]], fill=polygon_color, width=line_width)

        if mode in {"bbox", "both"} and element.get("bbox"):
            bbox = element["bbox"]
            x = float(bbox["x"])
            y = float(bbox["y"])
            draw.rectangle(
                [x, y, x + float(bbox["width"]), y + float(bbox["height"])],
                outline=bbox_color,
                width=line_width,
            )

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)
    return str(target)


def _iter_elements(gt: dict) -> list[dict]:
    elements: list[dict] = []
    for page in gt.get("pages", []):
        for container in page.get("containers", []):
            elements.extend(container.get("elements", []))
    if elements:
        return elements
    return list(gt.get("elements", []))
