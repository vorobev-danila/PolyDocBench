"""Inspect scope coverage on frozen inputs; optional bounded local Tesseract smoke."""

import argparse
from collections import defaultdict
import html
import json
from pathlib import Path

from PIL import Image, ImageDraw

from polydocbench.benchmark.manifest import DatasetManifest, verify_manifest
from polydocbench.benchmark.pilot import prepare_pilot
from polydocbench.benchmark.pilot_runtime import run_pilot
from polydocbench.eval import extract_gt_lines, evaluate_ocr_quality, write_ocr_dashboard
from polydocbench.eval.scope import load_visibility_policy, prepare_scope
from polydocbench.eval.scoped import scope_summary
from polydocbench.gt.visibility import geometry_engine
from polydocbench.provenance import fingerprint_file


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")


def overlay(prepared, image_path, target):
    with Image.open(image_path) as bitmap:
        image = bitmap.convert("RGBA")
    geometry = prepared.ignored_geometry.difference(prepared.eligible_geometry)
    mask = Image.new("L", image.size)
    draw = ImageDraw.Draw(mask)
    polygons = list(geometry.geoms) if geometry.geom_type == "MultiPolygon" else [geometry]
    for polygon in polygons:
        if polygon.geom_type != "Polygon" or polygon.is_empty:
            continue
        draw.polygon(list(polygon.exterior.coords), fill=95)
        for interior in polygon.interiors:
            draw.polygon(list(interior.coords), fill=0)
    tint = Image.new("RGBA", image.size, (235, 145, 25, 0))
    tint.putalpha(mask)
    image = Image.alpha_composite(image, tint)
    draw = ImageDraw.Draw(image)
    geometry = prepared.eligible_geometry
    polygons = list(geometry.geoms) if geometry.geom_type == "MultiPolygon" else [geometry]
    for polygon in polygons:
        if polygon.geom_type == "Polygon" and not polygon.is_empty:
            draw.line(list(polygon.exterior.coords), fill="red", width=2)
    image = image.convert("RGB")
    image.thumbnail((1100, 1500))
    image.save(target)


def inspect(manifest_path, root, output, policy, *, tesseract=False, tesseract_cmd=None):
    inventory = DatasetManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    if inventory.issues or verify_manifest(inventory, root):
        raise ValueError("Inspection input integrity failed")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Inspection output must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    (output / "scopes").mkdir()
    (output / "previews").mkdir()
    save_json(output / "visibility_policy.json", policy.model_dump())
    save_json(output / "input_manifest.json", inventory.model_dump())
    coverage, previews = [], []
    for record in inventory.records:
        gt = json.loads((root / record.image_gt.path).read_text(encoding="utf-8"))
        for task in ("quality", "ordering", "structure"):
            prepared = prepare_scope(gt, task, policy)
            _, ledger, metrics = prepared.filter_predictions([])
            scope_path = output / "scopes" / f"{record.artifact_id}_{task}.json"
            save_json(scope_path, ledger)
            coverage.append({"record_type": "coverage_inspection_not_model_metrics", "artifact_id": record.artifact_id,
                             "language": record.language, "template": record.template, "profile": record.profile,
                             "scope_path": scope_path.relative_to(output).as_posix(), **metrics})
            if (task == "quality" and record.language == "en" and record.article_id == "complex_gt_audit"
                    and record.template == "technical_report" and record.source_page_number == 1
                    and record.profile in {"clean", "audit_shear"}):
                target = output / "previews" / f"{record.profile}.png"
                overlay(prepared, root / record.image.path, target)
                previews.append((record.profile, target.relative_to(output).as_posix()))
    (output / "coverage.jsonl").write_text("".join(json.dumps(r, allow_nan=False) + "\n" for r in coverage), encoding="utf-8")
    comparisons = []
    if tesseract:
        # Selection precedes scores: first text page per language plus one complex page.
        records = [r for r in inventory.records if r.source_page_number == 1 and r.profile in {"clean", "audit_shear"}
                   and (r.article_id == "text_gt_audit" or (r.language == "en" and r.article_id == "complex_gt_audit" and r.template == "technical_report"))]
        subset = DatasetManifest(discovered_count=len(records), records=records, issues=[], split_plan=inventory.split_plan)
        base_pages = len({(r.language, r.article_id, r.template) for r in records})
        pilot = prepare_pilot(subset, base_pages=base_pages, profiles=["clean", "audit_shear"], split="unassigned")
        save_json(output / "pilot_plan.json", pilot.model_dump())
        config = {"visibility_policy": policy.model_dump()}
        if tesseract_cmd:
            config["tesseract_cmd"] = tesseract_cmd
        run_pilot(pilot, root, output / "tesseract", engine="tesseract", config=config, timeout_per_image=120)
        results = [json.loads(line) for line in (output / "tesseract/results.jsonl").read_text().splitlines()]
        lookup = {r.artifact_id: r for r in records}
        scored, legacy = [], []
        for row in results:
            if row["status"] != "success":
                continue
            record = lookup[row["artifact_id"]]
            gt = json.loads((root / record.image_gt.path).read_text(encoding="utf-8"))
            predictions = json.loads((output / "tesseract" / row["prediction_path"]).read_text(encoding="utf-8"))
            old = evaluate_ocr_quality(extract_gt_lines(gt, 1), predictions)
            legacy.append({"artifact_id": record.artifact_id, **old})
            scored.append({"language": record.language, "template": record.template, "profile": record.profile, **row["metrics"]})
            comparisons.append({"artifact_id": record.artifact_id, "language": record.language,
                                "article_id": record.article_id, "template": record.template, "profile": record.profile,
                                "legacy_micro_CER": old["micro_CER"], "scoped_micro_CER": row["metrics"]["micro_CER"],
                                "gt_kept": row["metrics"]["scope_eligible_gt"], "gt_total": row["metrics"]["scope_input_gt"],
                                "ignored_predictions": row["metrics"]["scope_ignored_predictions"]})
        (output / "legacy_reference.jsonl").write_text("".join(json.dumps(r) + "\n" for r in legacy), encoding="utf-8")
        save_json(output / "paired_protocol_comparison.json", comparisons)
        write_ocr_dashboard(output / "tesseract_dashboard.html", scored)
    grouped = defaultdict(list)
    for row in coverage:
        grouped[(row["scope_task"], row["profile"])].append(row)
    # Coverage rows deliberately have no evaluation_protocol_version: no predictions were evaluated.
    table = []
    for (task, profile), rows in sorted(grouped.items()):
        total = sum(r["scope_input_gt"] for r in rows)
        kept = sum(r["scope_eligible_gt"] for r in rows)
        table.append(f'<tr><td>{html.escape(task)}</td><td>{html.escape(profile)}</td><td>{len(rows)}</td>'
                     f'<td>{kept}/{total}</td><td>{total-kept}</td></tr>')
    figures = "".join(f'<figure><h3>{html.escape(name)}</h3><a href="{path}"><img src="{path}" alt="{html.escape(name)} scope"></a></figure>' for name, path in previews)
    comparison_rows = "".join(f'<tr><td>{html.escape(r["language"]+"/"+r["article_id"]+"/"+r["profile"])}</td>'
                              f'<td>{r["legacy_micro_CER"]:.4f}</td><td>{r["scoped_micro_CER"] if r["scoped_micro_CER"] is not None else "n/a"}</td>'
                              f'<td>{r["gt_kept"]}/{r["gt_total"]}</td><td>{r["ignored_predictions"]}</td></tr>' for r in comparisons)
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PolyDocBench Visibility Policy</title><style>
*{box-sizing:border-box}body{margin:0;font:15px system-ui,sans-serif;letter-spacing:0;color:#263338;background:#f7f9fa}
header,main{max-width:1350px;margin:auto;padding:24px}header{border-bottom:2px solid #247d77}h1{font-size:27px}h2{font-size:21px}h3{font-size:16px}
table{border-collapse:collapse;width:100%}td,th{padding:9px;border-bottom:1px solid #cddadd;text-align:left;overflow-wrap:anywhere}
.scroll{overflow-x:auto}.previews{display:grid;grid-template-columns:1fr 1fr;gap:24px}figure{margin:0;min-width:0}img{width:100%;object-fit:contain}
p{line-height:1.5}a{color:#126f9b}nav{display:flex;gap:18px;flex-wrap:wrap}.warning{border-left:3px solid #c68d29;padding-left:12px}
@media(max-width:700px){header,main{padding:14px}.previews{grid-template-columns:1fr}}
</style><header><h1>PolyDocBench Visibility Policy</h1>'''
    page += f'<p>{len(inventory.records)} input scans; 3 task scopes. Policy {policy.policy_id[:12]}.</p>'
    page += '<p class="warning">Engineering inspection. Candidate policy, not publication approval. Coverage is not model accuracy. '
    page += 'Protocol score changes are not recognition improvements.</p><nav><a href="coverage.jsonl">Coverage rows</a>'
    page += '<a href="input_manifest.json">Frozen inputs</a><a href="visibility_policy.json">Policy</a>'
    if tesseract:
        page += '<a href="tesseract_dashboard.html">Tesseract protocol 0.3</a><a href="paired_protocol_comparison.json">Paired comparison</a>'
    page += '</nav></header><main><h2>Eligibility Coverage</h2><div class="scroll"><table><thead><tr><th>Task</th><th>Profile</th><th>Scans</th><th>GT kept/total</th><th>Excluded</th></tr></thead><tbody>'
    page += "".join(table) + '</tbody></table></div><h2>Quality Scope Previews</h2><p>Orange: effective ignored areas. Red: eligible GT. Previews are downscaled.</p><div class="previews">' + figures + '</div>'
    if comparisons:
        page += '<h2>Same Predictions, Different Protocols</h2><div class="scroll"><table><tr><th>Input</th><th>Legacy CER</th><th>Scoped CER</th><th>GT kept/total</th><th>Pred ignored</th></tr>'
        page += comparison_rows + '</table></div>'
    page += '</main></html>'
    (output / "index.html").write_text(page, encoding="utf-8")
    summary = {"input_scans": len(inventory.records), "coverage_rows": len(coverage), "policy_id": policy.policy_id,
               "geometry_engine": geometry_engine(), "tesseract_comparisons": len(comparisons),
               "publication_approval": "not_granted", "source_manifest": fingerprint_file(manifest_path.parent, manifest_path).model_dump()}
    save_json(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--visibility-policy", type=Path, default=Path("configs/evaluation_visibility.json"))
    parser.add_argument("--run-tesseract", action="store_true")
    parser.add_argument("--tesseract-cmd")
    args = parser.parse_args()
    print(json.dumps(inspect(args.manifest, args.input_dir, args.output_dir, load_visibility_policy(args.visibility_policy),
                             tesseract=args.run_tesseract, tesseract_cmd=args.tesseract_cmd), indent=2))
    print(f"Report: {args.output_dir / 'index.html'}")


if __name__ == "__main__":
    main()
