"""Run a multilingual Tesseract OCR quality experiment with PolyDocBench.

Pipeline:
    Wikipedia URL -> source JSON -> PDF + GT -> degraded scans + transformed GT
    -> Tesseract OCR -> quality metrics.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from polydocbench.degradation import pdf_to_noisy_dataset
from polydocbench.eval import evaluate_ocr_quality, extract_gt_lines, load_gt
from polydocbench.eval.ocr import extract_tesseract_lines
from polydocbench.layout import LayoutEngine
from polydocbench.render import PDFRenderer
from polydocbench.sources.wikipedia import WikipediaParser


@dataclass(frozen=True)
class LanguageCase:
    code: str
    name: str
    tesseract_lang: str
    url: str


LANGUAGE_CASES: tuple[LanguageCase, ...] = (
    LanguageCase("en", "English", "eng", "https://en.wikipedia.org/wiki/History_of_Russia"),
    LanguageCase(
        "ru",
        "Russian",
        "rus",
        "https://ru.wikipedia.org/wiki/%D0%98%D1%81%D1%82%D0%BE%D1%80%D0%B8%D1%8F_%D0%A0%D0%BE%D1%81%D1%81%D0%B8%D0%B8",
    ),
    LanguageCase("fr", "French", "fra", "https://fr.wikipedia.org/wiki/Histoire_de_la_Russie"),
    LanguageCase("de", "German", "deu", "https://de.wikipedia.org/wiki/Geschichte_Russlands"),
    LanguageCase("es", "Spanish", "spa", "https://es.wikipedia.org/wiki/Historia_de_Rusia"),
    LanguageCase("it", "Italian", "ita", "https://it.wikipedia.org/wiki/Storia_della_Russia"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run multilingual Tesseract OCR experiments.")
    parser.add_argument("--output-dir", default="outputs/experiments/tesseract_quality", help="Experiment output root")
    parser.add_argument("--template", default="simple_article", help="Layout template")
    parser.add_argument("--font", default="DejaVu Sans/DejaVuSans.ttf", help="Font path")
    parser.add_argument("--profiles", nargs="+", default=["light_scan", "medium_scan", "heavy_scan"], help="Degradation profiles")
    parser.add_argument("--variants", type=int, default=1, help="Variants per degradation profile")
    parser.add_argument("--dpi", type=int, default=200, help="PDF rendering DPI for degradation")
    parser.add_argument("--seed", type=int, default=42, help="Degradation random seed")
    parser.add_argument("--page-index", type=int, default=0, help="PDF page index to degrade")
    parser.add_argument("--iou-threshold", type=float, default=0.3, help="Line matching IoU threshold")
    parser.add_argument("--languages", nargs="+", default=[case.code for case in LANGUAGE_CASES], help="Language codes to run")
    parser.add_argument("--tesseract-cmd", default=None, help="Path to tesseract executable")
    parser.add_argument("--reuse", action="store_true", help="Reuse existing parsed/rendered/degraded artifacts when possible")
    parser.add_argument("--fail-on-missing-tesseract-lang", action="store_true", help="Fail instead of skipping missing Tesseract languages")
    parser.add_argument("--debug-render", action="store_true", help="Render debug bboxes into PDFs")
    parser.add_argument("--verbose-layout", action="store_true", help="Show internal layout engine logs")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    cases = _select_cases(args.languages)
    tesseract_cmd = _resolve_tesseract_cmd(args.tesseract_cmd)
    if tesseract_cmd is None:
        raise RuntimeError(
            "Tesseract executable was not found. Install Tesseract or pass "
            "--tesseract-cmd \"C:\\Program Files\\Tesseract-OCR\\tesseract.exe\"."
        )
    _configure_pytesseract(tesseract_cmd)
    available_langs = _available_tesseract_languages(tesseract_cmd)

    metrics_path = output_root / "metrics.jsonl"
    summary_path = output_root / "summary.csv"
    metrics_rows: list[dict[str, Any]] = []

    with metrics_path.open("w", encoding="utf-8") as metrics_file:
        for case in cases:
            if case.tesseract_lang not in available_langs:
                message = f"Missing Tesseract language '{case.tesseract_lang}' for {case.code}"
                if args.fail_on_missing_tesseract_lang:
                    raise RuntimeError(message)
                print(f"SKIP {case.code}: {message}")
                continue

            print(f"\n== {case.code.upper()} | {case.name} ==")
            print(f"URL: {case.url}")
            row_batch = _run_case(case, args, output_root)
            for row in row_batch:
                metrics_file.write(json.dumps(row, ensure_ascii=False) + "\n")
            metrics_rows.extend(row_batch)

    _write_summary(summary_path, metrics_rows)
    print(f"Metrics: {metrics_path}")
    print(f"Summary: {summary_path}")
    return 0


def _run_case(case: LanguageCase, args: argparse.Namespace, output_root: Path) -> list[dict[str, Any]]:
    case_dir = output_root / case.code
    case_dir.mkdir(parents=True, exist_ok=True)

    source_path = case_dir / "source.json"
    pdf_path = case_dir / "document.pdf"
    gt_path = case_dir / "document_gt.json"
    dataset_dir = case_dir / "degraded"
    predictions_dir = case_dir / "predictions"
    predictions_dir.mkdir(parents=True, exist_ok=True)

    if not args.reuse or not source_path.exists():
        print("[1/4] Parse Wikipedia")
        parser = WikipediaParser(debug=False)
        source_data = parser.parse_from_url(case.url)
        if "error" in source_data:
            raise RuntimeError(f"Failed to parse {case.url}: {source_data['error']}")
        if not source_data.get("content"):
            raise RuntimeError(f"Parsed Wikipedia page has no content: {case.url}")
        parser.save_to_file(source_data, source_path)
        print(f"      title='{source_data.get('title', '')}', top_level_items={len(source_data.get('content', []))}")
    else:
        print(f"[1/4] Parse Wikipedia: reuse {source_path}")

    if not args.reuse or not pdf_path.exists() or not gt_path.exists():
        print("[2/4] Render PDF + GT")
        font_path = Path(args.font)
        layout = _run_quietly(
            lambda: LayoutEngine(font_path=font_path if font_path.exists() else None).layout_document(
                source_path,
                template_name=args.template,
            ),
            quiet=not args.verbose_layout,
        )
        _run_quietly(lambda: PDFRenderer(debug=args.debug_render).render(layout, pdf_path), quiet=not args.verbose_layout)
        print(f"      pages={len(layout.pages)}, elements={len(layout.elements)}, pdf={pdf_path.name}, gt={gt_path.name}")
    else:
        print(f"[2/4] Render PDF + GT: reuse {pdf_path}, {gt_path}")

    if not args.reuse or not dataset_dir.exists() or not list(dataset_dir.glob("*_gt.json")):
        print("[3/4] Generate degraded scans + transformed GT")
        degradation_result = pdf_to_noisy_dataset(
            pdf_path=pdf_path,
            gt_path=gt_path,
            output_dir=dataset_dir,
            page_index=args.page_index,
            n_variants=args.variants,
            seed=args.seed,
            dpi=args.dpi,
            profiles=args.profiles,
        )
        print(f"      artifacts={len(degradation_result['artifacts'])}, profiles={', '.join(degradation_result['profiles'])}")
    else:
        print(f"[3/4] Generate degraded scans + transformed GT: reuse {dataset_dir}")

    print("[4/4] Run Tesseract + evaluate")
    rows: list[dict[str, Any]] = []
    for artifact_gt_path in sorted(dataset_dir.glob("*_gt.json")):
        image_path = artifact_gt_path.with_name(artifact_gt_path.name.replace("_gt.json", ".jpg"))
        if not image_path.exists():
            continue

        prediction_lines = extract_tesseract_lines(
            image_path,
            lang=case.tesseract_lang,
            page_number=1,
            coordinate_system="image",
        )
        prediction_path = predictions_dir / f"{image_path.stem}_tesseract.json"
        prediction_path.write_text(json.dumps(prediction_lines, ensure_ascii=False, indent=2), encoding="utf-8")

        gt_lines = extract_gt_lines(load_gt(artifact_gt_path), page_number=1)
        metrics = evaluate_ocr_quality(gt_lines, prediction_lines, iou_threshold=args.iou_threshold)
        profile, variant = _parse_artifact_name(image_path.stem)
        row = {
            "language": case.code,
            "language_name": case.name,
            "tesseract_lang": case.tesseract_lang,
            "profile": profile,
            "variant": variant,
            "image_path": str(image_path),
            "gt_path": str(artifact_gt_path),
            "prediction_path": str(prediction_path),
            "gt_lines": len(gt_lines),
            "predicted_lines": len(prediction_lines),
            **metrics,
        }
        print(
            f"      {image_path.stem}: "
            f"CER={row['CER']:.3f} WER={row['WER']:.3f} IoU={row['IoU']:.3f} matched={row['matched_ratio']:.3f}"
            f" lines={row['predicted_lines']}/{row['gt_lines']}"
        )
        rows.append(row)

    return rows


def _run_quietly(fn, quiet: bool):
    if not quiet:
        return fn()
    with contextlib.redirect_stdout(io.StringIO()):
        return fn()


def _select_cases(codes: list[str]) -> list[LanguageCase]:
    by_code = {case.code: case for case in LANGUAGE_CASES}
    unknown = sorted(set(codes) - set(by_code))
    if unknown:
        raise ValueError(f"Unknown language codes: {', '.join(unknown)}")
    return [by_code[code] for code in codes]


def _resolve_tesseract_cmd(configured_path: str | None) -> str | None:
    candidates = [
        configured_path,
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists():
            return str(path)
        if shutil.which(candidate):
            return candidate
    return None


def _configure_pytesseract(tesseract_cmd: str) -> None:
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd


def _available_tesseract_languages(tesseract_cmd: str) -> set[str]:
    result = subprocess.run(
        [tesseract_cmd, "--list-langs"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return {line.strip() for line in result.stdout.splitlines()[1:] if line.strip()}


def _parse_artifact_name(stem: str) -> tuple[str, int]:
    profile, _, raw_variant = stem.rpartition("_")
    try:
        return profile, int(raw_variant)
    except ValueError:
        return stem, 0


def _write_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "language",
        "language_name",
        "tesseract_lang",
        "profile",
        "count",
        "mean_CER",
        "mean_WER",
        "mean_IoU",
        "mean_matched_ratio",
    ]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["language"], row["profile"]), []).append(row)

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for (language, profile), group in sorted(groups.items()):
            first = group[0]
            writer.writerow(
                {
                    "language": language,
                    "language_name": first["language_name"],
                    "tesseract_lang": first["tesseract_lang"],
                    "profile": profile,
                    "count": len(group),
                    "mean_CER": mean(row["CER"] for row in group),
                    "mean_WER": mean(row["WER"] for row in group),
                    "mean_IoU": mean(row["IoU"] for row in group),
                    "mean_matched_ratio": mean(row["matched_ratio"] for row in group),
                }
            )


if __name__ == "__main__":
    raise SystemExit(main())
