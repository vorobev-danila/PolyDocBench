import json
from pathlib import Path

from polydocbench.layout import LayoutEngine


def test_layout_engine_layouts_parsed_source_json():
    input_path = Path("outputs/test_runs/layout_engine_source.json")
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(
        json.dumps(
            {
                "title": "Tiny article",
                "url": "https://example.test/article",
                "content": [
                    {"type": "paragraph", "text": "This is a short paragraph for layout."},
                    {"type": "heading", "level": 2, "text": "Section", "id": "Section", "content": []},
                    {"type": "paragraph", "text": "Another paragraph after a heading."},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = LayoutEngine(font_path="DejaVu Sans/DejaVuSans.ttf").layout_document(input_path)

    assert len(result.pages) == 1
    assert any(element.type == "text_line" for element in result.elements)
    assert result.ground_truth["metadata"]["page_count"] == 1


def test_layout_engine_uses_graphic_element_dimensions():
    input_path = Path("outputs/test_runs/layout_engine_graphic_source.json")
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(
        json.dumps(
            {
                "title": "Graphic article",
                "url": "https://example.test/graphic",
                "content": [{"type": "image", "width": 180, "height": 90}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = LayoutEngine(font_path="DejaVu Sans/DejaVuSans.ttf").layout_document(input_path)
    image = next(element for element in result.elements if element.type == "image")
    container = result.pages[0].containers[0]

    assert image.bbox.width == 180
    assert image.bbox.height == 90
    assert image.bbox.x == container.x + (container.width - image.bbox.width) / 2


def test_layout_engine_exports_justified_line_dimensions():
    input_path = Path("outputs/test_runs/layout_engine_justified_source.json")
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(
        json.dumps(
            {
                "title": "Justified article",
                "url": "https://example.test/justified",
                "content": [
                    {
                        "type": "paragraph",
                        "text": (
                            "This paragraph has enough words to create multiple lines "
                            "and mark non-final lines as candidates for justified rendering."
                        ),
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = LayoutEngine(font_path="DejaVu Sans/DejaVuSans.ttf").layout_document(input_path)
    justified_lines = [
        element for element in result.elements
        if element.type == "text_line" and element.dimensions.get("justify")
    ]

    assert justified_lines
    line = justified_lines[0]
    assert line.dimensions["target_width"] > line.dimensions["text_width"]
    assert line.bbox.width == line.dimensions["target_width"]


def test_layout_engine_exports_stable_ids_and_reading_order():
    input_path = Path("outputs/test_runs/layout_engine_reading_order_source.json")
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(
        json.dumps(
            {
                "title": "Reading order article",
                "url": "https://example.test/reading-order",
                "content": [
                    {"type": "paragraph", "text": "First paragraph."},
                    {"type": "paragraph", "text": "Second paragraph."},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = LayoutEngine(font_path="DejaVu Sans/DejaVuSans.ttf").layout_document(input_path)
    gt = result.ground_truth

    assert gt["reading_order"]["blocks"] == ["paragraph_0001", "paragraph_0002"]
    assert gt["elements"][0]["id"] == "paragraph_0001"
    assert gt["elements"][0]["metadata"]["role"] == "block"
    first_line = next(element for element in gt["elements"] if element["metadata"].get("role") == "line")
    assert first_line["id"].startswith("paragraph_0001_line_")
    assert first_line["metadata"]["parent_id"] == "paragraph_0001"


def test_layout_engine_preserves_formula_image_metadata():
    input_path = Path("outputs/test_runs/layout_engine_formula_source.json")
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(
        json.dumps(
            {
                "title": "Formula article",
                "url": "https://example.test/formula",
                "content": [
                    {
                        "type": "formula",
                        "image_src": "outputs/test_runs/formula.png",
                        "latex": "a+b",
                        "formula_type": "display",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = LayoutEngine(font_path="DejaVu Sans/DejaVuSans.ttf").layout_document(input_path)
    formula = next(element for element in result.ground_truth["elements"] if element["type"] == "formula")
    container = result.pages[0].containers[0]

    assert formula["metadata"]["image_src"] == "outputs/test_runs/formula.png"
    assert formula["metadata"]["latex"] == "a+b"
    assert formula["metadata"]["formula_type"] == "display"
    assert formula["bbox"]["x"] == container.x + (container.width - formula["bbox"]["width"]) / 2
