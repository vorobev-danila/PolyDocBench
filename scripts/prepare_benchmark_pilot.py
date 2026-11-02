"""Select a fixed paired pilot from a verified artifact inventory."""

import argparse
import json
from pathlib import Path

from polydocbench.benchmark.manifest import DatasetManifest, verify_manifest
from polydocbench.benchmark.pilot import prepare_pilot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New pilot plan JSON; never overwritten")
    parser.add_argument("--base-pages", type=int, default=18)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--variant", type=int, default=0)
    parser.add_argument("--split", choices=["dev", "unassigned"], default="dev")
    parser.add_argument("--profiles", nargs="+", default=None)
    args = parser.parse_args(argv)
    manifest = DatasetManifest.model_validate_json(args.manifest.read_text(encoding="utf-8"))
    plan = prepare_pilot(manifest, base_pages=args.base_pages, seed=args.seed, variant=args.variant,
                         profiles=args.profiles, split=args.split)
    issues = verify_manifest(plan.selection, args.input_dir)
    if issues:
        raise ValueError(f"Selected pilot files failed integrity verification: {issues[0].path}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(plan.model_dump_json(indent=2) + "\n")
    print(json.dumps(plan.summary(), ensure_ascii=True, indent=2))
    if args.split == "unassigned":
        print("ENGINEERING PILOT ONLY: families/splits/rights are not approved by this command.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
