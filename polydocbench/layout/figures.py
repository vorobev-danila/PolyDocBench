"""Aspect-preserving figures kept together with visible captions."""

from pathlib import Path
import math

from polydocbench.document import BBox, DocumentElement
from polydocbench.document.assets import image_dimensions, resolve_image
from polydocbench.layout.compound import caption_lines, make_caption
from polydocbench.layout.placement_types import PlacementResult
from polydocbench.layout.specs import ElementLayoutSpec


class ImagePlacementHandler:
    def __init__(self, context):
        self.context = context

    def place(self, element_data, typography, layout_type):
        context = self.context
        container = context.current_container
        if container is None:
            return PlacementResult(False, message="No container for image")
        source = next((str(element_data[key]) for key in ("src", "path", "url", "image_src")
                       if element_data.get(key)), "")
        metadata = {key: element_data[key] for key in ("caption", "alt", "alt_text") if key in element_data}
        options = context.options.get("images", {})
        if source:
            if not source.startswith(("http://", "https://")) and not Path(source).is_file():
                source = str(context.source_dir / source)
            path = resolve_image(source, context.options.get("assets", {}).get("cache_dir", "outputs/cache/images"))
            if path is None:
                raise ValueError(f"Image could not be loaded: {source}")
            native_width, native_height = image_dimensions(path)
            metadata.update({"src": str(path.resolve()), "source_url": element_data.get("src", source),
                             "pixel_width": native_width, "pixel_height": native_height, "require_asset": True})
        else:
            if context.options.get("strict_layout", False):
                raise ValueError("Image requires a source path or URL")
            spec = ElementLayoutSpec.from_element(element_data)
            native_width, native_height = spec.width, spec.height
        requested_width = float(element_data.get("width") or container.width * float(options.get("width_fraction", 1.0)))
        requested_height = float(element_data.get("height") or context.full_page_height * float(options.get("max_height_fraction", 0.5)))
        if not all(math.isfinite(value) and value > 0 for value in (requested_width, requested_height)):
            raise ValueError("Figure dimensions must be positive")
        scale = min(requested_width / native_width, requested_height / native_height, container.width / native_width)
        width, height = native_width * scale, native_height * scale
        caption = str(element_data.get("caption") or "")
        lines = caption_lines(context, caption, width, float(options.get("caption_size", typography.body_size)))
        caption_height = sum(line.height for line in lines)
        gap = 6 if lines else 0
        if caption_height + gap >= context.full_page_height:
            raise ValueError("Figure caption is taller than a page")
        if height + caption_height + gap > context.full_page_height:
            scale = (context.full_page_height - caption_height - gap) / height
            width, height = width * scale, height * scale
        total = height + caption_height + gap
        while not context.current_container.can_fit(total):
            if not (context._try_switch_column() or context._create_new_page()):
                raise ValueError("No space for image and caption")
        container = context.current_container
        allocation = container.place(total)
        x = container.x + (container.width - width) / 2
        top = allocation.y + allocation.height
        element_id = element_data["_layout_id"]
        metadata.update({"role": "block", "source_index": element_data["_source_index"], "container_id": container.id})
        result = PlacementResult(True, elements=[DocumentElement(
            id=element_id, type="image", bbox=BBox(x, top - height, width, height, allocation.page), metadata=metadata,
        )])
        caption_width = max((line.target_width for line in lines), default=width)
        caption_x = container.x + (container.width - caption_width) / 2
        result.elements.extend(make_caption(context, caption, lines, top - height - gap, caption_x, caption_width,
                               f"{element_id}_caption", element_id, element_data["_source_index"]))
        if container.can_fit(typography.paragraph_spacing):
            container.place(typography.paragraph_spacing)
        return result
