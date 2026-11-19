"""Render a small revision-bound Wikipedia pilot and build its local GT gallery."""

import argparse
from collections import Counter
from contextlib import redirect_stdout
from html import escape
import io
import json
from pathlib import Path

from bs4 import BeautifulSoup

from polydocbench.benchmark.gt_audit import GTAuditPlan, run_gt_audit
from polydocbench.benchmark.manifest import build_manifest, verify_manifest
from polydocbench.benchmark.pilot import prepare_pilot
from polydocbench.benchmark.render_snapshot import capture_render_snapshot
from polydocbench.noise import load_noise_config, pdf_to_noisy_dataset
from polydocbench.sources.snapshots import capture_wikipedia_source, verify_wikipedia_source


CASES = {
    "en": ("pythagorean_theorem", "Pythagorean_theorem", "research_illustrated"),
    "ru": ("rainbow", "%D0%A0%D0%B0%D0%B4%D1%83%D0%B3%D0%B0", "research_illustrated"),
    "fr": ("eiffel_tower", "Tour_Eiffel", "technical_report"),
    "de": ("si_prefix", "SI-Pr%C3%A4fix", "technical_report"),
    "es": ("solar_system", "Sistema_solar", "research_illustrated"),
    "it": ("rialto_bridge", "Ponte_di_Rialto", "simple_article"),
}
PROFILES = ["clean", "audit_rotate_positive", "medium_scan"]
MEDIA = {"table", "image", "formula"}


def select_pages(gt, limit):
    """Maximize distinct source media in the sample without looking at OCR."""
    groups = {page["page_number"]: set() for page in gt["pages"]}
    counts = {number: Counter() for number in groups}
    for item in gt["elements"]:
        number = item["bbox"]["page"]
        kind = item["type"]
        if kind in MEDIA and item["metadata"].get("role") != "block":
            continue
        counts[number][kind] += 1
        if kind in MEDIA:
            # Repeated table fragments should not monopolize the selection.
            groups[number].add((kind, item["metadata"]["source_index"]))
    selected, covered, seen_types = {}, set(), set()
    while groups and len(selected) < limit:
        def rank(number):
            media = groups[number]
            return (len({kind for kind, _ in media} - seen_types), len(media - covered),
                    min(counts[number]["text_line"], 20), -number)

        number = max(groups, key=rank)
        covered.update(groups[number])
        seen_types.update(kind for kind, _ in groups.pop(number))
        selected[number] = dict(counts[number])
    return dict(sorted(selected.items()))


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _html_inventory(path):
    root = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser").select_one(".mw-parser-output")
    return {label: len(root.select(selector)) for label, selector in {
        "tables": "table", "images": "img", "math_wrappers": ".mwe-math-element",
        "mathml_tags": "math", "video": "video", "audio": "audio", "iframes": "iframe",
    }.items()}


def _write_index(root, cases, audit):
    rows = []
    for case in cases:
        source = (f'<a href="{escape(case["revision_url"], quote=True)}">Wikipedia revision '
                  f'{case["revision_id"]}</a>') if "revision_id" in case else ""
        pages = ", ".join(f'{page}: ' + ", ".join(
            f'{counts.get(kind, 0)} {kind}' for kind in sorted(MEDIA)
        ) for page, counts in case.get("pages", {}).items())
        details = escape(case.get("error", f'{len(case.get("exclusions", []))} excluded parsed blocks'))
        if "render_ledger" in case:
            details += f' | <a href="{escape(case["render_ledger"], quote=True)}">Exclusions</a>'
        rows.append(f'<tr><td>{case["language"]}</td><td>{escape(case["article_id"])}<br>{source}</td>'
                    f'<td>{escape(case["template"])}</td><td>{escape(pages)}</td><td>{details}</td></tr>')
    audit_link = '<a href="audit/index.html">Open GT review gallery</a>' if audit else "No audit was generated."
    (root / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>PolyDocBench: Wikipedia GT pilot</title><style>'
        'body{font:16px system-ui;margin:32px auto;padding:0 18px;max-width:1160px;color:#202829}'
        'table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid #ccc;text-align:left;vertical-align:top;padding:9px}'
        'a{color:#196485}.scroll{overflow:auto}td{overflow-wrap:anywhere}</style>'
        '<h1>Wikipedia GT pilot</h1><p>Original Wikipedia content, PolyDocBench layout. No inserted figures or tables. '
        'Development only; human review and media rights approval are pending.</p>'
        f'<p>{audit_link} | <a href="report.json">Source, asset and exclusion details</a></p>'
        + (f'<p>{audit["selected_images"]} scans checked; {audit["automatic_error_findings"]} automatic errors. '
           f'{audit["manual_review_units"]} preview units available for human review.</p>' if audit else "")
        +
        '<p>Start with the clean scans, then compare the paired rotation and medium noise. Use the revision links '
        'for content checks. Raw HTML counts include navigation and fallback markup; they are not coverage denominators.</p>'
        '<div class="scroll"><table><thead><tr><th>Language</th><th>Article</th><th>Template</th>'
        '<th>Selected pages (media blocks)</th><th>Preparation</th></tr></thead><tbody>'
        + "".join(rows) + '</tbody></table></div></html>', encoding="utf-8",
    )


def build(root, *, pages_per_source=2, seed=42, dpi=160, revision_lock=None):
    root = root.resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("Pilot output must be new or empty")
    root.mkdir(parents=True, exist_ok=True)
    dataset = root / "dataset"
    dataset.mkdir()
    noise = load_noise_config("configs/gt_audit_noise.json")
    cases, revisions = [], {}
    for language, (article_id, title, template) in CASES.items():
        source_dir = dataset / language / article_id
        render_dir = source_dir / template
        case = {"language": language, "article_id": article_id, "template": template, "status": "failed"}
        cases.append(case)
        try:
            url = f"https://{language}.wikipedia.org/wiki/{title}"
            revision = revision_lock[language] if revision_lock is not None else None
            capture_wikipedia_source(url, source_dir, revision_id=revision, timeout=18)
            evidence = verify_wikipedia_source(source_dir, reparse=True).inputs
            revisions[language] = evidence.revision_id
            case.update(revision_id=evidence.revision_id, revision_url=evidence.permanent_url,
                        raw_html_inventory=_html_inventory(source_dir / "page.html"))
            with redirect_stdout(io.StringIO()):
                rendered = capture_render_snapshot(source_dir / "source.json", render_dir, template=template,
                                                   allow_downloads=True, wikipedia_pilot=True)
            ledger = render_dir / "inputs/source_selection.json"
            case.update(_read(ledger), render_ledger=ledger.relative_to(root).as_posix())
            case["sealed_graphics"] = _read(render_dir / "render_inputs.json")["assets"]
            pages = select_pages(_read(Path(rendered["gt_path"])), pages_per_source)
            case["pages"] = pages
            for page in pages:
                pdf_to_noisy_dataset(rendered["pdf_path"], rendered["gt_path"], render_dir / "noisy" / f"page_{page:03d}",
                                     page_index=page - 1, n_variants=1, dpi=dpi, seed=seed, profiles=PROFILES, config=noise)
            case["status"] = "generated"
            print(f"{language}/{article_id}: pages {list(pages)}, {len(case['exclusions'])} exclusions", flush=True)
        except (ValueError, OSError) as exc:
            case["error"] = str(exc)
            print(f"{language}/{article_id}: {exc}", flush=True)
        _write(root / "revisions.json", revisions)
        _write(root / "report.json", {"cases": cases, "status": "building"})
    manifest = build_manifest(dataset)
    (root / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    audit = None
    expected_pages = sum(len(c["pages"]) for c in cases if c["status"] == "generated")
    usable = (expected_pages and not manifest.issues and not verify_manifest(manifest, dataset)
              and len(manifest.records) == expected_pages * len(PROFILES))
    if usable:
        pilot = prepare_pilot(manifest, base_pages=expected_pages, seed=seed, split="unassigned", profiles=PROFILES)
        audit = run_gt_audit(GTAuditPlan.freeze(pilot), dataset, root / "audit")
    status = "generated_pending_review" if audit and not audit["automatic_error_findings"] and all(
        c["status"] == "generated" for c in cases
    ) else "needs_investigation"
    report = {"status": status, "rights_status": "pending_human_review", "profiles": PROFILES, "dpi": dpi, "seed": seed,
              "base_pages": expected_pages, "scan_records": len(manifest.records), "cases": cases, "audit": audit}
    _write(root / "report.json", report)
    _write_index(root, cases, audit)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    revisions = parser.add_mutually_exclusive_group()
    revisions.add_argument("--revision-lock", type=Path, default=Path("configs/wikipedia_gt_pilot_revisions.json"),
                           help="Revision IDs to capture (defaults to the checked-in pilot)")
    revisions.add_argument("--refresh-revisions", action="store_true", help="Capture latest and save their revision IDs")
    args = parser.parse_args()
    lock = None if args.refresh_revisions else _read(args.revision_lock)
    if lock is not None and (set(lock) != set(CASES) or any(type(i) is not int or i < 1 for i in lock.values())):
        parser.error("Expected one positive revision ID per pilot language")
    report = build(args.output_dir, revision_lock=lock)
    print(f"{report['status']}: {report['base_pages']} pages, {report['scan_records']} scans; {args.output_dir / 'index.html'}")
    return int(report["status"] != "generated_pending_review")


if __name__ == "__main__":
    raise SystemExit(main())
