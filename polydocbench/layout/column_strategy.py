"""Column navigation strategy."""

from __future__ import annotations

from polydocbench.document import Container


class ColumnStrategy:
    """Sequential column-filling strategy."""

    def __init__(self) -> None:
        self.current_column_index = 0
        self.page_column_starts: dict[int, int] = {}

    def select_column(self, element_data, containers: list[Container], current_index: int) -> int:
        return current_index

    def find_alternative_column(
        self,
        element_height: float,
        current_index: int,
        containers: list[Container],
    ) -> int | None:
        for index in range(current_index + 1, len(containers)):
            if containers[index].can_fit(element_height):
                return index
        return None

    def reset_for_new_page(self, page_num: int) -> None:
        self.current_column_index = 0
        self.page_column_starts[page_num] = 0
        print(f"   Page {page_num}: starting at column 0")

    def switch_to_next_column(self, containers: list[Container]) -> bool:
        if not containers or self.current_column_index >= len(containers) - 1:
            return False

        self.current_column_index += 1
        print(f"   Switched to column {self.current_column_index}")
        return True

