"""Portable audit gallery with explicit automatic and human-review denominators."""

import html
import json
import os
from pathlib import Path
from urllib.parse import quote


def write_gt_audit_report(output: Path, summary, documents, images, units, reviews, input_root: Path, pilot):
    escape = lambda value: html.escape(str(value), quote=True)
    review_map = {r.unit_id: r for r in reviews.reviews}
    image_map = {r["artifact_id"]: r for r in images}
    document_map = {r["document_id"]: r for r in documents}
    records = {r.artifact_id: r for r in pilot.selection.records}
    pdf_records = {r.pdf.path: r for r in pilot.selection.records}

    def input_link(path):
        absolute = input_root / path
        try:
            return quote(Path(os.path.relpath(absolute, output)).as_posix(), safe="/.")
        except ValueError:
            return absolute.as_uri()
    figures = []
    for unit in units:
        row = image_map[unit["artifact_id"]] if unit["kind"] == "scan" else document_map[unit["document_id"]]
        findings = row["result"]["findings"]
        errors = sum(f["severity"] == "error" for f in findings)
        warnings = len(findings) - errors
        clipped = sum(f["code"] in {"partially_clipped", "fully_clipped"} for f in findings)
        review = review_map[unit["unit_id"]]
        title = f"{unit['language']}/{unit['article_id']}/{unit['template']} / page {unit['source_page_number']} / {unit['profile']}"
        entries = "".join(f'<li><strong>{escape(f["severity"])} / {escape(f["code"])}</strong> '
                          f'page {escape(f.get("page"))}, {escape(f.get("element_id"))}: {escape(f["message"])}</li>'
                          for f in findings[:100])
        scope = "Full-document checks; this preview shows only the selected page." if unit["kind"] == "pdf_page" else "Selected scan checks."
        record = records[unit["artifact_id"]] if unit["kind"] == "scan" else pdf_records[row["pdf"]]
        original = record.image if unit["kind"] == "scan" else record.pdf
        gt = record.image_gt if unit["kind"] == "scan" else record.pdf_gt
        links = f'<p><a href="{escape(input_link(original.path))}">Full-resolution input</a> / <a href="{escape(input_link(gt.path))}">GT JSON</a></p>'
        figures.append(f'<figure data-language="{escape(unit["language"])}" data-template="{escape(unit["template"])}" '
                       f'data-profile="{escape(unit["profile"])}" data-errors="{errors}" data-warnings="{warnings}" '
                       f'data-clipped="{clipped}" data-review="{review.status}">'
                       f'<h3>{escape(title)}</h3><p class="status">{errors} automatic errors / {warnings} warnings; '
                       f'human review: <strong>{review.status}</strong></p>'
                       f'<div class="pair"><a href="{escape(unit["original"])}"><img src="{escape(unit["original"])}" alt="Original" loading="lazy"></a>'
                       f'<a href="{escape(unit["overlay"])}"><img src="{escape(unit["overlay"])}" alt="GT overlay" loading="lazy"></a></div>'
                       f'{links}<p class="meta">{escape(unit["unit_id"])}</p><p>{escape(scope)} '
                       'Red: text-line GT. Blue: blocks/cells. Polygons may extend outside the canvas.</p>'
                       f'<p>Reviewer: {escape(review.reviewer or "not assigned")}. {escape(review.notes)}</p>'
                       f'<details><summary>Findings ({len(findings)}; up to 100 shown)</summary><ul>{entries}</ul></details></figure>')
    selectors = []
    for key in ("language", "template", "profile"):
        options = '<option value="">All</option>' + "".join(f'<option value="{escape(v)}">{escape(v)}</option>' for v in sorted({u[key] for u in units}))
        selectors.append(f'<label>{key.title()}<select id="{key}">{options}</select></label>')
    page = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PolyDocBench GT Audit</title><style>
*{box-sizing:border-box}body{margin:0;font:15px system-ui,sans-serif;letter-spacing:0;color:#243136;background:#f7f9fa}
header,main{max-width:1500px;margin:auto;padding:24px}header{border-bottom:2px solid #197d78}h1{font-size:28px;margin:0 0 12px}
h2{font-size:21px}h3{font-size:16px;margin:0 0 10px;overflow-wrap:anywhere}p{line-height:1.5}a{color:#156eac}
nav,.controls{display:flex;flex-wrap:wrap;gap:18px;margin:18px 0}label{display:grid;gap:5px}select{font:inherit;padding:6px;max-width:100%}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}figure{min-width:0;margin:0;border-top:1px solid #bacbd0;padding:18px 0}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:8px}.pair img{width:100%;aspect-ratio:0.71;object-fit:contain;background:#e5ecee}
.meta{font:11px monospace;overflow-wrap:anywhere}.status{color:#405c66}li{overflow-wrap:anywhere;margin:8px 0}figure[hidden]{display:none}
.warning{border-left:3px solid #be8c28;padding-left:12px}details{font-size:13px}pre{white-space:pre-wrap;overflow-wrap:anywhere}
@media(max-width:800px){header,main{padding:14px}.grid{grid-template-columns:1fr}.controls label{width:100%}select{width:100%}}
</style></head><body>'''
    page += f'<header><h1>PolyDocBench GT Audit</h1><p>Protocol 0.1 / {escape(summary["split"])} split</p>'
    page += f'<p>{summary["documents_checked"]} complete GT documents ({summary["document_pages_checked"]} pages); '
    page += f'{summary["previewed_pdf_pages"]} PDF-page previews; {summary["selected_images"]} selected scans.</p>'
    page += f'<p>{summary["automatic_error_findings"]} automatic error findings / {summary["automatic_warning_findings"]} warnings. '
    statuses = ", ".join(f'{summary["manual_review_statuses"].get(status, 0)} {status}' for status in ("pending", "accepted", "defect"))
    page += f'Human review units: {summary["manual_review_units"]}; {statuses}.</p>'
    page += f'<p>{summary["checked_transform_elements"]} transformed elements checked; maximum coordinate error: '
    page += f'{escape(summary["maximum_coordinate_error_pixels"])} pixels. Geometric clipping: '
    page += f'{summary["partially_clipped_elements"]} partial / {summary["fully_clipped_elements"]} complete.</p>'
    page += '<p class="warning">Automatic consistency checks are not manual approval, pixel-accurate ink masks, or a rights/family review. '
    page += 'PDF text extraction is a diagnostic, not proof of visual alignment. Preview review does not cover unshown document pages. '
    page += 'Thumbnails are downscaled; full-resolution input links require the original dataset.</p>'
    page += '<nav><a href="summary.json">Summary</a><a href="audit_plan.json">Frozen plan</a><a href="document_results.jsonl">Document findings</a>'
    page += '<a href="image_results.jsonl">Scan findings</a><a href="reviews.json">Review template</a><a href="applied_reviews.json">Applied reviews</a>'
    page += '<a href="audit_evidence.json">Evidence hashes</a></nav></header><main><div class="controls">'
    page += "".join(selectors)
    page += '<label>Automatic findings<select id="findings"><option value="">All</option><option value="errors">Has errors</option>'
    page += '<option value="warnings">Has warnings</option><option value="clipped">Geometric clipping</option></select></label>'
    page += '<label>Human review<select id="review"><option value="">All</option><option>pending</option><option>accepted</option><option>defect</option></select></label></div>'
    page += f'<p id="visible"></p><div class="grid">{"".join(figures)}</div></main>'
    page += '''<script>
const names=['language','template','profile','findings','review'];
function filter(){let count=0;document.querySelectorAll('figure').forEach(figure=>{
 const keep=names.every(name=>{const value=document.getElementById(name).value;
  return !value||(name==='findings'?Number(figure.dataset[value])>0:figure.dataset[name]===value)});
 figure.hidden=!keep;if(keep)count++});document.getElementById('visible').textContent=count+' preview units shown';}
names.forEach(name=>document.getElementById(name).addEventListener('change',filter));filter();
</script></body></html>'''
    (output / "index.html").write_text(page, encoding="utf-8")
    (output / "applied_reviews.json").write_text(json.dumps(reviews.model_dump(mode="json"), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
