"""FastAPI application for PolyDocBench workflows."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from polydocbench.api.services import (
    evaluate_ordering_from_gt,
    evaluate_quality_from_gt,
    noise_pdf_document,
    noise_pdf_with_gt_document,
    parse_wikipedia_to_file,
    render_document,
)
from polydocbench.noise import NOISE_PROFILES
from polydocbench.layout.templates import list_template_names


app = FastAPI(
    title="PolyDocBench API",
    version="0.1.0",
    description="API for Wikipedia parsing, synthetic document rendering, scan noising, and OCR/layout evaluation.",
)


class ParseWikipediaRequest(BaseModel):
    url: str
    output_path: str | None = None
    debug: bool = False


class RenderRequest(BaseModel):
    json_path: str
    output_pdf: str | None = None
    template: str = "simple_article"
    font_path: str | None = "DejaVu Sans/DejaVuSans.ttf"
    debug: bool = False


class NoisePdfRequest(BaseModel):
    pdf_path: str
    output_dir: str | None = None
    page_index: int = 0
    variants: int = 1
    seed: int = 42
    dpi: int = 200
    profiles: list[str] | None = None


class NoisePdfWithGtRequest(NoisePdfRequest):
    gt_path: str


class BBoxPayload(BaseModel):
    x: float
    y: float
    width: float
    height: float


class PredictedLinePayload(BaseModel):
    id: str = ""
    text: str = ""
    bbox: BBoxPayload
    confidence: float | None = None
    page_number: int | None = None

    def as_line_dict(self) -> dict[str, Any]:
        data = self.dict(exclude_none=True)
        data["bbox"] = self.bbox.dict()
        return data


class QualityEvaluationRequest(BaseModel):
    gt_path: str
    predicted_lines: list[PredictedLinePayload] = Field(default_factory=list)
    page_number: int = 1
    iou_threshold: float = 0.3


class OrderingEvaluationRequest(QualityEvaluationRequest):
    num_columns: int = 1


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/templates")
def templates() -> dict[str, list[str]]:
    return {"templates": list_template_names()}


@app.get("/noise/profiles")
def noise_profiles() -> dict[str, list[str]]:
    return {"profiles": list(NOISE_PROFILES)}


@app.post("/parse/wikipedia")
def parse_wikipedia(request: ParseWikipediaRequest) -> dict[str, Any]:
    try:
        return parse_wikipedia_to_file(
            url=request.url,
            output_path=request.output_path,
            debug=request.debug,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/render")
def render(request: RenderRequest) -> dict[str, Any]:
    try:
        return render_document(
            json_path=request.json_path,
            output_pdf=request.output_pdf,
            template=request.template,
            font_path=request.font_path,
            debug=request.debug,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/noise/pdf")
def noise_pdf(request: NoisePdfRequest) -> dict[str, Any]:
    try:
        return noise_pdf_document(
            pdf_path=request.pdf_path,
            output_dir=request.output_dir,
            page_index=request.page_index,
            variants=request.variants,
            seed=request.seed,
            dpi=request.dpi,
            profiles=request.profiles,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/noise/pdf-with-gt")
def noise_pdf_with_gt(request: NoisePdfWithGtRequest) -> dict[str, Any]:
    try:
        return noise_pdf_with_gt_document(
            pdf_path=request.pdf_path,
            gt_path=request.gt_path,
            output_dir=request.output_dir,
            page_index=request.page_index,
            variants=request.variants,
            seed=request.seed,
            dpi=request.dpi,
            profiles=request.profiles,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/evaluate/quality")
def evaluate_quality(request: QualityEvaluationRequest) -> dict[str, float]:
    try:
        return evaluate_quality_from_gt(
            gt_path=request.gt_path,
            predicted_lines=[line.as_line_dict() for line in request.predicted_lines],
            page_number=request.page_number,
            iou_threshold=request.iou_threshold,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/evaluate/ordering")
def evaluate_reading_order(request: OrderingEvaluationRequest) -> dict[str, float | int]:
    try:
        return evaluate_ordering_from_gt(
            gt_path=request.gt_path,
            predicted_lines=[line.as_line_dict() for line in request.predicted_lines],
            page_number=request.page_number,
            num_columns=request.num_columns,
            iou_threshold=request.iou_threshold,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def run() -> None:
    import uvicorn

    uvicorn.run("polydocbench.api.app:app", host="127.0.0.1", port=8000, reload=True)
