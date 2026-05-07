"""Layout engine orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from polydocbench.document import DocumentElement, Page
from polydocbench.layout.bbox import BBoxCalculator
from polydocbench.layout.column_strategy import ColumnStrategy
from polydocbench.layout.content_loader import ContentLoader
from polydocbench.layout.ids import ElementIdGenerator
from polydocbench.layout.placement import PlacedLine, PlacementEngine
from polydocbench.layout.result import LayoutResult
from polydocbench.layout.template_manager import TemplateManager
from polydocbench.layout.templates import DEFAULT_TEMPLATE_PATH


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
        self.current_template = self.template_manager.get_template(template_name)

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
            element_type = element_data.get("type", "text_line")
            placement_result = self.placement_engine.prepare_element(
                element_data,
                self.current_template.get("typography", {}),
                self.current_template.get("layout_type", "single_column"),
            )

            if not placement_result.success:
                print(f"Элемент {index}: {element_type} не удалось разместить: {placement_result.message}")
                continue

            main_id = self.id_generator.block_id(element_type, index)
            dimensions = self._build_dimensions(element_type, placement_result)
            main_element = DocumentElement(
                id=main_id,
                type=element_type,
                content=element_data.get("content", ""),
                bbox=placement_result.paragraph_bbox,
                dimensions=dimensions,
                metadata=self._build_metadata(element_data, element_type, index),
            )
            self.layout_result.add_element(main_element)

            if not element_type.startswith("heading"):
                for line_index, placed_line in enumerate(placement_result.placed_lines, start=1):
                    line_element = DocumentElement(
                        id=self.id_generator.line_id(main_id, line_index),
                        type=placed_line.element_type or "text_line",
                        content=placed_line.text,
                        bbox=placed_line.bbox,
                        dimensions={
                            "font_size": placed_line.font_size,
                            "font_family": placed_line.font_family,
                            "line_index": placed_line.line_index,
                            "ascent": placed_line.ascent,
                            "descent": placed_line.descent,
                            "paragraph_id": placed_line.paragraph_id,
                            "container_id": placed_line.container_id,
                            "page_number": placed_line.page_number,
                        },
                        metadata={
                            "role": "line",
                            "parent_id": main_id,
                            "source_index": index,
                            "line_index": line_index,
                        },
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
                }
                for line in placement_result.placed_lines
            ]

        return dimensions

    @staticmethod
    def _build_metadata(element_data: dict[str, Any], element_type: str, source_index: int) -> dict[str, Any]:
        metadata = {
            "role": "block",
            "source_index": source_index,
            "source_type": element_type,
        }
        for key in ("src", "path", "url", "image_src", "caption", "alt", "alt_text", "alttext", "latex", "mathml", "formula_type"):
            if key in element_data:
                metadata[key] = element_data[key]
        return metadata

    def _add_element_to_container(self, placed_line: PlacedLine, element: DocumentElement) -> None:
        for page in self.layout_result.pages:
            for container in page.containers:
                if container.id == placed_line.container_id:
                    container.add_element(element)
                    return

    def _create_page_from_template(self, template: dict[str, Any], page_num: int) -> Page:
        base_settings = self.template_manager.get_base_settings()
        page_width = template.get("page_width", base_settings.get("page_width", 595.0))
        page_height = template.get("page_height", base_settings.get("page_height", 842.0))
        page = Page(number=page_num, width=page_width, height=page_height)

        layout_type = template.get("layout_type", "single_column")
        margins = template.get("margins", {"top": 50, "bottom": 50, "left": 50, "right": 50})

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
        self.placement_engine.setup_page(new_page)
        return new_page


def layout_wikipedia_json(
    json_path: str | Path,
    template_name: str = "simple_article",
    font_path: str | Path | None = None,
) -> LayoutResult:
    return LayoutEngine(font_path=font_path).layout_document(json_path=json_path, template_name=template_name)
