"""Generate calibration pairs and reuse the supervised Tesseract pilot runner."""

from __future__ import annotations

import csv
import json
import math
import shutil
from pathlib import Path

from polydocbench.eval import extract_gt_lines
from polydocbench.noise import NOISE_PIPELINE_VERSION, pdf_to_noisy_dataset
from polydocbench.provenance import fingerprint_file, json_sha256
from .calibration import CalibrationPlan, calibration_page_id, summarize_calibration
from .manifest import build_manifest, verify_manifest
from .pilot import PilotPlan, prepare_pilot
from .pilot_runtime import run_pilot
from .splits import apply_split_plan


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as file:
        file.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def generate_calibration(plan: CalibrationPlan, input_dir: str | Path, output_dir: str | Path) -> PilotPlan:
    root, output = Path(input_dir).resolve(strict=True), Path(output_dir).resolve()
    if plan.spec.noise_pipeline_version != NOISE_PIPELINE_VERSION:
        raise ValueError("Installed noise generator differs from the frozen calibration version")
    if plan.spec.evaluation_contract:
        plan.spec.evaluation_contract.verify_runtime()
    issues = verify_manifest(plan.selection, root)
    if issues:
        raise ValueError(f"Calibration input integrity failed: {issues[0].path}")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Calibration output must be new or empty")
    for record in plan.selection.records:
        gt = json.loads((root / record.pdf_gt.path).read_text(encoding="utf-8"))
        if not extract_gt_lines(gt, page_number=record.source_page_number):
            raise ValueError("Selected PDF page has no OCR line GT")
    output.mkdir(parents=True, exist_ok=True)
    _write(output / "calibration_plan.json", plan.model_dump())
    dataset = output / "dataset"
    dataset.mkdir()
    dependencies = {}
    for record in plan.selection.records:
        for file in [record.source, record.pdf, record.pdf_gt, *record.provenance_files]:
            if file.path in dependencies and dependencies[file.path] != file:
                raise ValueError("Selected pages disagree about a shared dependency")
            dependencies[file.path] = file
    for relative, file in sorted(dependencies.items()):
        target = dataset / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / relative, target)
        if fingerprint_file(dataset, target) != file:
            raise ValueError(f"Copied calibration input differs: {relative}")
    profiles = ["clean", *[c["profile"] for c in plan.spec.conditions()]]
    for index, record in enumerate(plan.selection.records, 1):
        page_id = calibration_page_id(record)
        directory = dataset / Path(record.pdf.path).parent / "noisy" / f"page_{record.source_page_number:03d}"
        config = plan.spec.recipes(page_id)
        result = pdf_to_noisy_dataset(dataset / record.pdf.path, dataset / record.pdf_gt.path, directory,
                                      page_index=record.source_page_number - 1, n_variants=1,
                                      seed=plan.spec.seed, dpi=plan.spec.dpi, profiles=profiles, config=config)
        clean = json.loads(Path(result["artifacts"][0]["gt_path"]).read_text(encoding="utf-8"))
        for artifact in result["artifacts"][1:]:
            gt = json.loads(Path(artifact["gt_path"]).read_text(encoding="utf-8"))
            if any(gt[key] != clean[key] for key in ("elements", "pages", "reading_order")):
                raise ValueError("Photometric calibration changed GT geometry/content")
        print(f"Generate [{index}/{len(plan.selection.records)}] {record.language}/{record.article_id}/"
              f"{record.template}: {len(result['artifacts'])} paired conditions", flush=True)
    manifest = build_manifest(dataset)
    if manifest.issues:
        raise ValueError(f"Generated calibration inventory rejected samples: {manifest.issues[0].message}")
    if plan.selection.split_plan:
        manifest = apply_split_plan(manifest, plan.selection.split_plan)
    expected = len(plan.selection.records) * len(profiles)
    if len(manifest.records) != expected:
        raise ValueError("Generated calibration inventory is incomplete")
    _write(output / "manifest.json", manifest.model_dump())
    pilot = prepare_pilot(manifest, base_pages=len(plan.selection.records), seed=plan.spec.seed,
                          profiles=profiles, split=plan.split)
    _write(output / "pilot_plan.json", pilot.model_dump())
    return pilot


def write_calibration_results(output_dir: str | Path) -> dict:
    output = Path(output_dir).resolve(strict=True)
    plan = CalibrationPlan.model_validate_json((output / "calibration_plan.json").read_text(encoding="utf-8"))
    pilot = PilotPlan.model_validate_json((output / "pilot_plan.json").read_text(encoding="utf-8"))
    _validate_generated_pilot(plan, pilot)
    issues = verify_manifest(pilot.selection, output / "dataset")
    if issues:
        raise ValueError(f"Generated calibration files changed: {issues[0].path}")
    metadata = json.loads((output / "run/run.json").read_text(encoding="utf-8"))
    if metadata.get("plan_id") != pilot.plan_id or metadata.get("engine") != "tesseract":
        raise ValueError("Run metadata is not bound to this calibration pilot")
    if plan.spec.evaluation_contract:
        job = json.loads((output / "run/job.json").read_text(encoding="utf-8"))
        if job.get("config", {}).get("evaluation_contract") != plan.spec.evaluation_contract.model_dump():
            raise ValueError("Calibration worker used a different evaluation contract")
        if metadata["configuration_sha256"] != json_sha256({"engine": "tesseract", "config": job["config"], "environment": metadata["environment"]}):
            raise ValueError("Calibration run identity differs from its worker configuration")
    raw = [json.loads(line) for line in (output / "run/results.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    records = {record.artifact_id: record for record in pilot.selection.records}
    if len(raw) != len(records) or {row["artifact_id"] for row in raw} != set(records):
        raise ValueError("Calibration result ledger must contain every selected artifact exactly once")
    rows = []
    for row in raw:
        record = records[row["artifact_id"]]
        if (row["plan_id"] != pilot.plan_id or row["engine"] != "tesseract"
                or row["configuration_sha256"] != metadata["configuration_sha256"]
                or row["profile"] != record.profile):
            raise ValueError("Result ledger contains a different plan/engine/configuration")
        if plan.spec.evaluation_contract and row["status"] == "success":
            ledger_path = (output / "run" / row["scope_path"]).resolve(strict=True)
            prediction_path = (output / "run" / row["prediction_path"]).resolve(strict=True)
            ledger_path.relative_to((output / "run").resolve())
            prediction_path.relative_to((output / "run").resolve())
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            predicted = json.loads(prediction_path.read_text(encoding="utf-8"))
            gt = json.loads((output / "dataset" / record.image_gt.path).read_text(encoding="utf-8"))
            if (ledger["scope_id"] != row["metrics"]["scope_id"]
                    or ledger["scope_id"] != json_sha256({k: v for k, v in ledger.items() if k != "scope_id"})
                    or ledger["prediction_sha256"] != json_sha256({"predictions": predicted})
                    or ledger["gt_sha256"] != json_sha256(gt)):
                raise ValueError("Calibration scope ledger differs from predictions/GT/metrics")
        rows.append({**row, "base_page_id": calibration_page_id(record)})
    summaries, pairs = summarize_calibration(plan, rows)
    for name, values in (("paired_results.jsonl", pairs), ("calibration_metrics.jsonl", summaries)):
        with (output / name).open("w", encoding="utf-8") as file:
            for value in values:
                file.write(json.dumps(value, ensure_ascii=True, allow_nan=False) + "\n")
    with (output / "calibration_summary.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    from .calibration_report import write_calibration_report

    write_calibration_report(output, plan, summaries, pairs, pilot)
    validation = {"calibration_plan_id": plan.plan_id, "pilot_plan_id": pilot.plan_id,
                  "selected_base_pages": len(plan.selection.records), "selected_images": len(records),
                  "result_rows": len(rows), "successful_images": sum(row["status"] == "success" for row in rows),
                  "expected_pairs": len(pairs), "available_pairs": sum(pair["paired"] for pair in pairs),
                  "file_integrity": "passed", "gt_geometry_checks": "passed_during_generation",
                  "review_status": "reviewed_family_dev" if plan.split == "dev" else "engineering_unassigned",
                  "uncertainty": "not_estimated", "severity_approval": "not_automatic"}
    if plan.spec.evaluation_contract:
        from polydocbench.eval.scoped import scope_summary

        validation.update(evaluation_protocol_version="0.3", evaluation_contract_id=plan.spec.evaluation_contract.contract_id,
                          visibility=scope_summary([r["metrics"] for r in rows if r["status"] == "success"]),
                          scientific_approval="pending_human_review")
    (output / "validation_report.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    return validation


def _validate_generated_pilot(plan: CalibrationPlan, pilot: PilotPlan) -> None:
    pages = {calibration_page_id(record): record for record in plan.selection.records}
    recipes = {page_id: plan.spec.recipes(page_id).profiles for page_id in pages}
    expected = {(page_id, profile) for page_id in pages for profile in ["clean", *recipes[page_id]]}
    actual = {(calibration_page_id(record), record.profile) for record in pilot.selection.records}
    if actual != expected or len(pilot.selection.records) != len(expected):
        raise ValueError("Generated pilot does not match the frozen calibration matrix")
    for record in pilot.selection.records:
        page_id = calibration_page_id(record)
        generation = record.noise_generation
        recipe = recipes[page_id].get(record.profile)
        if (record.split != plan.split or record.source_family != pages[page_id].source_family
                or record.dpi != plan.spec.dpi or record.variant != 0 or generation is None
                or generation.dpi != plan.spec.dpi or generation.master_seed != plan.spec.seed
                or generation.noise_pipeline_version != plan.spec.noise_pipeline_version
                or generation.profile_definition != recipe):
            raise ValueError("Generated pilot settings differ from the frozen calibration plan")


def run_calibration(plan: CalibrationPlan, input_dir: str | Path, output_dir: str | Path, *,
                    tesseract_cmd: str | None = None, timeout_per_image: float = 120) -> dict:
    if not math.isfinite(timeout_per_image) or timeout_per_image <= 0:
        raise ValueError("Calibration timeout must be finite and positive")
    pilot = generate_calibration(plan, input_dir, output_dir)
    config = {"tesseract_cmd": tesseract_cmd} if tesseract_cmd else None
    if plan.spec.evaluation_contract:
        config = {**(config or {}), **plan.spec.evaluation_contract.model_config_values()}
    run_pilot(pilot, Path(output_dir) / "dataset", Path(output_dir) / "run", engine="tesseract",
               config=config, timeout_per_image=timeout_per_image)
    return write_calibration_results(output_dir)
