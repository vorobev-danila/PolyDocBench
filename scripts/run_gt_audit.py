"""Audit a frozen paired selection without OCR calls or automatic human approval."""

import argparse
import json
from pathlib import Path

from polydocbench.benchmark.gt_audit import GTAuditPlan, rebuild_gt_audit, run_gt_audit
from polydocbench.benchmark.manifest import DatasetManifest
from polydocbench.benchmark.pilot import PilotPlan, base_page_key, prepare_pilot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--manifest", type=Path)
    group.add_argument("--pilot-plan", type=Path)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--base-pages", type=int, default=18)
    selection.add_argument("--all-base-pages", action="store_true", help="Require all eligible pages and every requested profile")
    parser.add_argument("--profiles", nargs="+", default=["clean", "medium_scan", "heavy_scan"])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--split", choices=["dev", "unassigned"], default="dev")
    parser.add_argument("--point-tolerance", type=float, default=0.01)
    parser.add_argument("--pixel-tolerance", type=float, default=0.05)
    parser.add_argument("--no-pixel-replay", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--review-file", type=Path)
    args = parser.parse_args(argv)
    if args.report_only:
        result = rebuild_gt_audit(args.output_dir, args.input_dir, args.review_file)
    else:
        if args.review_file:
            parser.error("Use --review-file with --report-only after the frozen audit has been generated")
        if args.pilot_plan:
            pilot = PilotPlan.model_validate_json(args.pilot_plan.read_text(encoding="utf-8"))
        elif args.manifest:
            inventory = DatasetManifest.model_validate_json(args.manifest.read_text(encoding="utf-8"))
            count = len({base_page_key(r) for r in inventory.records if r.split == args.split and r.variant == 0
                         and r.profile in args.profiles}) if args.all_base_pages else args.base_pages
            pilot = prepare_pilot(inventory, base_pages=count, seed=args.seed, split=args.split, profiles=args.profiles)
        else:
            parser.error("Provide --manifest or --pilot-plan, or use --report-only")
        plan = GTAuditPlan.freeze(pilot, point_tolerance=args.point_tolerance, pixel_tolerance=args.pixel_tolerance,
                                  replay_pixels=not args.no_pixel_replay)
        result = run_gt_audit(plan, args.input_dir, args.output_dir)
    print(json.dumps(result, indent=2))
    print(f"Report: {args.output_dir / 'index.html'}")
    return 1 if result["automatic_error_findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
