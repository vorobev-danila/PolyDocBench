"""Placement engine orchestration."""

from __future__ import annotations

from typing import Any, Callable, Optional

from polydocbench.document import BBox, Container, Page
from polydocbench.layout.bbox import BBoxCalculator, TextLineInfo
from polydocbench.layout.column_strategy import ColumnStrategy
from polydocbench.layout.handlers import build_default_handlers
from polydocbench.layout.placement_types import PlacedLine, PlacementResult, PlacementStatus
from polydocbench.layout.specs import ElementLayoutSpec
from polydocbench.layout.typography import TypographyStyle


class PlacementEngine:
    """Coordinate element placement across containers, columns, and pages."""

    def __init__(
        self,
        bbox_calculator: BBoxCalculator,
        page_factory: Optional[Callable[[], Page]] = None,
        column_strategy: Optional[ColumnStrategy] = None,
    ) -> None:
        self.bbox_calculator = bbox_calculator
        self.page_factory = page_factory
        self.column_strategy = column_strategy

        self.all_containers: list[Container] = []
        self.current_container: Optional[Container] = None
        self.current_column_index = 0
        self.current_page_number = 1
        self.debug_log: list[str] = []
        self.handlers = build_default_handlers(self)

    def setup_page(self, page: Page) -> None:
        self.current_page_number = page.number
        self.setup_containers(page.containers)
        self.debug_log.append(f"Setup page {page.number}")

    def setup_containers(self, containers: list[Container]) -> None:
        self.all_containers = containers
        for container in containers:
            container.reset()

        self.current_column_index = 0
        self.current_container = containers[0] if containers else None

        if self.column_strategy and containers:
            self.column_strategy.current_column_index = 0

        self.debug_log.append(f"Setup {len(containers)} containers, starting at column 0")

    def prepare_element(
        self,
        element_data: dict[str, Any],
        typography: dict[str, Any],
        layout_type: str = "single_column",
    ) -> PlacementResult:
        element_type = element_data.get("type", "text_line")
        handler = self._get_handler(element_type)
        style = TypographyStyle.from_config(typography)
        return handler.place(element_data, style, layout_type)

    def _get_handler(self, element_type: str):
        return self.handlers.get(element_type, self.handlers["paragraph"])

    def _try_switch_column(self) -> bool:
        if not self.all_containers or len(self.all_containers) <= 1:
            return False

        next_index = self.current_column_index + 1
        if next_index < len(self.all_containers):
            self.current_column_index = next_index
            self.current_container = self.all_containers[next_index]

            if self.column_strategy:
                self.column_strategy.current_column_index = next_index

            self.debug_log.append(f"Switched to next column: {next_index}")
            return True

        self.debug_log.append("Last column reached, need new page")
        return False

    def _create_new_page(self) -> bool:
        if not self.page_factory:
            return False

        new_page = self.page_factory()
        self.setup_page(new_page)

        if self.column_strategy:
            self.column_strategy.reset_for_new_page(new_page.number)

        return True

    def _try_place_line(self, line_info: TextLineInfo) -> PlacementStatus:
        if not self.current_container:
            return PlacementStatus.TOO_LARGE

        if self.current_container.can_fit(line_info.height):
            return PlacementStatus.PLACED
        if len(self.all_containers) > 1:
            return PlacementStatus.NEED_NEW_COLUMN
        if self.page_factory:
            return PlacementStatus.NEED_NEW_PAGE
        return PlacementStatus.TOO_LARGE

    def _create_placed_line(
        self,
        line_info: TextLineInfo,
        line_index: int,
        paragraph_id: str,
        element_type: str,
    ) -> PlacedLine:
        if not self.current_container:
            raise RuntimeError("No container available")

        bbox = self.current_container.place(line_info.height)
        if bbox is None:
            raise RuntimeError("Failed to place line")

        indent = getattr(line_info, "indent", 0)
        bbox.x += indent
        bbox.width = getattr(line_info, "width", bbox.width)

        return PlacedLine(
            text=getattr(line_info, "text", ""),
            bbox=bbox,
            font_size=getattr(line_info, "font_size", 0),
            font_family=getattr(line_info, "font_family", ""),
            is_first_line=getattr(line_info, "is_first_line", True),
            ascent=getattr(line_info, "ascent", 0.8 * line_info.font_size),
            descent=getattr(line_info, "descent", 0.2 * line_info.font_size),
            container_id=self.current_container.id,
            page_number=self.current_page_number,
            line_index=line_index,
            paragraph_id=paragraph_id,
            element_type=element_type,
        )

    def _create_graphic_line(self, spec: ElementLayoutSpec) -> PlacedLine:
        if not self.current_container:
            raise RuntimeError("No container available")

        bbox = self.current_container.place(spec.height)
        if bbox is None:
            raise RuntimeError("Failed to place graphic element")

        bbox.width = spec.width_for_container(self.current_container.width)

        return PlacedLine(
            text="",
            bbox=bbox,
            font_size=0,
            font_family="",
            ascent=0,
            descent=0,
            is_first_line=True,
            container_id=self.current_container.id,
            page_number=self.current_page_number,
            line_index=0,
            element_type=spec.element_type,
        )

    @staticmethod
    def _calculate_paragraph_bbox(placed_lines: list[PlacedLine]) -> Optional[BBox]:
        if not placed_lines:
            return None

        min_x = min(line.bbox.x for line in placed_lines)
        min_y = min(line.bbox.y for line in placed_lines)
        max_x = max(line.bbox.x + line.bbox.width for line in placed_lines)
        max_y = max(line.bbox.y + line.bbox.height for line in placed_lines)
        page = placed_lines[0].bbox.page
        return BBox(x=min_x, y=min_y, width=max_x - min_x, height=max_y - min_y, page=page)

    def get_debug_log(self) -> list[str]:
        return self.debug_log.copy()

    def clear_debug_log(self) -> None:
        self.debug_log.clear()


__all__ = ["PlacedLine", "PlacementEngine", "PlacementResult", "PlacementStatus"]
