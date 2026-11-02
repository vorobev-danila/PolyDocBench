import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from PIL import Image

from polydocbench.document.schema import validate_source_document
from polydocbench.eval import extract_gt_structure_elements, extract_visible_gt_blocks
from polydocbench.layout import LayoutEngine
from polydocbench.layout.templates import load_layout_templates
from polydocbench.render import PDFRenderer
from polydocbench.sources.wikipedia import WikipediaParser


ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "DejaVu Sans" / "DejaVuSans.ttf"


def layout(tmp_path, content, template="technical_report", small=False):
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"content": content}), encoding="utf-8")
    config = deepcopy(load_layout_templates())
    if small:
        config["templates"][template].update({"page_width": 280, "page_height": 240,
            "margins": {"top": 20, "bottom": 20, "left": 20, "right": 20}})
    config_path = tmp_path / "templates.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return LayoutEngine(config_path, font_path=FONT).layout_document(source, template)


def table(rows=3):
    return {"type": "table", "caption": "Table 1. Controlled data.", "header_rows": 2,
            "rows": [[{"text": "Group", "rowspan": 2, "is_header": True},
                      {"text": "Measurements", "colspan": 2, "is_header": True}],
                     [{"text": "First", "is_header": True}, {"text": "Second", "is_header": True}]] +
                    [[{"text": f"Sample {index:03d}"}, {"text": str(index)}, {"text": ""}]
                     for index in range(rows)]}


def test_parser_retains_table_grid_caption_empty_cells_and_image_dimensions():
    parsed = WikipediaParser().parse_html('''<h1>Test</h1><div class="mw-parser-output">
      <table><caption>Results</caption><tr><th rowspan="2">Name</th><th colspan="2">Values</th></tr>
      <tr><td></td><td>42</td></tr></table>
      <figure><img src="/figure.png" width="400" height="200"><figcaption>Figure caption</figcaption></figure>
      </div>''', url="https://en.wikipedia.org/wiki/Test")
    source_table, image = parsed["content"]
    assert source_table["caption"] == "Results"
    assert source_table["rows"][0][0]["rowspan"] == 2
    assert source_table["rows"][0][1]["colspan"] == 2
    assert source_table["rows"][1][0]["text"] == ""
    assert image["pixel_width"] == 400 and image["pixel_height"] == 200
    assert image["src"] == "https://en.wikipedia.org/figure.png"
    validate_source_document(parsed)


def test_nested_table_rows_do_not_pollute_parent_grid():
    parsed = WikipediaParser().parse_html('''<h1>Test</h1><div class="mw-parser-output">
        <table><tr><td>Outer<table><tr><td>Inner</td></tr></table></td></tr></table></div>''')
    assert len(parsed["content"][0]["rows"]) == 1
    assert parsed["content"][0]["extraction_warnings"]


def test_rowspan_zero_is_limited_to_the_remaining_row_group():
    parsed = WikipediaParser().parse_html('''<h1>Test</h1><div class="mw-parser-output"><table>
        <tbody><tr><td rowspan="0">Group</td><td>A</td></tr><tr><td>B</td></tr></tbody>
        <tbody><tr><td>Next group</td><td>C</td></tr></tbody></table></div>''')
    assert parsed["content"][0]["rows"][0][0]["rowspan"] == 2


def test_parser_extracts_each_gallery_image():
    parsed = WikipediaParser().parse_html('''<h1>Test</h1><div class="mw-parser-output">
        <ul class="gallery"><li><img src="//example.test/one.png"><div class="gallerytext">One</div></li>
        <li><img src="//example.test/two.png"><div class="gallerytext">Two</div></li></ul></div>''')
    assert [item["caption"] for item in parsed["content"]] == ["One", "Two"]


@pytest.mark.parametrize("rows", [[], [[{"text": "invalid", "colspan": 0}]],
    [[{"text": "invalid", "rowspan": 2}]]])
def test_table_validation_rejects_invalid_grids(rows):
    with pytest.raises(ValueError):
        validate_source_document({"content": [{"type": "table", "rows": rows}]})


def test_table_validation_rejects_overlaps_and_nonfinite_weights():
    for item in [
        {"type": "table", "rows": [[{"text": "A"}, {"text": "B", "rowspan": 2}],
                                  [{"text": "Crosses B", "colspan": 2}]]},
        {"type": "table", "rows": [[{"text": "A"}]], "column_weights": [float("inf")]},
    ]:
        with pytest.raises(ValueError):
            validate_source_document({"content": [item]})


def test_table_render_and_gt_share_cells_and_text(tmp_path):
    fitz = pytest.importorskip("fitz")
    result = layout(tmp_path, [table()])
    rendered = PDFRenderer(debug=False).render(result, tmp_path / "table.pdf")
    with fitz.open(rendered["pdf_path"]) as document:
        text = "".join(page.get_text() for page in document)
        assert "Measurements" in text and "Sample 002" in text
    cells = [element for element in result.elements if element.type == "table_cell"]
    assert len(cells) == 13
    assert any(cell.content == "" for cell in cells)
    assert next(cell for cell in cells if cell.content == "Measurements").metadata["colspan"] == 2
    for line in result.elements:
        if line.type == "text_line" and line.metadata.get("owner_type") == "table":
            cell = next(cell for cell in cells if cell.id == line.metadata["parent_id"])
            assert cell.bbox.x <= line.bbox.x <= line.bbox.x + line.bbox.width <= cell.bbox.x + cell.bbox.width + 0.01
            assert cell.bbox.y <= line.bbox.y <= line.bbox.y + line.bbox.height <= cell.bbox.y + cell.bbox.height + 0.01
    structure = extract_gt_structure_elements(result.ground_truth)
    assert [element["type"] for element in structure].count("table") == 1
    assert not any(element["type"] in {"table_cell", "paragraph"} for element in structure)
    assert all("Sample" not in block["text"] for block in extract_visible_gt_blocks(result.ground_truth))


def test_long_table_repeats_headers_and_never_splits_merged_cells(tmp_path):
    result = layout(tmp_path, [table(30)], small=True)
    assert len(result.pages) >= 3
    fragments = [element for element in result.elements if element.type == "table"]
    assert len({element.metadata["table_id"] for element in fragments}) == 1
    for fragment in fragments:
        cells = [element for element in result.elements if element.type == "table_cell" and
                 element.metadata["parent_id"] == fragment.id]
        assert any(cell.content == "Group" and cell.metadata["rowspan"] == 2 for cell in cells)
        assert any(cell.content == "First" for cell in cells)
    source_cells = [element for element in result.elements if element.type == "table_cell" and
                    element.content.startswith("Sample")]
    assert len(source_cells) == 30
    repeated = [element for element in result.elements if element.type == "table_cell" and
                element.metadata["repeated_header"]]
    assert repeated
    assert len({element.id for element in result.elements}) == len(result.elements)


def test_body_rowspan_remains_inside_a_single_fragment(tmp_path):
    source = {"type": "table", "rows": [[{"text": "A", "is_header": True}, {"text": "B", "is_header": True}]]}
    for index in range(25):
        if index in {7, 8}:
            source["rows"].append([{"text": f"Value {index}"}])
        elif index == 6:
            source["rows"].append([{"text": "Merged body", "rowspan": 3}, {"text": f"Value {index}"}])
        else:
            source["rows"].append([{"text": f"Row {index}"}, {"text": f"Value {index}"}])
    result = layout(tmp_path, [source], small=True)
    merged = next(element for element in result.elements if element.type == "table_cell" and element.content == "Merged body")
    parent = next(element for element in result.elements if element.id == merged.metadata["parent_id"])
    assert {7, 8, 9} <= set(parent.metadata["row_indexes"])
    assert parent.bbox.y - 1e-8 <= merged.bbox.y < merged.bbox.y + merged.bbox.height <= parent.bbox.y + parent.bbox.height + 1e-8


def test_multicolumn_full_width_bands_have_correct_ownership_and_order(tmp_path):
    content = [{"type": "paragraph", "text": "Controlled text with several words. " * 15}, table(2),
               {"type": "paragraph", "text": "Text after the wide table. " * 10}]
    result = layout(tmp_path, content, "research_illustrated")
    table_block = next(element for element in result.elements if element.type == "table")
    assert table_block.bbox.width == 511
    for page in result.pages:
        for container in page.containers:
            assert all(element.bbox.page == page.number for element in container.elements)
    table_caption = next(element for element in result.elements if element.type == "caption")
    order = result.ground_truth["reading_order"]["blocks"]
    assert order.index(table_caption.id) < order.index(table_block.id)
    before = [element for element in result.elements if element.type == "text_line" and
              element.metadata.get("source_index") == 1]
    assert len({element.dimensions["container_id"] for element in before}) == 2
    assert all(line.bbox.y >= table_caption.bbox.y + table_caption.bbox.height for line in before)


def test_page_containers_and_paragraph_fragments_are_page_local(tmp_path):
    result = layout(tmp_path, [{"type": "paragraph", "text": "Text across many pages. " * 200}], small=True)
    assert len(result.pages) > 2
    for page in result.pages:
        assert any(container.elements for container in page.containers)
        for container in page.containers:
            for element in container.elements:
                assert element.bbox.page == page.number
                parent = next(block for block in result.elements if block.id == element.metadata["parent_id"])
                assert parent.bbox.page == page.number


def test_figure_uses_actual_aspect_ratio_and_keeps_caption(tmp_path):
    image = tmp_path / "wide.png"
    Image.new("RGB", (400, 100), "red").save(image)
    result = layout(tmp_path, [{"type": "paragraph", "text": "Preface " * 50},
        {"type": "image", "src": "wide.png", "caption": "Figure caption wrapping below the image."}], small=True)
    figure = next(element for element in result.elements if element.type == "image")
    caption = next(element for element in result.elements if element.type == "caption")
    assert figure.bbox.width / figure.bbox.height == pytest.approx(4.0)
    assert figure.bbox.page == caption.bbox.page
    assert caption.bbox.y + caption.bbox.height <= figure.bbox.y
    assert caption.metadata["caption_for"] == figure.id
    fitz = pytest.importorskip("fitz")
    PDFRenderer(debug=False).render(result, tmp_path / "figure.pdf")
    with fitz.open(tmp_path / "figure.pdf") as document:
        page = document[figure.bbox.page - 1]
        pixmap = page.get_pixmap()
        for fraction in (0.1, 0.5, 0.9):
            x = int(figure.bbox.x + fraction * figure.bbox.width)
            y = int(page.rect.height - figure.bbox.y - fraction * figure.bbox.height)
            red, green, blue = pixmap.pixel(x, y)
            assert red > 200 and green < 50 and blue < 50


def test_svg_dimensions_use_viewport_not_just_viewbox(tmp_path):
    from polydocbench.document.assets import image_dimensions

    image = tmp_path / "figure.svg"
    image.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="50mm" viewBox="0 0 100 100"/>',
                     encoding="utf-8")
    width, height = image_dimensions(image)
    assert width / height == 2.0


def test_financial_numeric_alignment_is_reflected_in_text_gt(tmp_path):
    result = layout(tmp_path, [{"type": "table", "rows": [[{"text": "125.5"}, {"text": "Text"}]]}],
                    template="financial_report")
    cell = next(element for element in result.elements if element.type == "table_cell" and element.content == "125.5")
    line = next(element for element in result.elements if element.type == "text_line" and element.content == "125.5")
    assert line.bbox.x + line.bbox.width == pytest.approx(cell.bbox.x + cell.bbox.width - 3)


def test_legacy_profiles_record_missing_assets_instead_of_exporting_phantom_images(tmp_path):
    result = layout(tmp_path, [{"type": "image", "src": "missing.png"}, {"type": "paragraph", "text": "Visible text"}],
                    template="simple_article")
    assert result.warnings and result.ground_truth["metadata"]["layout_warnings"]
    assert not any(element.type == "image" for element in result.elements)


def test_failure_in_a_later_row_is_detected_before_reserving_table_fragments(tmp_path):
    content = table(5)
    content["rows"].append([{"text": "Oversized content " * 1000}])
    result = layout(tmp_path, [content, {"type": "paragraph", "text": "After skipped table"}],
                    template="simple_article", small=True)
    assert len(result.pages) == 1
    assert result.warnings
    assert not any(element.type == "table" for element in result.elements)


@pytest.mark.parametrize("template", ["technical_report", "research_illustrated", "financial_report", "magazine_feature", "reference_sheet"])
def test_new_profiles_render_offline_and_respect_page_bounds(tmp_path, template):
    fitz = pytest.importorskip("fitz")
    result = LayoutEngine(font_path=FONT).layout_document(ROOT / "examples/complex_document.json", template)
    assert not result.warnings
    output = tmp_path / f"{template}.pdf"
    PDFRenderer(debug=False).render(result, output)
    with fitz.open(output) as document:
        assert len(document) == len(result.pages)
        for page, plan in zip(document, result.pages):
            assert page.rect.width == plan.width and page.rect.height == plan.height
            assert page.get_text().strip()
    for element in result.elements:
        page = result.pages[element.bbox.page - 1]
        assert 0 <= element.bbox.x <= element.bbox.x + element.bbox.width <= page.width + 0.01
        assert 0 <= element.bbox.y <= element.bbox.y + element.bbox.height <= page.height + 0.01


@pytest.mark.parametrize("element", [
    {"type": "table", "rows": [[{"text": "Too much text " * 1000}]]},
    {"type": "formula", "height": 10000},
    {"type": "heading", "text": "Too large heading " * 1000},
    {"type": "image", "src": "missing-image.png"},
])
def test_impossible_elements_fail_explicitly_without_recursion(tmp_path, element):
    with pytest.raises(ValueError):
        layout(tmp_path, [element], small=True)


def test_rotated_table_gt_transforms_cells_and_filters_page_order(tmp_path):
    pytest.importorskip("cv2")
    pytest.importorskip("fitz")
    from polydocbench.noise import pdf_to_noisy_dataset

    result = layout(tmp_path, [table(20)], small=True)
    rendered = PDFRenderer(debug=False).render(result, tmp_path / "table.pdf")
    noisy = pdf_to_noisy_dataset(rendered["pdf_path"], rendered["gt_path"], tmp_path / "noisy",
                                page_index=1, dpi=72, profiles=["medium_scan"], n_variants=1)
    gt = json.loads(Path(noisy["artifacts"][0]["gt_path"]).read_text(encoding="utf-8"))
    cells = [element for element in gt["elements"] if element["type"] == "table_cell"]
    assert cells and all(len(cell["polygon"]) == 4 for cell in cells)
    assert any(cell["metadata"]["repeated_header"] for cell in cells)
    ids = {element["id"] for element in gt["elements"]}
    assert set(gt["reading_order"]["lines"]) <= ids
    assert set(gt["reading_order"]["blocks"]) <= ids
    assert all(element["bbox"]["page"] == 1 for element in gt["elements"])
    cell = cells[0]
    source_box = cell["metadata"]["source_bbox"]
    x, y = source_box["x"], 240 - source_box["y"] - source_box["height"]
    matrix = gt["metadata"]["transform"]["matrix"]
    expected = [matrix[0][0] * x + matrix[0][1] * y + matrix[0][2],
                matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]]
    assert cell["polygon"][0] == pytest.approx(expected)
