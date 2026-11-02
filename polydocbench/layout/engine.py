"""Layout engine orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from collections import defaultdict
import math

from polydocbench.document import DocumentElement, Page
from polydocbench.layout.bbox import BBoxCalculator
from polydocbench.layout.column_strategy import ColumnStrategy
from polydocbench.layout.content_loader import ContentLoader
from polydocbench.layout.ids import ElementIdGenerator
from polydocbench.layout.placement import PlacedLine, PlacementEngine, PlacementResult
from polydocbench.layout.result import LayoutResult
from polydocbench.layout.template_manager import TemplateManager
from polydocbench.layout.templates import DEFAULT_TEMPLATE_PATH
from polydocbench.layout.typography import TypographyStyle


class LayoutEngine:
    """Coordinate content loading, page creation, and element placement."""

    def __init__(
        self,
        template_config_path: str | Path = DEFAULT_TEMPLATE_PATH,
        font_path: str | Path | None = None,
    ) -> None:
        self.page_factory = lambda: self._create_new_page()
        self.template_manager = TemplateManager(str(template_config_path))
        self.bbox_calculator = BBoxCalculator(font_path=str(font_path) if font_path else None)
        self.column_strategy = ColumnStrategy()
        self.placement_engine = PlacementEngine(
            bbox_calculator=self.bbox_calculator,
            page_factory=self.page_factory,
            column_strategy=self.column_strategy,
        )
        self.layout_result = LayoutResult()
        self.current_page: Page | None = None
        self.current_template: dict[str, Any] | None = None
        self.id_generator = ElementIdGenerator()

    def layout_document(self, json_path: str | Path, template_name: str = "simple_article") -> LayoutResult:
        print("\nНачало верстки документа...")
        self.layout_result = LayoutResult()

        elements = ContentLoader.load_json(str(json_path))
        self.placement_engine.source_dir = Path(json_path).resolve().parent
        self.current_template = self.template_manager.get_template(template_name)
        self.placement_engine.options = self.current_template

        self.current_page = self._create_page_from_template(self.current_template, 1)
        self.layout_result.add_page(self.current_page)
        self.placement_engine.setup_page(self.current_page)

        self._place_elements(elements)
        self.layout_result.prepare_ground_truth()

        print("Верстка завершена!")
        return self.layout_result

    def _place_elements(self, elements: list[dict[str, Any]]) -> None:
        assert self.current_template is not None

        for index, element_data in enumerate(elements, start=1):
            if self.current_template.get("balance_before_spans", False):
                self._balance_upcoming_band(elements[index - 1:])
            element_type = element_data.get("type", "text_line")
            for warning in element_data.get("extraction_warnings", []):
                if self.current_template.get("strict_layout", False):
                    raise ValueError(f"Element {index} ({element_type}): {warning}")
                self.layout_result.warnings.append({"source_index": index, "type": element_type, "message": warning})
            main_id = self.id_generator.block_id(element_type, index)
            try:
                placement_result = self.placement_engine.prepare_element(
                    {**element_data, "_layout_id": main_id, "_source_index": index},
                    self.current_template.get("typography", {}),
                    self.current_template.get("layout_type", "single_column"),
                )
            except (ValueError, OSError) as exc:
                if self.current_template.get("strict_layout", False):
                    raise ValueError(f"Element {index} ({element_type}): {exc}") from exc
                placement_result = PlacementResult(False, message=str(exc))

            if not placement_result.success:
                if self.current_template.get("strict_layout", False):
                    raise ValueError(f"Element {index} ({element_type}): {placement_result.message}")
                self.layout_result.warnings.append({"source_index": index, "type": element_type,
                                                    "message": placement_result.message})
                print(f"Элемент {index}: {element_type} не удалось разместить: {placement_result.message}")
                continue

            if placement_result.elements:
                for order, element in enumerate(placement_result.elements):
                    element.metadata["flow_order"] = order
                    self.layout_result.add_element(element)
                    self._attach_element(element, element.metadata["container_id"])
                continue

            groups = defaultdict(list)
            for line in placement_result.placed_lines:
                groups[(line.page_number, line.container_id)].append(line)
            for fragment_index, lines in enumerate(groups.values()):
                fragment_id = main_id if not fragment_index else f"{main_id}_fragment_{fragment_index + 1:03d}"
                self._add_fragment(element_data, element_type, index, fragment_id, main_id, lines)

    def _balance_upcoming_band(self, upcoming):
        context = self.placement_engine
        if len(context.all_containers) < 2 or any(column.elements for column in context.all_containers):
            return
        typography = TypographyStyle.from_config(self.current_template.get("typography", {}))
        heights = []
        for item in upcoming:
            item_type = item.get("type", "")
            if item_type in {"image", "table"}:
                options = self.current_template.get("tables" if item_type == "table" else "images", {})
                if item.get("span_columns", options.get("span_columns")) == "all":
                    context.balance_text_band(heights)
                return
            if not (item_type.startswith("heading") or item_type in {"paragraph", "text", "text_line"}):
                return
            width = context.current_container.width
            if item_type.startswith("heading"):
                lines = self.bbox_calculator.split_heading_into_lines(
                    item.get("content", ""), width, typography.heading_size(item_type), typography.line_height,
                )
                heights.append(sum(line.height for line in lines))
            else:
                lines = self.bbox_calculator.split_into_lines(
                    item.get("content", ""), width, typography.body_size, typography.line_height,
                    first_line_indent=typography.first_line_indent,
                )
                heights.extend(line.height for line in lines)
                if typography.paragraph_spacing:
                    heights.append(typography.paragraph_spacing)

    def _add_fragment(self, element_data, element_type, index, main_id, source_id, lines):
        fragment = PlacementResult(
            True, placed_lines=lines,
            paragraph_bbox=self.placement_engine._calculate_paragraph_bbox(lines),
            total_height=sum(line.bbox.height for line in lines),
        )
        main_element = DocumentElement(
            id=main_id, type=element_type, content=" ".join(line.text for line in lines),
            bbox=fragment.paragraph_bbox, dimensions=self._build_dimensions(element_type, fragment),
            metadata=self._build_metadata(element_data, element_type, index),
        )
        main_element.metadata["source_block_id"] = source_id
        self.layout_result.add_element(main_element)
        for line_index, placed_line in enumerate(lines, start=1):
            line_element = DocumentElement(
                id=self.id_generator.line_id(main_id, line_index),
                type="text_line" if element_type.startswith("heading") else placed_line.element_type or "text_line",
                content=placed_line.text, bbox=placed_line.bbox,
                dimensions={
                    "font_size": placed_line.font_size, "font_family": placed_line.font_family,
                    "line_index": placed_line.line_index, "ascent": placed_line.ascent,
                    "descent": placed_line.descent, "paragraph_id": placed_line.paragraph_id,
                    "container_id": placed_line.container_id, "page_number": placed_line.page_number,
                    "text_width": placed_line.text_width, "target_width": placed_line.target_width,
                    "justify": placed_line.justify,
                },
                metadata={"role": "line", "parent_id": main_id, "source_index": index, "line_index": line_index},
            )
            self.layout_result.add_element(line_element)
            self._add_element_to_container(placed_line, line_element)

    @staticmethod
    def _build_dimensions(element_type: str, placement_result) -> dict[str, Any]:
        dimensions: dict[str, Any] = {
            "line_count": placement_result.line_count,
            "total_height": placement_result.total_height,
            "remaining_text": placement_result.remaining_text,
        }

        if element_type.startswith("heading"):
            dimensions["render_lines_separately"] = True
            dimensions["placed_lines"] = [
                {
                    "text": line.text,
                    "bbox": line.bbox.as_dict() if line.bbox else None,
                    "font_size": line.font_size,
                    "font_family": line.font_family,
                    "ascent": line.ascent,
                    "descent": line.descent,
                    "line_index": line.line_index,
                    "paragraph_id": line.paragraph_id,
                    "container_id": line.container_id,
                    "page_number": line.page_number,
                    "element_type": line.element_type,
                    "text_width": line.text_width,
                    "target_width": line.target_width,
                    "justify": line.justify,
                }
                for line in placement_result.placed_lines
            ]

        return dimensions

    @staticmethod
    def _build_metadata(element_data: dict[str, Any], element_type: str, source_index: int) -> dict[str, Any]:
        metadata = {
            **element_data.get("metadata", {}),
            "role": "block",
            "source_index": source_index,
            "source_type": element_type,
        }
        for key in ("src", "path", "url", "image_src", "caption", "alt", "alt_text", "alttext", "latex", "mathml", "formula_type"):
            if key in element_data:
                metadata[key] = element_data[key]
        return metadata

    def _add_element_to_container(self, placed_line: PlacedLine, element: DocumentElement) -> None:
        self._attach_element(element, placed_line.container_id)

    def _attach_element(self, element: DocumentElement, container_id: str) -> None:
        for page in self.layout_result.pages:
            if page.number != element.bbox.page:
                continue
            for container in page.containers:
                if container.id == container_id:
                    container.add_element(element)
                    return
        raise RuntimeError(f"Container {container_id} on page {element.bbox.page} was not found")

    def _create_page_from_template(self, template: dict[str, Any], page_num: int) -> Page:
        base_settings = self.template_manager.get_base_settings()
        page_width = float(template.get("page_width", base_settings.get("page_width", 595.0)))
        page_height = float(template.get("page_height", base_settings.get("page_height", 842.0)))
        if not all(math.isfinite(value) and value > 0 for value in (page_width, page_height)):
            raise ValueError("Page dimensions must be finite and positive")
        page = Page(number=page_num, width=page_width, height=page_height)

        layout_type = template.get("layout_type", "single_column")
        margins = template.get("margins", {"top": 50, "bottom": 50, "left": 50, "right": 50})
        if any(not math.isfinite(value) or value < 0 for value in margins.values()):
            raise ValueError("Margins must be finite and nonnegative")
        columns = {"two_column": 2, "three_column": 3}.get(layout_type, 1)
        gutter = float(template.get("columns", {}).get("gutter", 20))
        if not math.isfinite(gutter) or gutter < 0 or (
            page_width <= margins["left"] + margins["right"] + gutter * (columns - 1)
            or page_height <= margins["top"] + margins["bottom"]
        ):
            raise ValueError("Margins and gutters leave no usable page area")

        if layout_type == "two_column":
            page.create_multi_column(num_columns=2, gutter=template.get("columns", {}).get("gutter", 20), margins=margins)
        elif layout_type == "three_column":
            page.create_multi_column(num_columns=3, gutter=template.get("columns", {}).get("gutter", 15), margins=margins)
        else:
            page.create_single_column(margins)

        return page

    def _create_new_page(self) -> Page:
        assert self.current_template is not None

        new_page = self._create_page_from_template(self.current_template, len(self.layout_result.pages) + 1)
        self.layout_result.add_page(new_page)
        return new_page


def layout_wikipedia_json(
    json_path: str | Path,
    template_name: str = "simple_article",
    font_path: str | Path | None = None,
) -> LayoutResult:
    return LayoutEngine(font_path=font_path).layout_document(json_path=json_path, template_name=template_name)
