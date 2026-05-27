from types import SimpleNamespace

from PIL import Image

from polydocbench.eval.dotsocr import DOTSOCR_ORDERING_PROMPT, extract_dotsocr_blocks, parse_dotsocr_blocks_response


def test_parse_dotsocr_blocks_preserves_model_order_and_pixel_bbox():
    blocks = parse_dotsocr_blocks_response(
        '```json\n[{"bbox": [10, 20, 80, 36], "category": "Title", "text": "Heading"},'
        '{"bbox": [10, 40, 95, 75], "category": "Text", "text": "Paragraph"}]\n```'
    )

    assert [block["text"] for block in blocks] == ["Heading", "Paragraph"]
    assert blocks[0]["category"] == "Title"
    assert blocks[0]["bbox"] == {"x": 10.0, "y": 20.0, "width": 70.0, "height": 16.0}


def test_extract_dotsocr_blocks_writes_raw_response(tmp_path):
    image_path = tmp_path / "scan.jpg"
    Image.new("RGB", (100, 80), "white").save(image_path)
    raw_path = tmp_path / "raw.txt"
    content = '[{"bbox": [1, 2, 20, 10], "category": "Text", "text": "paragraph"}]'
    create = lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    blocks = extract_dotsocr_blocks(image_path, client=client, raw_response_path=raw_path)

    assert blocks[0]["text"] == "paragraph"
    assert raw_path.read_text(encoding="utf-8") == content
    assert "semantic blocks" in DOTSOCR_ORDERING_PROMPT


def test_parse_dotsocr_blocks_accepts_ordered_markdown_without_geometry():
    blocks = parse_dotsocr_blocks_response("First paragraph.\n\n## Section\n\nSecond paragraph.")

    assert [block["text"] for block in blocks] == ["First paragraph.", "## Section", "Second paragraph."]
    assert blocks[1]["category"] == "Heading"
    assert blocks[0]["response_format"] == "ordered_text"
    assert "bbox" not in blocks[0]
