"""Validated table content and a non-overlapping logical cell grid."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TableCell(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str = ""
    is_header: bool = False
    rowspan: int = Field(default=1, ge=1, le=1000)
    colspan: int = Field(default=1, ge=1, le=1000)
    align: Literal["left", "center", "right"] | None = None
    scope: Literal["row", "col", "rowgroup", "colgroup"] | None = None


class TableData(BaseModel):
    model_config = ConfigDict(extra="allow")

    rows: list[list[TableCell]] = Field(min_length=1, max_length=10000)
    caption: str = ""
    header_rows: int | None = Field(default=None, ge=0)
    column_weights: list[float] | None = None

    @model_validator(mode="after")
    def validate_grid(self) -> "TableData":
        cells, columns = self.grid()
        if not cells:
            raise ValueError("table requires at least one cell")
        if columns > 1000:
            raise ValueError("table has too many columns")
        if self.header_rows is not None and self.header_rows > len(self.rows):
            raise ValueError("header_rows exceeds table row count")
        if self.column_weights is not None:
            import math

            if len(self.column_weights) != columns or any(
                not math.isfinite(value) or value <= 0 for value in self.column_weights
            ):
                raise ValueError("column_weights must contain one finite positive value per column")
        return self

    def grid(self) -> tuple[list["GridCell"], int]:
        occupied: set[tuple[int, int]] = set()
        cells: list[GridCell] = []
        columns = 0
        for row_index, row in enumerate(self.rows):
            column = 0
            for cell in row:
                while (row_index, column) in occupied:
                    column += 1
                if row_index + cell.rowspan > len(self.rows):
                    raise ValueError("rowspan extends beyond the table")
                slots = {(r, c) for r in range(row_index, row_index + cell.rowspan)
                         for c in range(column, column + cell.colspan)}
                if slots & occupied:
                    raise ValueError("table cells overlap")
                occupied.update(slots)
                cells.append(GridCell(row_index, column, cell))
                column += cell.colspan
                columns = max(columns, column)
        return cells, columns

    def repeated_header_count(self) -> int:
        if self.header_rows is not None:
            count = self.header_rows
        else:
            count = 0
            for row in self.rows:
                headers = [cell for cell in row if cell.is_header]
                if (not headers or any(cell.text.strip() and not cell.is_header for cell in row)
                    or all(cell.scope in {"row", "rowgroup"} for cell in headers)):
                    break
                count += 1
        # Never split a merged cell between a repeated header and the body.
        cells, _ = self.grid()
        while True:
            expanded = max([count] + [cell.row + cell.cell.rowspan for cell in cells if cell.row < count])
            if expanded == count:
                return count
            count = expanded


@dataclass(frozen=True)
class GridCell:
    row: int
    column: int
    cell: TableCell


def validate_table(data: dict[str, Any]) -> TableData:
    return TableData.model_validate(data)
