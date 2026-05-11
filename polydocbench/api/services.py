"""Application services used by the FastAPI layer."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from polydocbench.eval import evaluate_ordering, extract_gt_lines, load_gt
from polydocbench.eval.quality import evaluate_ocr_quality
from polydocbench.layout import LayoutEngine
from polydocbench.render import PDFRenderer
from polydocbench.sources import WikipediaParser


DEFAULT_API_OUTPUT_DIR = Path("outputs/api")
DEFAULT_FONT_PATH = Path("DejaVu Sans/DejaVuSans.ttf")


def parse_wikipedia_to_file(
    url: str,
    output_path: str | Path | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    parser = WikipediaParser(debug=debug)
    data = parser.parse_from_url(url)
    if "error" in data:
        raise ValueError(str(data["error"]))

    path = Path(output_path) if output_path else _default_output_path(data.get("title", "wikipedia"), ".json")
    parser.save_to_file(data, path)
    return {
        "title": data.get("title", ""),
        "url": data.get("url", url),
        "content_items": len(data.get("content", [])),
        "output_path": str(path),
        "data": data,
    }


def render_document(
    json_path: str | Path,
    output_pdf: str | Path | None = None,
    template: str = "simple_article",
    font_path: str | Path | None = DEFAULT_FONT_PATH,
    debug: bool = False,
) -> dict[str, Any]:
    input_path = Path(json_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input JSON was not found: {input_path}")

    pdf_path = Path(output_pdf) if output_pdf else _default_output_path(input_path.stem, ".pdf")
    resolved_font = Path(font_path) if font_path else None
    if resolved_font is not None and not resolved_font.exists():
        resolved_font = None

    layout_result = LayoutEngine(font_path=resolved_font).layout_document(input_path, template_name=template)
    render_result = PDFRenderer(debug=debug).render(layout_result, pdf_path)
    return {
        "pdf_path": render_result["pdf_path"],
        "gt_path": render_result["gt_path"],
        "template": template,
        "page_count": len(layout_result.pages),
        "element_count": len(layout_result.elements),
    }


def degrade_pdf_document(
    pdf_path: str | Path,
    output_dir: str | Path | None = None,
    page_index: int = 0,
    variants: int = 1,
    seed: int = 42,
    dpi: int = 200,
    profiles: list[str] | None = None,
) -> dict[str, Any]:
    input_path = Path(pdf_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input PDF was not found: {input_path}")
    if variants < 1:
        raise ValueError("variants must be at least 1")
    if dpi < 36:
        raise ValueError("dpi must be at least 36")

    target_dir = Path(output_dir) if output_dir else DEFAULT_API_OUTPUT_DIR / f"{_slug(input_path.stem)}_scans"

    try:
        from polydocbench.degradation import pdf_to_noisy_images
    except ImportError as exc:
        raise RuntimeError('Install degradation dependencies with: pip install -e ".[degradation]"') from exc

    result = pdf_to_noisy_images(
        pdf_path=input_path,
        output_dir=target_dir,
        page_index=page_index,
        n_variants=variants,
        seed=seed,
        dpi=dpi,
        profiles=profiles,
    )
    return {
        "pdf_path": str(input_path),
        "output_dir": str(target_dir),
        "page_index": page_index,
        "variants": variants,
        "dpi": dpi,
        **result,
    }


def evaluate_quality_from_gt(
    gt_path: str | Path,
    predicted_lines: list[dict[str, Any]],
    page_number: int = 1,
    iou_threshold: float = 0.3,
) -> dict[str, float]:
    gt_lines = extract_gt_lines(load_gt(gt_path), page_number=page_number)
    return evaluate_ocr_quality(gt_lines, predicted_lines, iou_threshold=iou_threshold)


def evaluate_ordering_from_gt(
    gt_path: str | Path,
    predicted_lines: list[dict[str, Any]],
    page_number: int = 1,
    num_columns: int = 1,
    iou_threshold: float = 0.3,
) -> dict[str, float | int]:
    gt_lines = extract_gt_lines(load_gt(gt_path), page_number=page_number)
    return evaluate_ordering(
        gt_lines,
        predicted_lines,
        num_columns=num_columns,
        iou_threshold=iou_threshold,
    )


def _default_output_path(label: str, suffix: str) -> Path:
    DEFAULT_API_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_API_OUTPUT_DIR / f"{_slug(label)}_{timestamp}{suffix}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "document"
