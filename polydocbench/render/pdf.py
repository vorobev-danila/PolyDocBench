"""PDF rendering."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from polydocbench.gt import GroundTruthExporter
from polydocbench.render.config import RenderConfig
from polydocbench.render.debug import DebugRenderer
from polydocbench.render.elements import FormulaRenderer, HeadingRenderer, ImageRenderer, TextRenderer
from polydocbench.render.font_manager import FontManager


class PDFRenderer:
    """Render a LayoutResult into PDF and JSON ground truth."""

    def __init__(self, config_path: str | Path | None = None, debug: bool = True) -> None:
        self.config = RenderConfig(config_path)
        self.debug_mode = debug
        self.font_manager = FontManager(self.config)
        self.font_manager.register_fonts()
        self.gt_exporter = GroundTruthExporter(self.config)
        self.renderer_registry = {
            "text": TextRenderer,
            "text_line": TextRenderer,
            "heading1": HeadingRenderer,
            "heading2": HeadingRenderer,
            "heading3": HeadingRenderer,
            "heading4": HeadingRenderer,
            "heading5": HeadingRenderer,
            "heading6": HeadingRenderer,
            "image": ImageRenderer,
            "formula": FormulaRenderer,
        }
        self.current_page = 1
        self.debug_renderer: DebugRenderer | None = None

    def render(self, layout_result: Any, output_pdf: str | Path = "output/output.pdf") -> dict[str, Any]:
        if not layout_result or not hasattr(layout_result, "to_dict"):
            raise ValueError("layout_result must provide to_dict()")

        output_pdf = Path(output_pdf)
        output_pdf.parent.mkdir(parents=True, exist_ok=True)

        layout_dict = layout_result.to_dict()
        pdf_canvas = canvas.Canvas(str(output_pdf), pagesize=A4)
        self._set_metadata(pdf_canvas)

        if self.debug_mode:
            self.debug_renderer = DebugRenderer(pdf_canvas, self.config)

        elements_by_page = self._group_elements_by_page(layout_dict)
        for page_num in sorted(elements_by_page.keys()):
            if page_num > 1:
                pdf_canvas.showPage()
            self.current_page = page_num
            for element in elements_by_page[page_num]:
                self._render_element(pdf_canvas, element)

        pdf_canvas.save()

        gt_path = output_pdf.with_name(f"{output_pdf.stem}_gt.json")
        self.gt_exporter.export(layout_result, gt_path)

        return {
            "pdf_path": str(output_pdf),
            "gt_path": str(gt_path),
            "page_count": len(elements_by_page),
            "element_count": sum(len(elements) for elements in elements_by_page.values()),
            "render_time": datetime.now().isoformat(),
        }

    def _get_renderer(self, element_type: str, canvas_obj: canvas.Canvas):
        renderer_cls = self.renderer_registry.get(element_type, TextRenderer)
        return renderer_cls(canvas_obj, self.config, self.font_manager)

    def _render_element(self, canvas_obj: canvas.Canvas, element: dict[str, Any]) -> None:
        bbox = element.get("bbox") or {}
        if bbox.get("page", 1) != self.current_page:
            return

        renderer = self._get_renderer(element.get("type", "text"), canvas_obj)
        renderer.render(element)

        if self.debug_mode and self.debug_renderer and bbox:
            self.debug_renderer.render_bbox(
                element,
                bbox.get("x", 0),
                bbox.get("y", 0),
                bbox.get("width", 0),
                bbox.get("height", 0),
            )

    @staticmethod
    def _group_elements_by_page(layout_dict: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
        elements_by_page: dict[int, list[dict[str, Any]]] = {}
        for element in layout_dict.get("elements", []):
            bbox = element.get("bbox") or {}
            page = bbox.get("page", 1)
            elements_by_page.setdefault(page, []).append(element)
        return elements_by_page

    def _set_metadata(self, pdf_canvas: canvas.Canvas) -> None:
        metadata = self.config.get("render.pdf.metadata", {})
        pdf_canvas.setTitle(metadata.get("title", "PolyDocBench PDF"))
        pdf_canvas.setAuthor(metadata.get("author", "PolyDocBench Generator"))
        pdf_canvas.setSubject(metadata.get("subject", "Synthetic OCR benchmark"))
        pdf_canvas.setCreator(metadata.get("creator", "PolyDocBench"))
        pdf_canvas.setProducer(metadata.get("producer", "PolyDocBench"))
        pdf_canvas.setKeywords(metadata.get("keywords", "OCR, document, GT"))


def render_layout_result(layout_result: Any, output_pdf: str | Path = "output/output.pdf", debug: bool = True) -> dict[str, Any]:
    return PDFRenderer(debug=debug).render(layout_result, output_pdf=output_pdf)
