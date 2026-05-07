import json
from pathlib import Path

from PIL import Image

from polydocbench.document import DocumentElement, Page
from polydocbench.render.config import RenderConfig
from polydocbench.layout import LayoutResult
from polydocbench.render.elements import FormulaRenderer
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


def test_pdf_renderer_draws_local_image():
    image_path = Path("outputs/test_runs/image_fixture.png")
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 12), color=(220, 40, 40)).save(image_path)

    page = Page(number=1, width=160, height=140)
    container = page.create_single_column({"top": 10, "bottom": 10, "left": 10, "right": 10})
    element = DocumentElement(
        id="image_1",
        type="image",
        content="",
        bbox=container.place(60),
        dimensions={"line_count": 1},
        metadata={"src": str(image_path), "role": "block"},
    )
    result = LayoutResult(pages=[page], elements=[element])
    result.prepare_ground_truth()

    output_pdf = Path("outputs/test_runs/image_renderer_test.pdf")
    render_result = PDFRenderer(debug=False).render(result, output_pdf)
    pdf_bytes = output_pdf.read_bytes()

    assert Path(render_result["pdf_path"]).exists()
    assert b"/Subtype /Image" in pdf_bytes
    assert json.loads(Path(render_result["gt_path"]).read_text(encoding="utf-8"))["elements"][0]["metadata"]["src"]


def test_pdf_renderer_draws_formula_image_fallback():
    image_path = Path("outputs/test_runs/formula_fixture.png")
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (24, 12), color=(30, 30, 30)).save(image_path)

    page = Page(number=1, width=160, height=140)
    container = page.create_single_column({"top": 10, "bottom": 10, "left": 10, "right": 10})
    element = DocumentElement(
        id="formula_1",
        type="formula",
        content="",
        bbox=container.place(40),
        dimensions={"line_count": 1},
        metadata={"image_src": str(image_path), "latex": "x^2", "role": "block"},
    )
    result = LayoutResult(pages=[page], elements=[element])
    result.prepare_ground_truth()

    output_pdf = Path("outputs/test_runs/formula_renderer_test.pdf")
    render_result = PDFRenderer(debug=False).render(result, output_pdf)
    pdf_bytes = output_pdf.read_bytes()
    gt_element = json.loads(Path(render_result["gt_path"]).read_text(encoding="utf-8"))["elements"][0]

    assert b"/Subtype /Image" in pdf_bytes
    assert gt_element["metadata"]["image_src"] == str(image_path)
    assert gt_element["metadata"]["latex"] == "x^2"


def test_formula_renderer_caches_extensionless_svg_urls(monkeypatch):
    class Response:
        headers = {"content-type": "image/svg+xml"}
        content = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="5"></svg>'

        @staticmethod
        def raise_for_status():
            return None

    monkeypatch.setattr("polydocbench.render.elements.image.requests.get", lambda *args, **kwargs: Response())

    renderer = FormulaRenderer(None, RenderConfig(), None)
    path = renderer._download_to_cache("https://wikimedia.org/api/rest_v1/media/math/render/svg/hash-without-extension")

    assert path is not None
    assert path.suffix == ".svg"
    assert renderer._is_svg_file(path)


def test_formula_renderer_uses_text_fallback_without_image_source():
    renderer = FormulaRenderer(None, RenderConfig(), None)

    assert renderer._get_formula_text({"type": "formula", "metadata": {"latex": "x^2"}}) == "x^2"
    assert renderer._get_formula_text({"type": "formula", "metadata": {"alt_text": "x squared"}}) == "x squared"
