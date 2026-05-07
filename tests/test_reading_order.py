from polydocbench.document import BBox, DocumentElement
from polydocbench.gt import assign_reading_order
from polydocbench.layout import ElementIdGenerator


def test_element_id_generator_creates_stable_block_and_line_ids():
    generator = ElementIdGenerator()

    block_id = generator.block_id("heading2", 3)

    assert block_id == "heading2_0003"
    assert generator.line_id(block_id, 2) == "heading2_0003_line_002"


def test_assign_reading_order_uses_source_index_for_blocks():
    second = DocumentElement(
        id="paragraph_0002",
        type="paragraph",
        bbox=BBox(x=50, y=700, width=100, height=20, page=1),
        metadata={"role": "block", "source_index": 2},
    )
    first = DocumentElement(
        id="heading2_0001",
        type="heading2",
        bbox=BBox(x=50, y=650, width=100, height=20, page=1),
        metadata={"role": "block", "source_index": 1},
    )

    reading_order = assign_reading_order([second, first])

    assert reading_order["blocks"] == ["heading2_0001", "paragraph_0002"]
    assert first.metadata["reading_order"] == 1
    assert second.metadata["reading_order"] == 2


def test_assign_reading_order_sorts_lines_by_page_column_and_vertical_position():
    right_top = DocumentElement(
        id="right_top",
        type="text_line",
        bbox=BBox(x=300, y=700, width=100, height=10, page=1),
        metadata={"role": "line"},
    )
    left_lower = DocumentElement(
        id="left_lower",
        type="text_line",
        bbox=BBox(x=50, y=650, width=100, height=10, page=1),
        metadata={"role": "line"},
    )
    left_top = DocumentElement(
        id="left_top",
        type="text_line",
        bbox=BBox(x=50, y=700, width=100, height=10, page=1),
        metadata={"role": "line"},
    )

    reading_order = assign_reading_order([right_top, left_lower, left_top])

    assert reading_order["lines"] == ["left_top", "left_lower", "right_top"]
