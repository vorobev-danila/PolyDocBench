"""Image resource preparation shared by layout and rendering."""

from __future__ import annotations

import hashlib
import math
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests
from PIL import Image


def resolve_image(source: str, cache_dir: str | Path = "outputs/cache/images") -> Path | None:
    if not source.startswith(("https://", "http://")):
        path = Path(source)
        return path if path.is_file() else None
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(source.encode("utf-8")).hexdigest()
    existing = next(cache.glob(f"{key}.*"), None)
    if existing is not None:
        return existing
    try:
        response = requests.get(source, timeout=10, headers={"User-Agent": "PolyDocBench/0.1"})
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").split(";")[0].strip()
        if content_type and not content_type.startswith("image/"):
            return None
        if len(response.content) > 20 * 1024 * 1024:
            return None
    except requests.RequestException:
        return None
    suffix = Path(urlparse(source).path).suffix.lower()
    if content_type == "image/svg+xml":
        suffix = ".svg"
    elif suffix not in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".svg"}:
        suffix = mimetypes.guess_extension(content_type) or ".img"
    target = cache / f"{key}{suffix}"
    target.write_bytes(response.content)
    return target


def image_dimensions(path: Path) -> tuple[float, float]:
    try:
        with Image.open(path) as image:
            return tuple(float(value) for value in image.size)
    except (OSError, ValueError):
        try:
            root = ElementTree.parse(path).getroot()
        except ElementTree.ParseError as exc:
            raise ValueError(f"Unsupported or corrupt image: {path}") from exc
        if root.tag.split("}")[-1] != "svg":
            raise ValueError(f"Unsupported image: {path}")
        def length(value):
            match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(px|pt|mm|cm|in)?\s*", value or "")
            if match is None:
                return 0.0
            factor = {"px": 1, "pt": 96 / 72, "mm": 96 / 25.4, "cm": 96 / 2.54, "in": 96}
            return float(match[1]) * factor.get(match[2], 1)

        width, height = length(root.get("width")), length(root.get("height"))
        viewbox = root.get("viewBox", "").replace(",", " ").split()
        if (not width or not height) and len(viewbox) == 4:
            width, height = float(viewbox[2]), float(viewbox[3])
        if not all(math.isfinite(value) and value > 0 for value in (width, height)):
            raise ValueError(f"Image has no positive dimensions: {path}")
        return width, height
