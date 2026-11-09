"""Freeze and evaluate page-paired one-factor Tesseract noise sweeps."""

import argparse
import json
from pathlib import Path

from polydocbench.benchmark.calibration import CalibrationSpec, prepare_calibration
from polydocbench.benchmark.calibration_run import run_calibration, write_calibration_results
from polydocbench.benchmark.manifest import DatasetManifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/noise_calibration.json"))
    parser.add_argument("--evaluation-contract", type=Path, help="Freeze protocol 0.3 settings and implementation identity")
    parser.add_argument("--base-pages", type=int, default=12)
    parser.add_argument("--languages", nargs="+", default=None)
    parser.add_argument("--split", choices=["dev", "unassigned"], default="dev")
    parser.add_argument("--repeats", type=int, default=None, help="Sensor field repeats; deterministic effects are generated once")
    parser.add_argument("--tesseract-cmd", default=None)
    parser.add_argument("--timeout-per-image", type=float, default=120)
    parser.add_argument("--report-only", action="store_true", help="Validate saved results and rebuild reports without inference")
    args = parser.parse_args(argv)
    if args.report_only:
        report = write_calibration_results(args.output_dir)
    else:
        if args.manifest is None or args.input_dir is None:
            parser.error("--manifest and --input-dir are required unless --report-only is selected")
        spec_data = json.loads(args.config.read_text(encoding="utf-8"))
        if args.evaluation_contract:
            from polydocbench.eval.contract import load_evaluation_settings

            spec_data.update(evaluation_protocol_version="0.3", evaluation_contract=load_evaluation_settings(args.evaluation_contract).model_dump())
        if args.repeats is not None:
            spec_data["repeats"] = args.repeats
        spec = CalibrationSpec.model_validate(spec_data)
        inventory = DatasetManifest.model_validate_json(args.manifest.read_text(encoding="utf-8"))
        plan = prepare_calibration(inventory, spec, base_pages=args.base_pages, split=args.split, languages=args.languages)
        count = len(plan.selection.records) * (1 + len(spec.conditions()))
        print(f"Calibration: {len(plan.selection.records)} base pages, {count} images, split={plan.split}", flush=True)
        report = run_calibration(plan, args.input_dir, args.output_dir, tesseract_cmd=args.tesseract_cmd,
                                 timeout_per_image=args.timeout_per_image)
    print(json.dumps(report, indent=2))
    print(f"Dashboard: {args.output_dir / 'dashboard.html'}")
    return 0 if report["selected_images"] == report["successful_images"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
