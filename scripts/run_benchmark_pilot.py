"""Measure inference, evaluation, failures and local RSS on a frozen paired pilot."""

import argparse
import json
from pathlib import Path

from polydocbench.benchmark.pilot import PilotPlan
from polydocbench.benchmark.pilot_runtime import run_pilot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--engine", choices=["tesseract", "dotsocr", "docling"], required=True)
    parser.add_argument("--timeout-per-image", type=float, default=600)
    parser.add_argument("--tesseract-cmd", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--api-key-env", default=None)
    parser.add_argument("--request-timeout", type=float, default=180)
    parser.add_argument("--max-retries", type=int, default=0)
    args = parser.parse_args(argv)
    config = {key: getattr(args, key) for key in
              ("tesseract_cmd", "base_url", "model", "api_key_env", "request_timeout", "max_retries")
              if getattr(args, key) is not None}
    if args.request_timeout <= 0 or args.max_retries < 0:
        parser.error("request timeout must be positive and retries non-negative")
    plan = PilotPlan.model_validate_json(args.plan.read_text(encoding="utf-8"))
    print(f"Pilot: {plan.plan_id}; engine={args.engine}; images={len(plan.selection.records)}", flush=True)
    summary = run_pilot(plan, args.input_dir, args.output_dir, engine=args.engine, config=config,
                        timeout_per_image=args.timeout_per_image)
    print(json.dumps(summary, indent=2))
    return 0 if summary["successful"] == summary["selected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
