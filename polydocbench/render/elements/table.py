"""Draw the measured table grid; cell text uses shared text-line elements."""

from reportlab.lib.colors import HexColor
from reportlab.platypus import Table, TableStyle

from .base import BaseElementRenderer


class TableRenderer(BaseElementRenderer):
    def render(self, element):
        if element.get("type") != "table":
            return
        dimensions = element.get("dimensions") or {}
        widths, heights = dimensions.get("column_widths"), dimensions.get("row_heights")
        if not widths or not heights:
            raise ValueError("Table element has no measured grid")
        options = dimensions.get("table_style", {})
        commands = [("SPAN", tuple(span[:2]), tuple(span[2:])) for span in dimensions.get("spans", [])]
        for header in dimensions.get("header_cells", []):
            commands.append(("BACKGROUND", tuple(header[:2]), tuple(header[2:]),
                             HexColor(options.get("header_fill", "#e5eef6"))))
        if not options.get("borderless", False):
            commands.append(("GRID", (0, 0), (-1, -1), float(options.get("grid_width", 0.4)),
                             HexColor(options.get("grid_color", "#9aa5b1"))))
        table = Table([[""] * len(widths) for _ in heights], colWidths=widths, rowHeights=heights,
                      style=TableStyle(commands))
        x, y, width, height = self._get_bbox_coords(element)
        table.wrap(width, height)
        table.drawOn(self.canvas, x, y)
