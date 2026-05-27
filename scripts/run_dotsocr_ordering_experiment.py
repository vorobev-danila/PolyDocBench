"""Evaluate dots.ocr semantic reading order on prepared noisy scans."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from dotenv import load_dotenv

from polydocbench.eval import (
    evaluate_semantic_ordering,
    extract_dotsocr_blocks,
    extract_visible_gt_blocks,
    load_gt,
    write_ordering_dashboard,
)
from polydocbench.eval.dotsocr import DEFAULT_DOTSOCR_BASE_URL, DEFAULT_DOTSOCR_MODEL
from polydocbench.eval.dotsocr import parse_dotsocr_blocks_response


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
    parser = argparse.ArgumentParser(description="Run dots.ocr semantic reading-order evaluation on PolyDocBench scans.")
    parser.add_argument("--input-dir", default="outputs/experiments/tesseract_quality", help="Directory with noisy scans and transformed GT")
    parser.add_argument("--output-dir", default="outputs/experiments/dotsocr_ordering", help="dots.ocr ordering result directory")
    parser.add_argument("--base-url", default=DEFAULT_DOTSOCR_BASE_URL, help="OpenAI-compatible API base URL")
    parser.add_argument("--model", default=DEFAULT_DOTSOCR_MODEL, help="Remote dots.ocr model name")
    parser.add_argument("--api-key-env", default="LITELLM_API_KEY", help="Environment variable containing the API key")
    parser.add_argument("--timeout", type=float, default=180.0, help="API request timeout in seconds")
    parser.add_argument("--max-retries", type=int, default=1, help="API client retries per request")
    parser.add_argument("--languages", nargs="+", default=None, help="Optional language filters, for example: en ru")
    parser.add_argument("--article-ids", nargs="+", default=None, help="Optional article filters")
    parser.add_argument("--templates", nargs="+", default=None, help="Optional layout template filters")
    parser.add_argument("--profiles", nargs="+", default=None, help="Optional noise profile filters")
    parser.add_argument("--page-numbers", nargs="+", type=int, default=None, help="Optional one-based page filters")
    parser.add_argument("--max-images", type=int, default=None, help="Maximum number of scan artifacts for a smoke run")
    parser.add_argument("--min-block-similarity", type=float, default=0.3, help="Minimum text-first semantic block match score")
    parser.add_argument("--max-gt-span", type=int, default=3, help="Maximum adjacent GT blocks matched to one model block")
    parser.add_argument("--reuse", action="store_true", help="Reuse existing semantic block predictions")
    parser.add_argument("--continue-on-error", action="store_true", help="Record failed artifacts and continue the remote batch")
    parser.add_argument("--dashboard-only", action="store_true", help="Rebuild dashboard.html from existing ordering metrics")
    parser.add_argument("--no-dashboard", action="store_true", help="Do not generate dashboard.html after evaluation")
    return parser


def main() -> int:
    _configure_console_encoding()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
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
        write_ordering_dashboard(dashboard_path, rows)
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

    api_key = os.environ.get(args.api_key_env)
    print(f"dots.ocr model: {args.model}")
    print(f"Input scans: {input_root}")
    print(f"Selected artifacts: {len(artifacts)}")
    rows: list[dict[str, Any]] = []
    with metrics_path.open("w", encoding="utf-8") as metrics_file, errors_path.open("w", encoding="utf-8") as errors_file:
        for index, artifact in enumerate(artifacts, start=1):
            try:
                row = _evaluate_artifact(artifact, args, input_root, output_root, api_key)
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
                f"ordered_WER={row['ordered_WER']:.3f} token_F1={row['token_F1']:.3f} "
                f"pairwise={row['pairwise_accuracy']:.3f} coverage={row['matched_block_ratio']:.3f}"
            )

    _write_summary(summary_path, rows)
    print(f"Metrics: {metrics_path}")
    print(f"Summary: {summary_path}")
    if errors_path.stat().st_size:
        print(f"Errors: {errors_path}")
    if not args.no_dashboard:
        write_ordering_dashboard(dashboard_path, rows)
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
        page_number = int(relative.parts[4].removeprefix("page_"))
        stem = gt_path.stem.removesuffix("_gt")
        profile, variant = _parse_artifact_name(stem)
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
        artifacts.append(ScanArtifact(language, article_id, template, page_number, profile, variant, image_path, gt_path))
    return artifacts


def _evaluate_artifact(
    artifact: ScanArtifact,
    args: argparse.Namespace,
    input_root: Path,
    output_root: Path,
    api_key: str | None,
) -> dict[str, Any]:
    relative_parent = artifact.gt_path.relative_to(input_root).parent
    prediction_dir = output_root / relative_parent
    prediction_path = prediction_dir / f"{artifact.profile}_{artifact.variant}_dotsocr_blocks.json"
    raw_response_path = prediction_dir / f"{artifact.profile}_{artifact.variant}_dotsocr_raw.txt"
    matches_path = prediction_dir / f"{artifact.profile}_{artifact.variant}_block_matches.json"

    if args.reuse and prediction_path.exists():
        predicted_blocks = json.loads(prediction_path.read_text(encoding="utf-8"))
    elif args.reuse and raw_response_path.exists():
        predicted_blocks = parse_dotsocr_blocks_response(raw_response_path.read_text(encoding="utf-8"), page_number=1)
        prediction_path.parent.mkdir(parents=True, exist_ok=True)
        prediction_path.write_text(json.dumps(predicted_blocks, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        if not api_key:
            raise RuntimeError(f"Set {args.api_key_env} before requesting dots.ocr predictions.")
        predicted_blocks = extract_dotsocr_blocks(
            artifact.image_path,
            api_key=api_key,
            base_url=args.base_url,
            model=args.model,
            page_number=1,
            raw_response_path=raw_response_path,
            timeout=args.timeout,
            max_retries=args.max_retries,
        )
        prediction_path.parent.mkdir(parents=True, exist_ok=True)
        prediction_path.write_text(json.dumps(predicted_blocks, ensure_ascii=False, indent=2), encoding="utf-8")

    gt_blocks = extract_visible_gt_blocks(load_gt(artifact.gt_path), page_number=1)
    metrics, matches = evaluate_semantic_ordering(
        gt_blocks,
        predicted_blocks,
        min_similarity=args.min_block_similarity,
        max_gt_span=args.max_gt_span,
    )
    matches_path.parent.mkdir(parents=True, exist_ok=True)
    matches_path.write_text(
        json.dumps(
            [
                {
                    "prediction_index": match.prediction_index,
                    "prediction_text": match.prediction["text"],
                    "gt_ids": match.gt_ids,
                    "gt_text": " ".join(block["text"] for block in match.gt_blocks),
                    "similarity": match.similarity,
                }
                for match in matches
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "engine": "dotsocr",
        "model": args.model,
        "language": artifact.language,
        "article_id": artifact.article_id,
        "template": artifact.template,
        "page_number": artifact.page_number,
        "profile": artifact.profile,
        "variant": artifact.variant,
        "image_path": str(artifact.image_path),
        "gt_path": str(artifact.gt_path),
        "prediction_path": str(prediction_path),
        "raw_response_path": str(raw_response_path),
        "matches_path": str(matches_path),
        **metrics,
    }


def _parse_artifact_name(stem: str) -> tuple[str, int]:
    profile, _, raw_variant = stem.rpartition("_")
    try:
        return profile, int(raw_variant)
    except ValueError:
        return stem, 0


def _read_metrics(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Metrics file was not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def _write_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "engine", "model", "language", "template", "profile", "article_count", "count",
        "mean_ordered_CER", "mean_ordered_WER", "mean_token_F1", "mean_kendall_tau",
        "mean_pairwise_accuracy", "mean_matched_block_ratio",
    ]
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["language"], row["template"], row["profile"]), []).append(row)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for (language, template, profile), group in sorted(groups.items()):
            writer.writerow(
                {
                    "engine": "dotsocr",
                    "model": group[0]["model"],
                    "language": language,
                    "template": template,
                    "profile": profile,
                    "article_count": len({row["article_id"] for row in group}),
                    "count": len(group),
                    **{
                        f"mean_{metric}": mean(float(row[metric]) for row in group)
                        for metric in (
                            "ordered_CER", "ordered_WER", "token_F1", "kendall_tau",
                            "pairwise_accuracy", "matched_block_ratio",
                        )
                    },
                }
            )


def _configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    raise SystemExit(main())
