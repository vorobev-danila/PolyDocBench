from polydocbench.document import DocumentElement, Page
from polydocbench.layout import LayoutResult


def test_canonical_layout_model_matches_legacy_contract():
    page = Page(number=1, width=100, height=100)
    container = page.create_single_column({"top": 10, "bottom": 10, "left": 10, "right": 10})
    bbox = container.place(12)
    element = DocumentElement(
        id="line_1",
        type="text_line",
        content="Hello",
        bbox=bbox,
        dimensions={"font_size": 10},
    )
    container.add_element(element)

    result = LayoutResult()
    result.add_page(page)
    result.add_element(element)
    result.prepare_ground_truth()

    as_dict = result.to_dict()

    assert bbox.as_dict() == {"x": 10, "y": 78, "width": 80, "height": 12, "page": 1}
    assert as_dict["elements"][0]["dimensions"]["font_size"] == 10
    assert result.ground_truth["pages"][0]["containers"][0]["elements"][0]["content"] == "Hello"

