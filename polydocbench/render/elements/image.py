"""Image element renderer."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from reportlab.lib.utils import ImageReader

from polydocbench.document.assets import resolve_image

from .base import BaseElementRenderer


class ImageRenderer(BaseElementRenderer):
    """Render local or remote images into an element bbox."""

    supported_types = {"image"}

    def render(self, element: dict[str, Any]) -> None:
        if element.get("type") not in self.supported_types:
            return
        rendered = self.render_image(element)
        if not rendered and element.get("metadata", {}).get("require_asset"):
            raise RuntimeError(f"Could not draw prepared image: {self._get_image_source(element)}")

    def render_image(self, element: dict[str, Any]) -> bool:
        image_path = self._resolve_image_path(element)
        if image_path is None:
            return False

        x, y, width, height = self._get_bbox_coords(element)
        if width <= 0 or height <= 0:
            return False

        return self._draw_image(image_path, x, y, width, height)

    def _draw_image(self, image_path: Path, x: float, y: float, width: float, height: float) -> bool:
        if image_path.suffix.lower() == ".svg" or self._is_svg_file(image_path):
            return self._draw_svg(image_path, x, y, width, height)

        return self._draw_raster(image_path, x, y, width, height)

    def _draw_raster(self, image_path: Path, x: float, y: float, width: float, height: float) -> bool:
        try:
            self.canvas.drawImage(
                ImageReader(str(image_path)),
                x,
                y,
                width=width,
                height=height,
                preserveAspectRatio=True,
                anchor="c",
                mask="auto",
            )
        except Exception:
            return False
        return True

    def _draw_svg(self, image_path: Path, x: float, y: float, width: float, height: float) -> bool:
        try:
            from reportlab.graphics import renderPDF
            from svglib.svglib import svg2rlg
        except Exception:
            return False

        drawing = svg2rlg(str(image_path))
        if drawing is None or not drawing.width or not drawing.height:
            return False

        scale = min(width / drawing.width, height / drawing.height)
        render_width = drawing.width * scale
        render_height = drawing.height * scale
        drawing.scale(scale, scale)
        renderPDF.draw(drawing, self.canvas, x + (width - render_width) / 2, y + (height - render_height) / 2)
        return True

    def _resolve_image_path(self, element: dict[str, Any]) -> Path | None:
        source = self._get_image_source(element)
        if not source:
            return None

        if source.startswith(("http://", "https://")):
            return self._download_to_cache(source)

        path = Path(source)
        if path.exists():
            return path

        return None

    @staticmethod
    def _get_image_source(element: dict[str, Any]) -> str:
        metadata = element.get("metadata") or {}
        dimensions = element.get("dimensions") or {}
        for container in (element, metadata, dimensions):
            for key in ("src", "path", "url", "image_src"):
                value = container.get(key)
                if value:
                    return str(value)
        return ""

    def _download_to_cache(self, url: str) -> Path | None:
        return resolve_image(url, self.config.get("render.images.cache_dir", "outputs/cache/images"))

    @staticmethod
    def _is_svg_file(path: Path) -> bool:
        try:
            prefix = path.read_text(encoding="utf-8", errors="ignore")[:256].lower()
        except Exception:
            return False
        return "<svg" in prefix or "<?xml" in prefix and "svg" in prefix
