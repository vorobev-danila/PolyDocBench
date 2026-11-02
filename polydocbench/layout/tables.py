"""ReportLab-backed table measurement and page-fragment placement."""

from __future__ import annotations

from dataclasses import dataclass
import math

from reportlab.platypus import Flowable, Table, TableStyle

from polydocbench.document import BBox, DocumentElement
from polydocbench.document.tables import TableData, validate_table
from polydocbench.layout.compound import caption_lines, make_caption
from polydocbench.layout.placement_types import PlacementResult


def automatic_column_widths(data, width, calculator, font_size, padding):
    """Allocate space to text-heavy columns without letting one outlier dominate."""
    cells, count = data.grid()
    samples = [[] for _ in range(count)]
    headers = [0.0] * count
    minimum = [2 * padding + font_size] * count
    word_minimum = list(minimum)
    for item in cells:
        if item.cell.colspan != 1:
            continue
        measured = calculator.measure_text_width(item.cell.text, font_size) + 2 * padding
        samples[item.column].append(measured)
        if item.cell.is_header:
            headers[item.column] = max(headers[item.column], measured)
        for character in set(item.cell.text):
            minimum[item.column] = max(minimum[item.column],
                calculator.measure_text_width(character, font_size) + 2 * padding)
        for word in item.cell.text.split():
            word_minimum[item.column] = max(word_minimum[item.column],
                min(calculator.measure_text_width(word, font_size), font_size * 6) + 2 * padding)
    if sum(minimum) > width:
        raise ValueError("Too many table columns for this width/font; use landscape or reduce padding/font size")
    word_minimum = [max(a, b) for a, b in zip(minimum, word_minimum)]
    if sum(word_minimum) > width:
        fraction = (width - sum(minimum)) / (sum(word_minimum) - sum(minimum))
        minimum = [a + fraction * (b - a) for a, b in zip(minimum, word_minimum)]
    else:
        minimum = word_minimum
    preferred = []
    for index, values in enumerate(samples):
        ordered = sorted(values)
        typical = ordered[int((len(ordered) - 1) * 0.75)] if ordered else minimum[index]
        preferred.append(max(minimum[index], min(width * 0.55, max(typical, headers[index]))))
    extra = max(0.0, width - sum(minimum))
    needs = [preferred[index] - minimum[index] for index in range(count)]
    total = sum(needs)
    if total > extra:
        return [minimum[index] + extra * needs[index] / total for index in range(count)]
    remaining = width - sum(preferred)
    return [value + remaining * value / sum(preferred) for value in preferred]


class _CellContent(Flowable):
    def __init__(self, calculator, text: str, font_size: float):
        super().__init__()
        self.calculator, self.text, self.font_size = calculator, text, font_size

    def wrap(self, available_width, available_height):
        if available_width <= 0:
            raise ValueError("Table columns are too narrow for cell padding")
        lines = caption_lines(self, self.text, available_width, self.font_size)
        return available_width, sum(line.height for line in lines) or self.font_size * 1.2

    @property
    def bbox_calculator(self):
        return self.calculator


@dataclass
class TablePlan:
    data: TableData
    widths: list[float]
    heights: list[float]
    padding: float
    font_size: float

    @classmethod
    def measure(cls, data, width, calculator, options):
        cells, column_count = data.grid()
        padding = float(options.get("cell_padding", 4))
        font_size = float(options.get("font_size", 8))
        if not math.isfinite(padding) or not math.isfinite(font_size) or padding < 0 or font_size <= 0:
            raise ValueError("Table padding must be nonnegative and font size positive")
        if data.column_weights is None and options.get("auto_column_widths", True):
            widths = automatic_column_widths(data, width, calculator, font_size, padding)
        else:
            weights = data.column_weights or [1.0] * column_count
            widths = [width * weight / sum(weights) for weight in weights]
        grid = [[""] * column_count for _ in data.rows]
        commands = [("LEFTPADDING", (0, 0), (-1, -1), padding),
                    ("RIGHTPADDING", (0, 0), (-1, -1), padding),
                    ("TOPPADDING", (0, 0), (-1, -1), padding),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), padding)]
        for item in cells:
            grid[item.row][item.column] = _CellContent(calculator, item.cell.text, font_size)
            if item.cell.rowspan > 1 or item.cell.colspan > 1:
                commands.append(("SPAN", (item.column, item.row),
                                 (item.column + item.cell.colspan - 1, item.row + item.cell.rowspan - 1)))
        table = Table(grid, colWidths=widths, style=TableStyle(commands))
        table.wrap(width, 1e9)
        # Isolate ReportLab's calculated row sizes; PDF and GT share this plan.
        heights = list(table._rowHeights)
        if len(heights) != len(data.rows) or any(value is None or value <= 0 for value in heights):
            raise ValueError("ReportLab could not determine positive table row heights")
        return cls(data, widths, heights, padding, font_size)


class TablePlacementHandler:
    def __init__(self, context):
        self.context = context

    def place(self, element_data, typography, layout_type):
        context = self.context
        if context.current_container is None:
            return PlacementResult(False, message="No container for table")
        options = context.options.get("tables", {})
        data = validate_table(element_data)
        plan = TablePlan.measure(data, context.current_container.width, context.bbox_calculator, options)
        cells, _ = data.grid()
        header_count = data.repeated_header_count() if options.get("repeat_headers", True) else 0
        root_id = element_data["_layout_id"]
        source_index = element_data["_source_index"]
        result = PlacementResult(True)
        start = fragment_index = 0
        legal_breaks = [boundary for boundary in range(1, len(data.rows) + 1)
                        if not any(item.row < boundary < item.row + item.cell.rowspan for item in cells)]
        first_lines = caption_lines(context, data.caption, sum(plan.widths), typography.body_size)
        first_reserve = sum(line.height for line in first_lines) + (6 if first_lines else 0)
        first_end = next(end for end in legal_breaks if end > header_count or end == len(data.rows))
        if first_reserve + sum(plan.heights[:first_end]) > context.full_page_height:
            raise ValueError("Table caption/header and first row group cannot fit on a page")
        boundaries = [0] + legal_breaks
        for begin, end in zip(boundaries, boundaries[1:]):
            repeated_height = sum(plan.heights[:header_count]) if begin >= header_count and header_count else 0
            if repeated_height + sum(plan.heights[begin:end]) > context.full_page_height:
                raise ValueError("A table row/merged row group is taller than a page")
        while start < len(data.rows):
            repeated = list(range(header_count)) if start else []
            caption = data.caption if not fragment_index else ""
            lines = caption_lines(context, caption, sum(plan.widths), typography.body_size)
            caption_height = sum(line.height for line in lines)
            gap = 6 if lines else 0
            reserve = caption_height + gap
            candidates = [end for end in legal_breaks if end > start and
                          (end > header_count or end == len(data.rows))]
            fits = [end for end in candidates if reserve + sum(plan.heights[row] for row in
                    repeated + list(range(start, end))) <= context.current_container.available_height]
            if not fits:
                minimum = reserve + sum(plan.heights[row] for row in repeated + list(range(start, candidates[0])))
                if minimum > context.full_page_height:
                    raise ValueError("A table row/merged row group is taller than a page; reduce font/padding or split the source table")
                if context._try_switch_column() or context._create_new_page():
                    continue
                raise ValueError("No space for table fragment")
            end = max(fits)
            row_indexes = repeated + list(range(start, end))
            fragment_id = root_id if not fragment_index else f"{root_id}_fragment_{fragment_index + 1:03d}"
            container = context.current_container
            top = container.cursor_y
            result.elements.extend(make_caption(context, caption, lines, top, container.x,
                                   sum(plan.widths), f"{fragment_id}_caption", fragment_id, source_index))
            if reserve:
                container.place(reserve)
            bbox = container.place(sum(plan.heights[row] for row in row_indexes))
            metadata = {"role": "block", "table_id": root_id, "source_index": source_index,
                        "fragment_index": fragment_index, "container_id": container.id,
                        "row_indexes": row_indexes, "repeated_header_rows": len(repeated),
                        "extraction_warnings": element_data.get("extraction_warnings", [])}
            result.elements.append(DocumentElement(
                id=fragment_id, type="table", bbox=bbox,
                content={"rows": [[cell.model_dump() for cell in data.rows[row]] for row in row_indexes]},
                dimensions={"column_widths": plan.widths, "row_heights": [plan.heights[row] for row in row_indexes],
                            "spans": [], "header_cells": [], "table_style": options}, metadata=metadata,
            ))
            table_element = result.elements[-1]
            local_rows = {row: index for index, row in enumerate(row_indexes)}
            for item in cells:
                if item.row not in local_rows:
                    continue
                row, column, cell = local_rows[item.row], item.column, item.cell
                cell_id = f"{fragment_id}_cell_{item.row:04d}_{column:04d}"
                cell_top = bbox.y + bbox.height - sum(plan.heights[index] for index in row_indexes[:row])
                cell_box = BBox(bbox.x + sum(plan.widths[:column]),
                                cell_top - sum(plan.heights[item.row:item.row + cell.rowspan]),
                                sum(plan.widths[column:column + cell.colspan]),
                                sum(plan.heights[item.row:item.row + cell.rowspan]), bbox.page)
                if cell.rowspan > 1 or cell.colspan > 1:
                    table_element.dimensions["spans"].append([column, row, column + cell.colspan - 1, row + cell.rowspan - 1])
                if cell.is_header:
                    table_element.dimensions["header_cells"].append([column, row, column + cell.colspan - 1, row + cell.rowspan - 1])
                cell_metadata = {"role": "cell", "parent_id": fragment_id, "table_id": root_id,
                                 "source_cell_id": f"{root_id}_cell_{item.row:04d}_{column:04d}",
                                 "row_index": item.row, "column_index": column, "rowspan": cell.rowspan,
                                 "colspan": cell.colspan, "is_header": cell.is_header,
                                 "scope": cell.scope,
                                 "repeated_header": item.row in repeated, "owner_type": "table",
                                 "container_id": container.id, "source_index": source_index}
                result.elements.append(DocumentElement(id=cell_id, type="table_cell", content=cell.text,
                                                       bbox=cell_box, metadata=cell_metadata))
                text_lines = caption_lines(context, cell.text, cell_box.width - 2 * plan.padding, plan.font_size)
                y = cell_top - plan.padding
                for index, line in enumerate(text_lines, 1):
                    y -= line.height
                    alignment = cell.align
                    if alignment is None and not cell.is_header:
                        try:
                            float(cell.text.replace(",", "").rstrip("%"))
                            alignment = options.get("numeric_alignment", "left")
                        except ValueError:
                            pass
                    extra = max(0, cell_box.width - 2 * plan.padding - line.width)
                    offset = extra if alignment == "right" else extra / 2 if alignment == "center" else 0
                    result.elements.append(DocumentElement(
                        id=f"{cell_id}_line_{index:04d}", type="text_line", content=line.text,
                        bbox=BBox(cell_box.x + plan.padding + offset, y, line.width, line.height, bbox.page),
                        dimensions={"font_family": line.font_family, "font_size": line.font_size,
                                    "ascent": line.ascent, "descent": line.descent},
                        metadata={**cell_metadata, "role": "line", "parent_id": cell_id, "line_index": index},
                    ))
            start = end
            fragment_index += 1
            if start < len(data.rows) and not (context._try_switch_column() or context._create_new_page()):
                raise ValueError("Cannot create another table fragment")
        if context.current_container.can_fit(typography.paragraph_spacing):
            context.current_container.place(typography.paragraph_spacing)
        return result
