from polydocbench.eval import parse_docling_structure


def test_parse_docling_structure_reads_top_level_items_and_bbox():
    payload = {
        "pages": {"1": {"size": {"width": 100, "height": 200}}},
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "section_header",
                "text": "Title",
                "prov": [{"page_no": 1, "bbox": {"l": 10, "t": 20, "r": 60, "b": 40, "coord_origin": "TOPLEFT"}}],
            }
        ],
        "tables": [
            {
                "self_ref": "#/tables/0",
                "prov": [{"page_no": 1, "bbox": {"l": 10, "t": 50, "r": 80, "b": 100, "coord_origin": "TOPLEFT"}}],
            }
        ],
        "pictures": [
            {
                "self_ref": "#/pictures/0",
                "prov": [{"page_no": 2, "bbox": {"l": 0, "t": 0, "r": 10, "b": 10, "coord_origin": "TOPLEFT"}}],
            }
        ],
    }

    elements = parse_docling_structure(payload, page_number=1)

    assert [element["type"] for element in elements] == ["heading", "table"]
    assert elements[0]["bbox"] == {"x": 10.0, "y": 20.0, "width": 50.0, "height": 20.0}
    assert elements[0]["text"] == "Title"


def test_parse_docling_structure_converts_bottom_left_origin_when_height_is_available():
    payload = {
        "pages": {"1": {"size": {"height": 200}}},
        "texts": [
            {
                "label": "text",
                "text": "Bottom origin",
                "prov": [{"page_no": 1, "bbox": {"l": 10, "b": 20, "r": 60, "t": 40, "coord_origin": "BOTTOMLEFT"}}],
            }
        ],
    }

    elements = parse_docling_structure(payload, page_number=1)

    assert elements[0]["bbox"]["y"] == 160.0
    assert elements[0]["bbox"]["height"] == 20.0
