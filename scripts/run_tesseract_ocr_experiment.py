"""Run a multilingual Tesseract OCR quality experiment with PolyDocBench.

Pipeline:
    Wikipedia URL -> source JSON -> PDF + GT -> noisy scans + transformed GT
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
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any
from urllib.parse import quote

from polydocbench.noise import pdf_to_noisy_dataset
from polydocbench.eval import evaluate_ocr_quality, extract_gt_lines, load_gt, write_ocr_dashboard
from polydocbench.eval.ocr import extract_tesseract_lines
from polydocbench.layout import LayoutEngine
from polydocbench.render import PDFRenderer
from polydocbench.sources.wikipedia import WikipediaParser


@dataclass(frozen=True)
class ArticleCase:
    code: str
    tesseract_lang: str
    language_name: str
    article_id: str
    title: str
    url: str


LANGUAGE_NAMES = {
    "en": "English",
    "ru": "Russian",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "it": "Italian",
}

TESSERACT_LANGS = {
    "en": "eng",
    "ru": "rus",
    "fr": "fra",
    "de": "deu",
    "es": "spa",
    "it": "ita",
}

ARTICLE_TITLES = {
    "en": {
        "history_russia": "History_of_Russia",
        "linear_algebra": "Linear_algebra",
        "quantum_mechanics": "Quantum_mechanics",
        "literature": "William_Shakespeare",
        "cell_biology": "Cell_biology",
        "organic_chemistry": "Organic_chemistry",
        "climate": "Climate_change",
        "ai": "Artificial_intelligence",
        "kant": "Immanuel_Kant",
        "milky_way": "Milky_Way",
    },
    "ru": {
        "history_russia": "История_России",
        "linear_algebra": "Линейная_алгебра",
        "quantum_mechanics": "Квантовая_механика",
        "literature": "Толстой,_Лев_Николаевич",
        "cell_biology": "Клеточная_биология",
        "organic_chemistry": "Органическая_химия",
        "climate": "Глобальное_потепление",
        "ai": "Искусственный_интеллект",
        "kant": "Кант,_Иммануил",
        "milky_way": "Млечный_Путь",
    },
    "fr": {
        "history_russia": "Histoire_de_la_Russie",
        "linear_algebra": "Algèbre_linéaire",
        "quantum_mechanics": "Mécanique_quantique",
        "literature": "Victor_Hugo",
        "cell_biology": "Biologie_cellulaire",
        "organic_chemistry": "Chimie_organique",
        "climate": "Réchauffement_climatique",
        "ai": "Intelligence_artificielle",
        "kant": "Emmanuel_Kant",
        "milky_way": "Voie_lactée",
    },
    "de": {
        "history_russia": "Geschichte_Russlands",
        "linear_algebra": "Lineare_Algebra",
        "quantum_mechanics": "Quantenmechanik",
        "literature": "Johann_Wolfgang_von_Goethe",
        "cell_biology": "Zellbiologie",
        "organic_chemistry": "Organische_Chemie",
        "climate": "Globale_Erwärmung",
        "ai": "Künstliche_Intelligenz",
        "kant": "Immanuel_Kant",
        "milky_way": "Milchstraße",
    },
    "es": {
        "history_russia": "Historia_de_Rusia",
        "linear_algebra": "Álgebra_lineal",
        "quantum_mechanics": "Mecánica_cuántica",
        "literature": "Miguel_de_Cervantes",
        "cell_biology": "Biología_celular",
        "organic_chemistry": "Química_orgánica",
        "climate": "Cambio_climático",
        "ai": "Inteligencia_artificial",
        "kant": "Immanuel_Kant",
        "milky_way": "Vía_Láctea",
    },
    "it": {
        "history_russia": "Storia_della_Russia",
        "linear_algebra": "Algebra_lineare",
        "quantum_mechanics": "Meccanica_quantistica",
        "literature": "Dante_Alighieri",
        "cell_biology": "Biologia_cellulare",
        "organic_chemistry": "Chimica_organica",
        "climate": "Riscaldamento_globale",
        "ai": "Intelligenza_artificiale",
        "kant": "Immanuel_Kant",
        "milky_way": "Via_Lattea",
    },
}


def _build_article_cases() -> tuple[ArticleCase, ...]:
    cases = []
    for code, titles in ARTICLE_TITLES.items():
        for article_id, title in titles.items():
            cases.append(
                ArticleCase(
                    code=code,
                    language_name=LANGUAGE_NAMES[code],
                    tesseract_lang=TESSERACT_LANGS[code],
                    article_id=article_id,
                    title=title,
                    url=_wiki_url(code, title),
                )
            )
    return tuple(cases)


def _wiki_url(code: str, title: str) -> str:
    return f"https://{code}.wikipedia.org/wiki/{quote(title, safe='(),_')}"


ARTICLE_CASES = _build_article_cases()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run multilingual Tesseract OCR experiments.")
    parser.add_argument("--output-dir", default="outputs/experiments/tesseract_quality", help="Experiment output root")
    parser.add_argument(
        "--templates",
        nargs="+",
        default=["simple_article", "scientific_paper", "magazine_layout"],
        help="Layout templates to render",
    )
    parser.add_argument("--font", default="DejaVu Sans/DejaVuSans.ttf", help="Font path")
    parser.add_argument("--profiles", nargs="+", default=["light_scan", "medium_scan", "heavy_scan"], help="Noise profiles")
    parser.add_argument("--variants", type=int, default=1, help="Variants per noise profile")
    parser.add_argument("--dpi", type=int, default=200, help="PDF rendering DPI for noising")
    parser.add_argument("--seed", type=int, default=42, help="Noise random seed")
    parser.add_argument("--page-scope", choices=["first", "half", "all"], default="first", help="Rendered pages to evaluate")
    parser.add_argument("--iou-threshold", type=float, default=0.3, help="Line matching IoU threshold")
    parser.add_argument("--languages", nargs="+", default=list(LANGUAGE_NAMES), help="Language codes to run")
    parser.add_argument("--article-ids", nargs="+", default=None, help="Article IDs to run, for example: linear_algebra ai")
    parser.add_argument("--article-limit-per-language", type=int, default=3, help="Max articles per language; use 0 for all")
    parser.add_argument("--tesseract-cmd", default=None, help="Path to tesseract executable")
    parser.add_argument("--list-articles", action="store_true", help="Print the configured article pool and exit")
    parser.add_argument("--dashboard-only", action="store_true", help="Build dashboard.html from existing metrics.jsonl and exit")
    parser.add_argument("--no-dashboard", action="store_true", help="Do not generate the HTML dashboard after evaluation")
    parser.add_argument("--reuse", action="store_true", help="Reuse existing parsed/rendered/noisy artifacts when possible")
    parser.add_argument("--fail-on-missing-tesseract-lang", action="store_true", help="Fail instead of skipping missing Tesseract languages")
    parser.add_argument("--debug-render", action="store_true", help="Render debug bboxes into PDFs")
    parser.add_argument("--verbose-layout", action="store_true", help="Show internal layout engine logs")
    return parser


def main() -> int:
    _configure_console_encoding()
    args = build_parser().parse_args()
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    if args.list_articles:
        _print_articles()
        return 0

    metrics_path = output_root / "metrics.jsonl"
    summary_path = output_root / "summary.csv"
    dashboard_path = output_root / "dashboard.html"

    if args.dashboard_only:
        metrics_rows = _read_metrics(metrics_path)
        _write_summary(summary_path, metrics_rows)
        write_ocr_dashboard(dashboard_path, metrics_rows)
        print(f"Dashboard: {dashboard_path}")
        return 0

    cases = _select_cases(args.languages, args.article_ids, args.article_limit_per_language)
    tesseract_cmd = _resolve_tesseract_cmd(args.tesseract_cmd)
    if tesseract_cmd is None:
        raise RuntimeError(
            "Tesseract executable was not found. Install Tesseract or pass "
            "--tesseract-cmd \"C:\\Program Files\\Tesseract-OCR\\tesseract.exe\"."
        )
    _configure_pytesseract(tesseract_cmd)
    available_langs = _available_tesseract_languages(tesseract_cmd)

    metrics_rows: list[dict[str, Any]] = []

    with metrics_path.open("w", encoding="utf-8") as metrics_file:
        for case in cases:
            if case.tesseract_lang not in available_langs:
                message = f"Missing Tesseract language '{case.tesseract_lang}' for {case.code}"
                if args.fail_on_missing_tesseract_lang:
                    raise RuntimeError(message)
                print(f"SKIP {case.code}: {message}")
                continue

            print(f"\n== {case.code.upper()} | {case.article_id} | {case.language_name} ==")
            print(f"Title: {case.title}")
            print(f"URL: {case.url}")
            row_batch = _run_case(case, args, output_root)
            for row in row_batch:
                metrics_file.write(json.dumps(row, ensure_ascii=False) + "\n")
            metrics_rows.extend(row_batch)

    _write_summary(summary_path, metrics_rows)
    print(f"Metrics: {metrics_path}")
    print(f"Summary: {summary_path}")
    if not args.no_dashboard:
        write_ocr_dashboard(dashboard_path, metrics_rows)
        print(f"Dashboard: {dashboard_path}")
    return 0


def _run_case(case: ArticleCase, args: argparse.Namespace, output_root: Path) -> list[dict[str, Any]]:
    case_dir = output_root / case.code / case.article_id
    case_dir.mkdir(parents=True, exist_ok=True)

    source_path = case_dir / "source.json"
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

    rows: list[dict[str, Any]] = []
    for template_name in args.templates:
        rows.extend(_run_template_case(case, args, case_dir, source_path, template_name))

    return rows


def _run_template_case(
    case: ArticleCase,
    args: argparse.Namespace,
    case_dir: Path,
    source_path: Path,
    template_name: str,
) -> list[dict[str, Any]]:
    template_dir = case_dir / template_name
    template_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = template_dir / "document.pdf"
    gt_path = template_dir / "document_gt.json"
    dataset_root = template_dir / "noisy"
    predictions_root = template_dir / "predictions"

    print(f"\n-- Template: {template_name} --")

    if not args.reuse or not pdf_path.exists() or not gt_path.exists():
        print("[2/4] Render PDF + GT")
        font_path = Path(args.font)
        layout = _run_quietly(
            lambda: LayoutEngine(font_path=font_path if font_path.exists() else None).layout_document(
                source_path,
                template_name=template_name,
            ),
            quiet=not args.verbose_layout,
        )
        _run_quietly(lambda: PDFRenderer(debug=args.debug_render).render(layout, pdf_path), quiet=not args.verbose_layout)
        print(f"      pages={len(layout.pages)}, elements={len(layout.elements)}, pdf={pdf_path.name}, gt={gt_path.name}")
    else:
        print(f"[2/4] Render PDF + GT: reuse {pdf_path}, {gt_path}")

    page_count = _count_gt_pages(gt_path)
    page_indices = _select_page_indices(page_count, args.page_scope)
    print(f"      page_scope={args.page_scope}, selected_pages={[index + 1 for index in page_indices]}")

    print("[3/4] Generate noisy scans + transformed GT")
    generated_artifacts = 0
    for page_index in page_indices:
        page_dir = dataset_root / f"page_{page_index + 1:03d}"
        if args.reuse and page_dir.exists() and list(page_dir.glob("*_gt.json")):
            print(f"      page={page_index + 1}: reuse {page_dir}")
            continue
        noise_result = pdf_to_noisy_dataset(
            pdf_path=pdf_path,
            gt_path=gt_path,
            output_dir=page_dir,
            page_index=page_index,
            n_variants=args.variants,
            seed=args.seed + page_index,
            dpi=args.dpi,
            profiles=args.profiles,
        )
        generated_artifacts += len(noise_result["artifacts"])
        print(f"      page={page_index + 1}: artifacts={len(noise_result['artifacts'])}")
    if generated_artifacts:
        print(f"      generated_artifacts={generated_artifacts}, profiles={', '.join(args.profiles)}")

    print("[4/4] Run Tesseract + evaluate")
    rows: list[dict[str, Any]] = []
    for page_index in page_indices:
        page_number = page_index + 1
        page_dir = dataset_root / f"page_{page_number:03d}"
        predictions_dir = predictions_root / f"page_{page_number:03d}"
        predictions_dir.mkdir(parents=True, exist_ok=True)

        for artifact_gt_path in sorted(page_dir.glob("*_gt.json")):
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
                "language_name": case.language_name,
                "tesseract_lang": case.tesseract_lang,
                "article_id": case.article_id,
                "article_title": case.title,
                "source_url": case.url,
                "template": template_name,
                "page_number": page_number,
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
                f"      page={page_number} {image_path.stem}: "
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


def _select_cases(codes: list[str], article_ids: list[str] | None, limit_per_language: int) -> list[ArticleCase]:
    unknown = sorted(set(codes) - set(LANGUAGE_NAMES))
    if unknown:
        raise ValueError(f"Unknown language codes: {', '.join(unknown)}")

    selected = [case for case in ARTICLE_CASES if case.code in codes]
    if article_ids:
        unknown_articles = sorted(set(article_ids) - {case.article_id for case in ARTICLE_CASES})
        if unknown_articles:
            raise ValueError(f"Unknown article IDs: {', '.join(unknown_articles)}")
        selected = [case for case in selected if case.article_id in article_ids]

    if limit_per_language > 0:
        limited = []
        for code in codes:
            limited.extend([case for case in selected if case.code == code][:limit_per_language])
        selected = limited

    return selected


def _select_page_indices(page_count: int, page_scope: str) -> list[int]:
    if page_count < 1:
        return [0]
    if page_scope == "first":
        return [0]
    if page_scope == "half":
        count = max(1, (page_count + 1) // 2)
        return list(range(count))
    if page_scope == "all":
        return list(range(page_count))
    raise ValueError(f"Unknown page scope: {page_scope}")


def _count_gt_pages(gt_path: Path) -> int:
    data = json.loads(gt_path.read_text(encoding="utf-8"))
    return len(data.get("pages", []))


def _print_articles() -> None:
    print("code\ttesseract\tarticle_id\ttitle\turl")
    for case in ARTICLE_CASES:
        print(f"{case.code}\t{case.tesseract_lang}\t{case.article_id}\t{case.title}\t{case.url}")


def _configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


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


def _read_metrics(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Metrics file was not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def _write_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "language",
        "language_name",
        "tesseract_lang",
        "template",
        "profile",
        "article_count",
        "count",
        "mean_CER",
        "mean_WER",
        "mean_IoU",
        "mean_matched_ratio",
    ]
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["language"], row["template"], row["profile"]), []).append(row)

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for (language, template, profile), group in sorted(groups.items()):
            first = group[0]
            writer.writerow(
                {
                    "language": language,
                    "language_name": first["language_name"],
                    "tesseract_lang": first["tesseract_lang"],
                    "template": template,
                    "profile": profile,
                    "article_count": len({row["article_id"] for row in group}),
                    "count": len(group),
                    "mean_CER": mean(row["CER"] for row in group),
                    "mean_WER": mean(row["WER"] for row in group),
                    "mean_IoU": mean(row["IoU"] for row in group),
                    "mean_matched_ratio": mean(row["matched_ratio"] for row in group),
                }
            )


if __name__ == "__main__":
    raise SystemExit(main())
