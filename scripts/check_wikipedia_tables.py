"""Audit and render real Wikipedia articles and table-only regression probes."""

from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys

import requests

from polydocbench.document.normalize import flatten_source_content
from polydocbench.document.schema import validate_source_document
from polydocbench.document.tables import validate_table
from polydocbench.layout import LayoutEngine
from polydocbench.layout.ids import ElementIdGenerator
from polydocbench.layout.templates import list_template_names
from polydocbench.render import PDFRenderer
from polydocbench.sources.wikipedia import DEFAULT_USER_AGENT, WikipediaParser


ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "en_ascii": "https://en.wikipedia.org/wiki/ASCII",
    "ru_ascii": "https://ru.wikipedia.org/wiki/ASCII",
    "en_languages": "https://en.wikipedia.org/wiki/Comparison_of_programming_languages",
    "de_prefixes": "https://de.wikipedia.org/wiki/SI-Pr%C3%A4fix",
}


def audit_tables(source):
    tables = [item for item in flatten_source_content(source.get("content", [])) if item["type"] == "table"]
    audit = []
    for index, item in enumerate(tables, 1):
        record = {"index": index, "rows": len(item.get("rows", [])),
                  "extraction_warnings": item.get("extraction_warnings", []), "table_kind": item.get("table_kind", "data")}
        try:
            data = validate_table(item)
            cells, columns = data.grid()
            record.update({"columns": columns, "cells": len(cells), "header_rows": data.repeated_header_count(),
                           "merged_cells": sum(cell.cell.rowspan > 1 or cell.cell.colspan > 1 for cell in cells)})
        except ValueError as exc:
            record["error"] = str(exc)
        audit.append(record)
    return tables, audit


def validate_layout(result):
    errors = []
    elements = {element.id: element for element in result.elements}
    if len(elements) != len(result.elements):
        errors.append("Duplicate visible element IDs")
    tolerance = 0.05
    for element in result.elements:
        box = element.bbox
        page = result.pages[box.page - 1]
        if min(box.x, box.y, box.width, box.height) < -tolerance or (
            box.x + box.width > page.width + tolerance or box.y + box.height > page.height + tolerance
        ):
            errors.append(f"Element outside page: {element.id}")
        if element.type == "table_cell" or element.metadata.get("owner_type") == "table":
            parent = elements.get(element.metadata.get("parent_id"))
            if parent is None or parent.bbox.page != box.page:
                errors.append(f"Missing/page-mismatched parent: {element.id}")
            elif (box.x < parent.bbox.x - tolerance or box.y < parent.bbox.y - tolerance or
                  box.x + box.width > parent.bbox.x + parent.bbox.width + tolerance or
                  box.y + box.height > parent.bbox.y + parent.bbox.height + tolerance):
                errors.append(f"Element outside parent: {element.id}")
    for page in result.pages:
        for container in page.containers:
            if any(element.bbox.page != page.number for element in container.elements):
                errors.append(f"Container page mismatch: {page.number}/{container.id}")
    return errors


def render_probe(source_path, output_path, template, preview_pages):
    import fitz

    logs = io.StringIO()
    with contextlib.redirect_stdout(logs):
        result = LayoutEngine(font_path=ROOT / "DejaVu Sans/DejaVuSans.ttf").layout_document(source_path, template)
        rendered = PDFRenderer(debug=False).render(result, output_path)
    errors = validate_layout(result)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    items = flatten_source_content(source["content"]) if source.get("content") else source.get("elements", [])
    expected = set()
    for index, item in enumerate(items, 1):
        if item["type"] == "table":
            cells, _ = validate_table(item).grid()
            root_id = ElementIdGenerator().block_id("table", index)
            expected.update((root_id, cell.row, cell.column) for cell in cells)
    observed = {(element.metadata["table_id"], element.metadata["row_index"], element.metadata["column_index"])
                for element in result.elements if element.type == "table_cell"}
    if expected != observed:
        errors.append(f"Source/GT cell coverage mismatch: missing={len(expected - observed)}, extra={len(observed - expected)}")
    missing = []
    with fitz.open(output_path) as document:
        if len(document) != len(result.pages):
            errors.append("PDF/GT page counts differ")
        texts = ["".join(page.get_text().split()) for page in document]
        for element in result.elements:
            # PDF extraction may omit spaces between separately justified words.
            # This checks character preservation, not OCR CER/WER or word spacing.
            if element.type == "text_line" and "".join(element.content.split()) not in texts[element.bbox.page - 1]:
                missing.append({"id": element.id, "text": element.content, "page": element.bbox.page})
        table_pages = sorted({element.bbox.page - 1 for element in result.elements if element.type == "table"})
        candidates = list(dict.fromkeys([0, len(document) - 1] + table_pages))
        selected = sorted(candidates[:preview_pages])
        for index in selected:
            document[index].get_pixmap(matrix=fitz.Matrix(1.25, 1.25)).save(output_path.with_name(f"{output_path.stem}_page_{index + 1:03d}.png"))
    return {"status": "issues" if errors or missing or result.warnings else "ok", "template": template,
            "pdf_path": str(output_path), "gt_path": rendered["gt_path"], "pages": len(result.pages),
            "table_fragments": sum(element.type == "table" for element in result.elements),
            "cells": sum(element.type == "table_cell" for element in result.elements),
            "source_cells": len(expected), "unique_gt_cells": len(observed),
            "geometry_errors": errors, "missing_text_lines": len(missing), "missing_text_examples": missing[:10],
            "layout_warnings": result.warnings, "preview_page_numbers": [index + 1 for index in selected]}


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/validation/wiki_tables"))
    parser.add_argument("--cases", nargs="+", choices=list(CASES), default=list(CASES))
    parser.add_argument("--templates", nargs="+", choices=list_template_names(), default=["technical_report", "reference_sheet"])
    parser.add_argument("--max-tables", type=int, default=3, help="Probes per article; 0 means all valid tables")
    parser.add_argument("--preview-pages", type=int, default=4)
    parser.add_argument("--reuse-html", action="store_true", help="Use saved HTML, but reparse and rerender it")
    parser.add_argument("--parse-only", action="store_true")
    parser.add_argument("--tables-only", action="store_true", help="Render supported table probes without full articles; exclusions remain in the report")
    return parser


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args()
    if args.max_tables < 0 or args.preview_pages < 0:
        raise ValueError("Table/preview limits must be nonnegative")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "scope": "tables_only" if args.tables_only else "articles_and_tables", "cases": []}
    for case in args.cases:
        directory = args.output_dir / case
        directory.mkdir(parents=True, exist_ok=True)
        html_path, fetch_path = directory / "source.html", directory / "fetch.json"
        record = {"id": case, "url": CASES[case], "renders": []}
        report["cases"].append(record)
        try:
            if not args.reuse_html or not html_path.exists():
                response = requests.get(CASES[case], headers={"User-Agent": DEFAULT_USER_AGENT}, timeout=45)
                response.raise_for_status()
                html_path.write_bytes(response.content)
                fetch_path.write_text(json.dumps({"url": CASES[case], "resolved_url": response.url,
                    "status_code": response.status_code, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "html_sha256": hashlib.sha256(response.content).hexdigest()}, indent=2), encoding="utf-8")
            fetch = json.loads(fetch_path.read_text(encoding="utf-8"))
            if hashlib.sha256(html_path.read_bytes()).hexdigest() != fetch["html_sha256"]:
                raise ValueError("Cached HTML does not match its recorded checksum")
            source = WikipediaParser().parse_html(html_path.read_text(encoding="utf-8"), url=fetch["resolved_url"])
            if "error" in source:
                raise ValueError(source["error"])
            source_path = directory / "source.json"
            source_path.write_text(json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8")
            tables, audit = audit_tables(source)
            record.update({"title": source["title"], "fetch": fetch, "tables": audit})
            try:
                validate_source_document(source)
                record["source_valid"] = True
            except ValueError as exc:
                record["source_valid"] = False
                record["source_error"] = str(exc)
            print(f"{case}: tables={len(tables)}, valid={sum('error' not in item for item in audit)}", flush=True)
            if args.parse_only:
                continue
            candidates = [item for item in audit if "error" not in item and not item["extraction_warnings"]]
            candidates.sort(key=lambda item: (item["merged_cells"], item["rows"], item["columns"]), reverse=True)
            if args.max_tables:
                candidates = candidates[:args.max_tables]
            record["selected_table_indices"] = [item["index"] for item in candidates]
            record["excluded_table_indices"] = [item["index"] for item in audit if "error" in item or item["extraction_warnings"]]
            probes = [] if args.tables_only else [("article", source_path)]
            for item in candidates:
                name = f"table_{item['index']:03d}"
                path = directory / f"{name}.json"
                path.write_text(json.dumps({"title": source["title"], "url": source["url"],
                    "elements": [tables[item["index"] - 1]]}, ensure_ascii=False, indent=2), encoding="utf-8")
                probes.append((name, path))
            for name, path in probes:
                for template in args.templates:
                    output = directory / f"{name}_{template}.pdf"
                    try:
                        rendered = render_probe(path, output, template, args.preview_pages)
                    except Exception as exc:
                        rendered = {"status": "error", "error": str(exc), "error_type": type(exc).__name__, "template": template}
                    rendered["probe"] = name
                    record["renders"].append(rendered)
                    print(f"  {name}/{template}: {rendered['status']} {rendered.get('error', '')[:180]}", flush=True)
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            print(f"{case}: {record['error']}", flush=True)
        finally:
            (args.output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return int(any(case.get("error") or not case.get("source_valid", False) or
                   any(item["status"] != "ok" for item in case["renders"]) for case in report["cases"]))


if __name__ == "__main__":
    raise SystemExit(main())
