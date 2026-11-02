"""Draft, review-gate, and freeze leakage-resistant benchmark source splits."""

from __future__ import annotations

import argparse
from pathlib import Path

from polydocbench.benchmark import DatasetManifest, SourceFamilyCatalog, draft_source_catalog, freeze_split_plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    draft = commands.add_parser("draft", help="Create an unreviewed family catalog candidate")
    draft.add_argument("--manifest", type=Path, required=True)
    draft.add_argument("--output", type=Path, required=True)
    freeze = commands.add_parser("freeze", help="Freeze deterministic dev/test assignments from a reviewed catalog")
    freeze.add_argument("--catalog", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    freeze.add_argument("--seed", type=int, default=42)
    freeze.add_argument("--development-fraction", type=float, default=0.2)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "draft":
        manifest = DatasetManifest.model_validate_json(args.manifest.read_text(encoding="utf-8"))
        result = draft_source_catalog(manifest)
        label = "Draft family catalog"
    else:
        catalog = SourceFamilyCatalog.model_validate_json(args.catalog.read_text(encoding="utf-8"))
        result = freeze_split_plan(catalog, seed=args.seed, development_fraction=args.development_fraction)
        label = "Frozen split plan"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"{label}: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
