"""Evaluate Docling structure extraction on prepared noisy scans."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from polydocbench.eval import (
    evaluate_structure,
    extract_docling_structure,
    extract_gt_structure_elements,
    load_gt,
    parse_docling_structure,
    structure_matches_to_dicts,
    write_structure_dashboard,
)


@dataclass(frozen=True)
class ScanArtifact:
    language: str
    article_id: str
    template: str
    page_number: int
    profile: str
    variant: int
    image_path: Path
    gt_path: Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Docling structure evaluation on PolyDocBench scans.")
    parser.add_argument("--input-dir", default="outputs/experiments/tesseract_quality", help="Directory with noisy scans and transformed GT")
    parser.add_argument("--output-dir", default="outputs/experiments/docling_structure", help="Docling structure result directory")
    parser.add_argument("--languages", nargs="+", default=None, help="Optional language filters")
    parser.add_argument("--article-ids", nargs="+", default=None, help="Optional article filters")
    parser.add_argument("--templates", nargs="+", default=None, help="Optional layout template filters")
    parser.add_argument("--profiles", nargs="+", default=None, help="Optional noise profile filters")
    parser.add_argument("--page-numbers", nargs="+", type=int, default=None, help="Optional one-based page filters")
    parser.add_argument("--max-images", type=int, default=None, help="Maximum number of scan artifacts for a smoke run")
    parser.add_argument("--iou-threshold", type=float, default=0.5, help="IoU threshold for structure element matching")
    parser.add_argument("--reuse", action="store_true", help="Reuse existing Docling outputs")
    parser.add_argument("--continue-on-error", action="store_true", help="Record failed artifacts and continue the batch")
    parser.add_argument("--dashboard-only", action="store_true", help="Rebuild dashboard.html from existing structure metrics")
    parser.add_argument("--no-dashboard", action="store_true", help="Do not generate dashboard.html after evaluation")
    return parser


def main() -> int:
    _configure_console_encoding()
    args = build_parser().parse_args()
    input_root = Path(args.input_dir)
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    metrics_path = output_root / "metrics.jsonl"
    errors_path = output_root / "errors.jsonl"
    summary_path = output_root / "summary.csv"
    dashboard_path = output_root / "dashboard.html"

    if args.dashboard_only:
        rows = _read_metrics(metrics_path)
        _write_summary(summary_path, rows)
        write_structure_dashboard(dashboard_path, rows)
        print(f"Dashboard: {dashboard_path}")
        return 0

    artifacts = discover_scan_artifacts(
        input_root,
        languages=args.languages,
        article_ids=args.article_ids,
        templates=args.templates,
        profiles=args.profiles,
        page_numbers=args.page_numbers,
    )
    if args.max_images is not None:
        artifacts = artifacts[: args.max_images]
    if not artifacts:
        raise RuntimeError(f"No noisy scan artifacts were found under: {input_root}")

    print("Docling structure evaluation")
    print(f"Input scans: {input_root}")
    print(f"Selected artifacts: {len(artifacts)}")
    rows: list[dict[str, Any]] = []
    with metrics_path.open("w", encoding="utf-8") as metrics_file, errors_path.open("w", encoding="utf-8") as errors_file:
        for index, artifact in enumerate(artifacts, start=1):
            try:
                row = _evaluate_artifact(artifact, args, input_root, output_root)
            except Exception as exc:
                error = {
                    "language": artifact.language,
                    "article_id": artifact.article_id,
                    "template": artifact.template,
                    "page_number": artifact.page_number,
                    "profile": artifact.profile,
                    "variant": artifact.variant,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                errors_file.write(json.dumps(error, ensure_ascii=False) + "\n")
                print(f"[{index}/{len(artifacts)}] ERROR {artifact.image_path}: {type(exc).__name__}: {exc}")
                if args.continue_on_error:
                    continue
                raise
            rows.append(row)
            metrics_file.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(
                f"[{index}/{len(artifacts)}] {artifact.language}/{artifact.article_id}/{artifact.template}/"
                f"page_{artifact.page_number:03d}/{artifact.profile}_{artifact.variant}: "
                f"score={row['structure_score']:.3f} det_F1={row['detection_F1']:.3f} "
                f"type_acc={row['type_accuracy']:.3f} mean_iou={row['mean_iou']:.3f}"
            )

    _write_summary(summary_path, rows)
    print(f"Metrics: {metrics_path}")
    print(f"Summary: {summary_path}")
    if errors_path.stat().st_size:
        print(f"Errors: {errors_path}")
    if not args.no_dashboard:
        write_structure_dashboard(dashboard_path, rows)
        print(f"Dashboard: {dashboard_path}")
    return 0


def discover_scan_artifacts(
    input_root: Path,
    *,
    languages: list[str] | None = None,
    article_ids: list[str] | None = None,
    templates: list[str] | None = None,
    profiles: list[str] | None = None,
    page_numbers: list[int] | None = None,
) -> list[ScanArtifact]:
    artifacts: list[ScanArtifact] = []
    for gt_path in sorted(input_root.glob("*/*/*/noisy/page_*/*_gt.json")):
        relative = gt_path.relative_to(input_root)
        language, article_id, template = relative.parts[:3]
        page_number = int(relative.parts[4].split("_", 1)[1])
        stem = gt_path.name.removesuffix("_gt.json")
        profile, variant = stem.rsplit("_", 1)
        image_path = gt_path.with_name(f"{stem}.jpg")
        if not image_path.exists():
            continue
        if languages and language not in languages:
            continue
        if article_ids and article_id not in article_ids:
            continue
        if templates and template not in templates:
            continue
        if profiles and profile not in profiles:
            continue
        if page_numbers and page_number not in page_numbers:
            continue
        artifacts.append(
            ScanArtifact(
                language=language,
                article_id=article_id,
                template=template,
                page_number=page_number,
                profile=profile,
                variant=int(variant),
                image_path=image_path,
                gt_path=gt_path,
            )
        )
    return artifacts


def _evaluate_artifact(artifact: ScanArtifact, args: argparse.Namespace, input_root: Path, output_root: Path) -> dict[str, Any]:
    relative_case = artifact.image_path.parent.relative_to(input_root)
    output_case = output_root / relative_case
    output_case.mkdir(parents=True, exist_ok=True)
    stem = f"{artifact.profile}_{artifact.variant}"
    raw_output_path = output_case / f"{stem}_docling_raw.json"
    structure_path = output_case / f"{stem}_docling_structure.json"
    matches_path = output_case / f"{stem}_structure_matches.json"

    if args.reuse and structure_path.exists():
        predicted_elements = json.loads(structure_path.read_text(encoding="utf-8"))
    elif args.reuse and raw_output_path.exists():
        predicted_elements = parse_docling_structure(
            json.loads(raw_output_path.read_text(encoding="utf-8")), page_number=artifact.page_number
        )
        structure_path.write_text(json.dumps(predicted_elements, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        predicted_elements = extract_docling_structure(
            artifact.image_path,
            raw_output_path=raw_output_path,
            page_number=artifact.page_number,
        )
        structure_path.write_text(json.dumps(predicted_elements, ensure_ascii=False, indent=2), encoding="utf-8")

    gt_elements = extract_gt_structure_elements(load_gt(artifact.gt_path), page_number=artifact.page_number)
    metrics, matches = evaluate_structure(gt_elements, predicted_elements, iou_threshold=args.iou_threshold)
    matches_path.write_text(json.dumps(structure_matches_to_dicts(matches), ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "engine": "docling",
        "language": artifact.language,
        "article_id": artifact.article_id,
        "template": artifact.template,
        "page_number": artifact.page_number,
        "profile": artifact.profile,
        "variant": artifact.variant,
        "image_path": str(artifact.image_path),
        "gt_path": str(artifact.gt_path),
        "prediction_path": str(structure_path),
        "raw_output_path": str(raw_output_path),
        **metrics,
    }


def _read_metrics(metrics_path: Path) -> list[dict[str, Any]]:
    if not metrics_path.exists():
        return []
    return [json.loads(line) for line in metrics_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_summary(summary_path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "language",
        "template",
        "profile",
        "count",
        "structure_score",
        "detection_F1",
        "type_accuracy",
        "mean_iou",
    ]
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row["language"], row["template"], row["profile"]), []).append(row)
    with summary_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for (language, template, profile), group in sorted(grouped.items()):
            writer.writerow(
                {
                    "language": language,
                    "template": template,
                    "profile": profile,
                    "count": len(group),
                    "structure_score": mean(float(row["structure_score"]) for row in group),
                    "detection_F1": mean(float(row["detection_F1"]) for row in group),
                    "type_accuracy": mean(float(row["type_accuracy"]) for row in group),
                    "mean_iou": mean(float(row["mean_iou"]) for row in group),
                }
            )


def _configure_console_encoding() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
