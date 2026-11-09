"""One persistent model session for a pilot; supervised by pilot_runtime."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from .pilot import PilotPlan


class PilotAdapter:
    def __init__(self, engine: str, config: dict):
        self.engine = engine
        self.config = config
        self.converter = None
        self.client = None

    def predict(self, record, image: Path, raw: Path) -> list:
        if self.engine == "tesseract":
            import pytesseract
            from polydocbench.eval.ocr import extract_tesseract_lines

            pytesseract.pytesseract.tesseract_cmd = self.config["tesseract_cmd"]
            languages = {"en": "eng", "ru": "rus", "fr": "fra", "de": "deu", "es": "spa", "it": "ita"}
            if record.language not in languages:
                raise ValueError(f"No Tesseract language mapping for {record.language}")
            return extract_tesseract_lines(image, page_number=1, lang=languages[record.language],
                                           coordinate_system="image")
        if self.engine == "docling":
            from polydocbench.eval.docling_adapter import extract_docling_structure

            if self.converter is None:
                from docling.document_converter import DocumentConverter

                self.converter = DocumentConverter()
            return extract_docling_structure(image, raw_output_path=raw, page_number=1, converter=self.converter)
        from openai import OpenAI
        from polydocbench.eval.dotsocr import extract_dotsocr_blocks

        if self.client is None:
            token = os.environ.get(self.config["api_key_env"])
            if not token:
                raise RuntimeError("Remote API credential is not configured")
            self.client = OpenAI(api_key=token, base_url=self.config["base_url"],
                                 timeout=self.config["request_timeout"], max_retries=self.config["max_retries"])
        return extract_dotsocr_blocks(image, client=self.client, model=self.config["model"],
                                      prompt=self.config["prompt"], raw_response_path=raw)

    def evaluate(self, record, gt: dict, predictions: list) -> dict:
        if self.config.get("visibility_policy") is not None:
            from polydocbench.eval.scoped import evaluate_with_visibility

            task = {"tesseract": "quality", "docling": "structure", "dotsocr": "ordering"}[self.engine]
            result = evaluate_with_visibility(gt, predictions, task=task, policy=self.config["visibility_policy"],
                                              iou_threshold=self.config["quality_iou"] if task == "quality" else self.config["structure_iou"],
                                              min_similarity=self.config["min_similarity"], max_gt_span=self.config["max_gt_span"])
            self.scope = result.scope
            if self.config.get("evaluation_contract"):
                result.metrics["evaluation_contract_id"] = self.config["evaluation_contract"]["contract_id"]
            return result.metrics
        from polydocbench.eval import (
            evaluate_ocr_quality, evaluate_semantic_ordering, evaluate_structure,
            extract_gt_lines, extract_gt_structure_elements, extract_visible_gt_blocks,
        )

        if self.engine == "tesseract":
            return evaluate_ocr_quality(extract_gt_lines(gt, page_number=1), predictions,
                                         iou_threshold=self.config["quality_iou"])
        if self.engine == "docling":
            return evaluate_structure(extract_gt_structure_elements(gt, page_number=1), predictions,
                                      iou_threshold=self.config["structure_iou"])[0]
        return evaluate_semantic_ordering(extract_visible_gt_blocks(gt, page_number=1), predictions,
                                          min_similarity=self.config["min_similarity"],
                                          max_gt_span=self.config["max_gt_span"])[0]


def run_worker(job: dict, output: Path, adapter=None) -> None:
    plan = PilotPlan.model_validate(job["plan"])
    root = Path(job["input_dir"])
    engine = job["engine"]
    adapter = adapter or PilotAdapter(engine, job["config"])
    predictions_dir = output / "predictions"
    predictions_dir.mkdir(exist_ok=True)
    with (output / "events.jsonl").open("x", encoding="utf-8") as events:
        def emit(value):
            events.write(json.dumps(value, ensure_ascii=True, allow_nan=False) + "\n")
            events.flush()

        for index, record in enumerate(plan.selection.records):
            started = perf_counter()
            identity = {"artifact_id": record.artifact_id, "engine": engine,
                        "phase": "first_call" if index == 0 else "subsequent_call",
                        "started_at": datetime.now(timezone.utc).isoformat()}
            emit({"event": "start", **identity})
            row = {**identity, "inference_seconds": None, "evaluation_seconds": None,
                   "prediction_path": None, "metrics": None, "error_type": None}
            stage = "inference"
            stage_started = perf_counter()
            try:
                if job.get("config", {}).get("evaluation_contract"):
                    from polydocbench.eval.contract import FrozenEvaluation

                    stage = "validation"
                    FrozenEvaluation.model_validate(job["config"]["evaluation_contract"]).verify_runtime()
                policy = job.get("config", {}).get("visibility_policy")
                if policy is not None:
                    from polydocbench.eval.scope import prepare_scope

                    stage = "validation"
                    gt = json.loads((root / record.image_gt.path).read_text(encoding="utf-8"))
                    task = {"tesseract": "quality", "docling": "structure", "dotsocr": "ordering"}[engine]
                    prepare_scope(gt, task, policy)
                    row["validation_seconds"] = perf_counter() - stage_started
                    stage, stage_started = "inference", perf_counter()
                predicted = adapter.predict(record, root / record.image.path,
                                             predictions_dir / f"{record.artifact_id}.raw")
                row["inference_seconds"] = perf_counter() - stage_started
                prediction = predictions_dir / f"{record.artifact_id}.json"
                prediction.write_text(json.dumps(predicted, ensure_ascii=False, allow_nan=False), encoding="utf-8")
                row["prediction_path"] = prediction.relative_to(output).as_posix()
                stage = "evaluation"
                stage_started = perf_counter()
                gt = json.loads((root / record.image_gt.path).read_text(encoding="utf-8"))
                row["metrics"] = adapter.evaluate(record, gt, predicted)
                if policy is not None and (row["metrics"].get("evaluation_protocol_version") != "0.3" or not hasattr(adapter, "scope")):
                    raise ValueError("A scoped pilot must produce protocol 0.3 metrics and an exclusion ledger")
                if policy is not None and hasattr(adapter, "scope"):
                    scope_path = predictions_dir / f"{record.artifact_id}.scope.json"
                    scope_path.write_text(json.dumps(adapter.scope, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
                    row["scope_path"] = scope_path.relative_to(output).as_posix()
                row["evaluation_seconds"] = perf_counter() - stage_started
                row["status"] = "success"
            except Exception as exc:
                row[f"{stage}_seconds"] = perf_counter() - stage_started
                # Exception messages from remote clients may contain credentials or response bodies.
                row.update(status="failed", error_type=type(exc).__name__, failed_stage=stage)
            row["total_seconds"] = perf_counter() - started
            emit({"event": "result", **row})


def main() -> None:
    job_path = Path(sys.argv[1])
    job = json.loads(job_path.read_text(encoding="utf-8"))
    if job["engine"] == "dotsocr":
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    run_worker(job, job_path.parent)


if __name__ == "__main__":
    main()
