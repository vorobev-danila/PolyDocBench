"""Element placement handlers."""

from __future__ import annotations

from typing import Any, Protocol

from polydocbench.layout.bbox import TextLineInfo
from polydocbench.layout.placement_types import PlacedLine, PlacementResult, PlacementStatus
from polydocbench.layout.specs import ElementLayoutSpec
from polydocbench.layout.typography import TypographyStyle


class PlacementContext(Protocol):
    bbox_calculator: Any
    current_container: Any
    current_page_number: int

    def _try_place_line(self, line_info: TextLineInfo) -> PlacementStatus: ...

    def _try_switch_column(self) -> bool: ...

    def _create_new_page(self) -> bool: ...

    def _create_placed_line(self, line_info: TextLineInfo, line_index: int, paragraph_id: str, element_type: str) -> PlacedLine: ...

    def _create_graphic_line(self, spec: ElementLayoutSpec) -> PlacedLine: ...

    def _calculate_paragraph_bbox(self, placed_lines: list[PlacedLine]): ...


class BasePlacementHandler:
    def __init__(self, context: PlacementContext) -> None:
        self.context = context

    def place(self, element_data: dict[str, Any], typography: TypographyStyle, layout_type: str) -> PlacementResult:
        raise NotImplementedError


class TextPlacementHandler(BasePlacementHandler):
    def place(self, element_data: dict[str, Any], typography: TypographyStyle, layout_type: str) -> PlacementResult:
        text = element_data.get("content", "")
        paragraph_spacing = typography.paragraph_spacing
        para_id = f"para_{id(element_data)}"
        result = PlacementResult(success=False)

        if not self.context.current_container:
            result.message = "No container available"
            return result

        lines_info: list[TextLineInfo] = self.context.bbox_calculator.split_into_lines(
            text=text,
            max_width=self.context.current_container.width,
            font_size=typography.body_size,
            line_height_ratio=typography.line_height,
            first_line_indent=typography.first_line_indent,
        )

        if not lines_info:
            result.message = "No lines generated"
            return result

        lines_to_place = lines_info.copy()
        while lines_to_place:
            line_info = lines_to_place[0]
            status = self.context._try_place_line(line_info)

            if status == PlacementStatus.PLACED:
                placed_line = self.context._create_placed_line(line_info, len(result.placed_lines), para_id, "text_line")
                result.add_line(placed_line)
                lines_to_place.pop(0)
            elif status == PlacementStatus.NEED_NEW_COLUMN:
                if self.context._try_switch_column():
                    continue
                if not self.context._create_new_page():
                    result.message = "Cannot create new page for remaining lines"
                    break
            elif status == PlacementStatus.NEED_NEW_PAGE:
                if not self.context._create_new_page():
                    result.message = "Cannot create new page"
                    break
            else:
                result.message = f"Line too tall: {line_info.height:.1f}pt"
                break

        if result.placed_lines:
            result.success = True
            result.paragraph_bbox = self.context._calculate_paragraph_bbox(result.placed_lines)
            if self.context.current_container and paragraph_spacing > 0 and self.context.current_container.can_fit(paragraph_spacing):
                self.context.current_container.place(paragraph_spacing)

        return result


class HeadingPlacementHandler(BasePlacementHandler):
    def place(self, element_data: dict[str, Any], typography: TypographyStyle, layout_type: str) -> PlacementResult:
        text = element_data.get("content", "")
        elem_type = element_data.get("type", "heading1")
        font_size = typography.heading_size(elem_type)
        result = PlacementResult(success=False)

        if not self.context.current_container:
            result.message = "No container"
            return result

        lines_info = self.context.bbox_calculator.split_heading_into_lines(
            text=text,
            max_width=self.context.current_container.width,
            font_size=font_size,
            line_height_ratio=typography.line_height,
        )

        if not lines_info:
            result.message = "Empty heading"
            return result

        total_height = sum(line.height for line in lines_info)
        if not self.context.current_container.can_fit(total_height):
            if self.context._try_switch_column():
                return self.place(element_data, typography, layout_type)
            if self.context._create_new_page():
                return self.place(element_data, typography, layout_type)
            result.message = "Heading does not fit entirely"
            return result

        para_id = f"heading_{id(element_data)}"
        for line_index, line_info in enumerate(lines_info):
            bbox = self.context.current_container.place(line_info.height)
            placed_line = PlacedLine(
                text=line_info.text,
                bbox=bbox,
                font_size=font_size,
                font_family=typography.font_family,
                ascent=line_info.ascent,
                descent=line_info.descent,
                is_first_line=(line_index == 0),
                container_id=self.context.current_container.id,
                page_number=self.context.current_page_number,
                line_index=line_index,
                paragraph_id=para_id,
                element_type=elem_type,
            )
            result.add_line(placed_line)

        result.success = True
        result.paragraph_bbox = self.context._calculate_paragraph_bbox(result.placed_lines)
        return result


class GraphicPlacementHandler(BasePlacementHandler):
    def place(self, element_data: dict[str, Any], typography: TypographyStyle, layout_type: str) -> PlacementResult:
        spec = ElementLayoutSpec.from_element(element_data)
        result = PlacementResult(success=False)

        if not self.context.current_container:
            result.message = "No container"
            return result

        if self.context.current_container.can_fit(spec.height):
            placed_line = self.context._create_graphic_line(spec)
            result.add_line(placed_line)
            result.success = True
            result.paragraph_bbox = placed_line.bbox
        elif self.context._try_switch_column() or self.context._create_new_page():
            return self.place(element_data, typography, layout_type)
        else:
            result.message = "Element too large"

        return result


def build_default_handlers(context: PlacementContext) -> dict[str, BasePlacementHandler]:
    text = TextPlacementHandler(context)
    heading = HeadingPlacementHandler(context)
    graphic = GraphicPlacementHandler(context)

    return {
        "paragraph": text,
        "text": text,
        "text_line": text,
        "heading1": heading,
        "heading2": heading,
        "heading3": heading,
        "heading4": heading,
        "heading5": heading,
        "image": graphic,
        "formula": graphic,
        "table": graphic,
    }
