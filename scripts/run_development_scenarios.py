"""Measure existing noise bundles on exactly the calibration's frozen source pages."""

import argparse
import csv
import json
from pathlib import Path

from polydocbench.benchmark.calibration import CalibrationPlan
from polydocbench.benchmark.manifest import DatasetManifest, verify_manifest
from polydocbench.benchmark.pilot import base_page_key, prepare_pilot
from polydocbench.benchmark.pilot_runtime import run_pilot
from polydocbench.eval import write_ocr_dashboard
from polydocbench.eval.quality import aggregate_ocr_counts
from polydocbench.eval.scoped import scope_summary


def scenario_plan(manifest, calibration):
    keys = {base_page_key(r) for r in calibration.selection.records}
    records = [r for r in manifest.records if base_page_key(r) in keys]
    subset = DatasetManifest(discovered_count=len(records), records=records, issues=[], split_plan=manifest.split_plan)
    return prepare_pilot(subset, base_pages=len(keys), seed=calibration.spec.seed, split=calibration.split,
                         profiles=["clean", "light_scan", "medium_scan", "heavy_scan"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True, help="Development candidate root")
    parser.add_argument("--timeout-per-image", type=float, default=120)
    args = parser.parse_args()
    root = args.input_dir.resolve(strict=True)
    manifest = DatasetManifest.model_validate_json((root / "manifest.json").read_text(encoding="utf-8"))
    calibration = CalibrationPlan.model_validate_json((root / "calibration/calibration_plan.json").read_text(encoding="utf-8"))
    if manifest.issues or verify_manifest(manifest, root / "dataset"):
        raise ValueError("Candidate inputs no longer verify")
    if not calibration.spec.evaluation_contract:
        raise ValueError("Use a frozen visibility-aware calibration contract")
    plan = scenario_plan(manifest, calibration)
    output = root / "scenarios"
    if output.exists() and any(output.iterdir()):
        raise ValueError("Scenario results already exist; never overwrite inference")
    output.mkdir(parents=True, exist_ok=True)
    (output / "pilot_plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    run_pilot(plan, root / "dataset", output / "run", engine="tesseract",
               config=calibration.spec.evaluation_contract.model_config_values(), timeout_per_image=args.timeout_per_image)
    raw = [json.loads(s) for s in (output / "run/results.jsonl").read_text(encoding="utf-8").splitlines()]
    records = {r.artifact_id: r for r in plan.selection.records}
    rows = [{"language": records[r["artifact_id"]].language, "article_id": records[r["artifact_id"]].article_id,
             "template": records[r["artifact_id"]].template, "profile": records[r["artifact_id"]].profile,
             "artifact_id": r["artifact_id"], **r["metrics"]} for r in raw if r["status"] == "success"]
    (output / "metrics.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    complete = {key for key in {base_page_key(r) for r in plan.selection.records}
                if all(r["status"] == "success" for r in raw if base_page_key(records[r["artifact_id"]]) == key)}
    summaries = []
    for profile in ("clean", "light_scan", "medium_scan", "heavy_scan"):
        selected = [r for r in rows if r["profile"] == profile and base_page_key(records[r["artifact_id"]]) in complete]
        summaries.append({"profile": profile, "selected_base_pages": plan.requested_base_pages,
                          "complete_base_pages": len(complete), **aggregate_ocr_counts(selected), **scope_summary(selected)})
    with (output / "summary.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=sorted({key for row in summaries for key in row}))
        writer.writeheader()
        writer.writerows(summaries)
    report = {"calibration_plan_id": calibration.plan_id, "scenario_plan_id": plan.plan_id,
              "selected_images": len(raw), "successful_images": len(rows), "complete_base_pages": len(complete),
              "profiles": summaries,
              "interpretation": "Paired pages, but geometric clipping may change eligible GT denominators; bundles are not a pure photometric or monotonic-severity scale",
              "approval_status": "pending_human_review"}
    (output / "comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_ocr_dashboard(output / "dashboard.html", rows)
    print(json.dumps(report, indent=2))
    return 0 if len(rows) == len(raw) else 1


if __name__ == "__main__":
    raise SystemExit(main())
