"""Compatibility exports for legacy imports."""

from polydocbench.render import PDFRenderer, render_layout_result


def create_simple_pdf(text: str, output_path: str = "output/simple.pdf"):
    class DummyLayoutResult:
        ground_truth = {}

        def to_dict(self):
            return {
                "pages": [{"page_number": 1, "width": 595, "height": 842, "containers": []}],
                "elements": [
                    {
                        "id": "test_1",
                        "type": "text_line",
                        "content": text,
                        "bbox": {"x": 50, "y": 700, "width": 495, "height": 50, "page": 1},
                        "dimensions": {"font_size": 12, "font_name": "Helvetica"},
                    }
                ],
            }

    return PDFRenderer(debug=False).render(DummyLayoutResult(), output_path)


__all__ = ["PDFRenderer", "create_simple_pdf", "render_layout_result"]

