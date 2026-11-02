"""Placement engine orchestration."""

from __future__ import annotations

from typing import Any, Callable, Optional
from pathlib import Path

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
        self.options: dict[str, Any] = {}
        self.span_active = False
        self.page: Page | None = None
        self.flow_columns: list[Container] = []
        self.full_page_height = 0.0
        self.source_dir = Path.cwd()

    def setup_page(self, page: Page) -> None:
        self.page = page
        self.flow_columns = list(page.containers)
        self.full_page_height = max((container.height for container in self.flow_columns), default=0.0)
        self.current_page_number = page.number
        self.setup_containers(page.containers)
        if self.span_active:
            self._begin_span_region()
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
        config = self.options.get("tables" if element_type == "table" else "images", {})
        span = element_data.get("span_columns", config.get("span_columns"))
        use_span = element_type in {"table", "image"} and span == "all" and len(self.flow_columns) > 1
        if use_span:
            self.span_active = True
            self._begin_span_region()
        try:
            return handler.place(element_data, style, layout_type)
        finally:
            if use_span:
                self._finish_span_region()
                self.span_active = False

    def _begin_span_region(self) -> None:
        assert self.page is not None
        columns = self.all_containers
        bottom = min(container.y for container in self.flow_columns)
        top = min(container.cursor_y for container in columns)
        left = min(container.x for container in columns)
        right = max(container.x + container.width for container in columns)
        container = Container(
            id=f"span_{len(self.page.containers)}", x=left, y=bottom,
            width=right - left, height=max(0.0, top - bottom), page=self.page.number,
            type="full_width",
        )
        self.page.add_container(container)
        self.all_containers = [container]
        self.current_container = container
        self.current_column_index = 0

    def balance_text_band(self, heights: list[float]) -> None:
        """Reserve a compact column band before a full-width insertion."""
        columns = self.all_containers
        if len(columns) < 2 or not heights or any(column.elements for column in columns):
            return
        available = min(column.available_height for column in columns)
        if sum(heights) > available * len(columns):
            return
        low, high = max(heights), sum(heights)
        for _ in range(40):
            middle = (low + high) / 2
            used, filled = 1, 0.0
            for height in heights:
                if filled + height > middle:
                    used, filled = used + 1, 0.0
                filled += height
            if used <= len(columns):
                high = middle
            else:
                low = middle
        height = min(available, high + 0.01)
        band = [Container(id=f"balanced_{len(self.page.containers)}_{index}", x=column.x,
                          y=column.cursor_y - height, width=column.width, height=height,
                          type=column.type, page=self.page.number) for index, column in enumerate(columns)]
        for column in band:
            self.page.add_container(column)
        self.all_containers = band
        self.current_container = band[0]
        self.current_column_index = 0

    def _finish_span_region(self) -> None:
        assert self.page is not None and self.current_container is not None
        top = self.current_container.cursor_y
        columns = [Container(
            id=f"region_{len(self.page.containers)}_column_{index + 1}",
            x=original.x, y=original.y, width=original.width,
            height=max(0.0, top - original.y), type=original.type, page=self.page.number,
        ) for index, original in enumerate(self.flow_columns)]
        for column in columns:
            self.page.add_container(column)
        self.all_containers = columns
        self.current_container = columns[0]
        self.current_column_index = 0

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
        if line_info.height > self.full_page_height:
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
        text_width = getattr(line_info, "width", bbox.width)
        target_width = getattr(line_info, "target_width", text_width) or text_width
        justify = bool(getattr(line_info, "justify", False))
        bbox.x += indent
        bbox.width = target_width if justify else text_width

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
            text_width=text_width,
            target_width=target_width,
            justify=justify,
        )

    def _create_graphic_line(self, spec: ElementLayoutSpec) -> PlacedLine:
        if not self.current_container:
            raise RuntimeError("No container available")

        bbox = self.current_container.place(spec.height)
        if bbox is None:
            raise RuntimeError("Failed to place graphic element")

        bbox.width = spec.width_for_container(self.current_container.width)
        bbox.x = self.current_container.x + (self.current_container.width - bbox.width) / 2

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
            text_width=0,
            target_width=bbox.width,
            justify=False,
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
