"""Inventory existing experiment files or verify their saved SHA-256 fingerprints."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from polydocbench.benchmark import DatasetManifest, build_manifest, load_benchmark_spec, verify_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default="outputs/experiments/tesseract_quality")
    parser.add_argument("--output-dir", default=None, help="Default: INPUT_DIR/benchmark_inventory")
    parser.add_argument("--languages", nargs="+", default=None)
    parser.add_argument("--templates", nargs="+", default=None)
    parser.add_argument("--spec", default="configs/benchmark_icdar2027.json", help="Draft research targets, not generation settings")
    parser.add_argument("--verify", type=Path, help="Verify an existing manifest instead of rebuilding it")
    parser.add_argument("--strict", action="store_true", help="Also fail on incomplete historical provenance")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.verify and (args.languages or args.templates):
        parser.error("--verify checks the full saved manifest; filters are only supported when building")
    root = Path(args.input_dir)
    if args.verify:
        manifest = DatasetManifest.model_validate_json(args.verify.read_text(encoding="utf-8"))
        issues = verify_manifest(manifest, root)
        for issue in issues:
            print(f"ERROR {issue.path}: {issue.message}")
        print(f"File integrity: {'FAILED' if issues else 'OK'}; records={len(manifest.records)}")
        if issues or manifest.issues or not manifest.records:
            if manifest.issues:
                print(f"Inventory contains {len(manifest.issues)} rejected artifacts; inspect its issue list.")
            return 1
        return _provenance_exit_code(manifest, args.strict)

    spec = load_benchmark_spec(args.spec)
    manifest = build_manifest(root, languages=args.languages, templates=args.templates)
    output = Path(args.output_dir) if args.output_dir else root / "benchmark_inventory"
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    report_path = output / "inventory_report.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    report = {**manifest.summary(), "draft_benchmark_id": spec.benchmark_id, "draft_target_counts": spec.target_counts()}
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Inventory: discovered={manifest.discovered_count}, accepted={len(manifest.records)}, rejected={len(manifest.issues)}")
    print(f"Manifest: {manifest_path}")
    print(f"Report: {report_path}")
    print("Generation reproducibility: NOT ESTABLISHED; splits and source families require review.")
    if not manifest.records or manifest.issues:
        return 1
    return _provenance_exit_code(manifest, args.strict)


def _provenance_exit_code(manifest: DatasetManifest, strict: bool) -> int:
    if strict and any(record.provenance_gaps for record in manifest.records):
        print("Strict provenance check: FAILED; historical generation settings are incomplete (exit 2).")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
