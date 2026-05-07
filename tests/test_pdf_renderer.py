import json
from pathlib import Path

from polydocbench.document import DocumentElement, Page
from polydocbench.layout import LayoutResult
from polydocbench.render import PDFRenderer


def test_pdf_renderer_writes_pdf_and_gt():
    page = Page(number=1, width=100, height=100)
    container = page.create_single_column({"top": 10, "bottom": 10, "left": 10, "right": 10})
    element = DocumentElement(
        id="line_1",
        type="text_line",
        content="Hello PDF",
        bbox=container.place(12),
        dimensions={"font_size": 10, "font_name": "Helvetica", "ascent": 8},
    )
    container.add_element(element)

    result = LayoutResult(pages=[page], elements=[element])
    result.prepare_ground_truth()

    output_pdf = Path("outputs/test_runs/pdf_renderer_test.pdf")
    render_result = PDFRenderer(debug=False).render(result, output_pdf)
    gt_path = Path(render_result["gt_path"])

    assert output_pdf.exists()
    assert gt_path.exists()
    assert json.loads(gt_path.read_text(encoding="utf-8"))["elements"][0]["content"] == "Hello PDF"


def test_legacy_root_pdf_renderer_import_still_works():
    from render.pdf_renderer import create_simple_pdf

    output_pdf = Path("outputs/test_runs/legacy_import_pdf_renderer.pdf")
    render_result = create_simple_pdf("Legacy import", str(output_pdf))

    assert output_pdf.exists()
    assert Path(render_result["gt_path"]).exists()
