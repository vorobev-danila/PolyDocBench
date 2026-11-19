"""Run and report a local Tesseract experiment on the frozen Wikipedia GT pilot."""

import argparse
from collections import defaultdict
import csv
import json
import os
from pathlib import Path
from urllib.parse import quote

from polydocbench.benchmark.gt_audit import GTAuditPlan
from polydocbench.benchmark.manifest import verify_manifest
from polydocbench.benchmark.pilot import PilotPlan, base_page_key
from polydocbench.benchmark.pilot_runtime import run_pilot
from polydocbench.eval.contract import FrozenEvaluation, load_evaluation_settings
from polydocbench.eval.geometry import bbox_iou
from polydocbench.eval.matching import match_lines
from polydocbench.eval.quality import aggregate_ocr_counts
from polydocbench.eval.scope import prepare_scope
from polydocbench.eval.scoped import scope_summary
from polydocbench.eval.text_metrics import edit_distance, normalize_text
from polydocbench.provenance import json_sha256


PROFILES = ("clean", "audit_rotate_positive", "medium_scan")
LABELS = dict(zip(PROFILES, ("Clean", "Fixed +3 degree rotation", "Medium scan")))
MEASURES = ("micro_CER", "micro_WER", "line_precision", "line_recall", "line_F1")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def relative_link(target, start):
    if target.resolve().drive != start.resolve().drive:
        return target.resolve().as_uri()
    return quote(Path(os.path.relpath(target, start)).as_posix(), safe="/.")


def paired_results(plan, results, references):
    """Pair by immutable base page and compare only identical eligible line text."""
    by_page = defaultdict(dict)
    for record in plan.selection.records:
        row = results[record.artifact_id]
        by_page[base_page_key(record)][record.profile] = row
    pairs, aggregate = [], []
    complete = []
    for group in by_page.values():
        clean = group["clean"]
        group_is_complete = True
        for profile in PROFILES[1:]:
            noisy = group[profile]
            c, n = clean.get("metrics"), noisy.get("metrics")
            both_scored = clean["status"] == noisy["status"] == "success" and c is not None and n is not None
            same = both_scored and references[clean["artifact_id"]] == references[noisy["artifact_id"]]
            status = "paired" if same and c["micro_CER"] is not None and n["micro_CER"] is not None else (
                "different_eligible_lines" if both_scored and not same else "unscored"
            )
            pair = {key: clean[key] for key in ("language", "article_id", "template", "source_page_number")}
            pair.update(profile=profile, status=status, clean_artifact_id=clean["artifact_id"],
                        noisy_artifact_id=noisy["artifact_id"], clean_status=clean["status"], noisy_status=noisy["status"])
            for key in (*MEASURES, "scope_input_gt", "scope_eligible_gt"):
                pair[f"clean_{key}"] = (c or {}).get(key)
                pair[f"noisy_{key}"] = (n or {}).get(key)
            for key in MEASURES:
                base, variant = pair[f"clean_{key}"], pair[f"noisy_{key}"]
                pair[f"delta_{key}"] = variant - base if status == "paired" and base is not None and variant is not None else None
            pairs.append(pair)
            group_is_complete &= status == "paired"
        if group_is_complete:
            complete.append(group)
    for profile in PROFILES:
        metrics = [g[profile]["metrics"] for g in complete]
        aggregate.append({"profile": profile, "selected_base_pages": len(by_page), "complete_base_pages": len(complete),
                          **aggregate_ocr_counts(metrics), **scope_summary(metrics)})
    return pairs, aggregate


def gt_line_class(line, elements):
    meta = line["metadata"]
    parent_type = elements.get(meta.get("parent_id"), {}).get("type", "")
    if meta.get("owner_type") == "table" or parent_type == "table_cell":
        return "table_cell"
    if parent_type == "caption":
        return "caption"
    return "heading" if parent_type.startswith("heading") else "body_or_other"


def clean_diagnostics(gt, prepared, kept, metrics, iou):
    matches = match_lines(prepared.gt, kept, iou_threshold=iou)
    by_id = {element["id"]: element for element in gt["elements"]}
    classes = defaultdict(lambda: {"gt_lines": 0, "matched_lines": 0, "gt_characters": 0,
                                   "matched_text_edits": 0, "unmatched_gt_characters": 0})
    used, examples = set(), []
    for match in matches:
        kind = gt_line_class(by_id[match.gt["id"]], by_id)
        text = normalize_text(match.gt["text"])
        counts = classes[kind]
        counts["gt_lines"] += 1
        counts["gt_characters"] += len(text)
        if match.prediction is not None:
            used.add(match.prediction_index)
            counts["matched_lines"] += 1
            edits = edit_distance(text, normalize_text(match.prediction["text"]))
            counts["matched_text_edits"] += edits
        else:
            edits = len(text)
            counts["unmatched_gt_characters"] += edits
        if edits:
            examples.append({"kind": kind, "gt": match.gt, "prediction": match.prediction,
                             "iou": match.iou, "errors": edits})
    insertions = [p for index, p in enumerate(kept) if index not in used]
    by_text = defaultdict(list)
    for line in insertions:
        by_text[normalize_text(line["text"])].append(line)
    below_iou = []
    for match in matches:
        text = normalize_text(match.gt["text"])
        if match.prediction is not None or not text or text not in by_text:
            continue
        overlap, candidate = max(((bbox_iou(match.gt["bbox"], p["bbox"]), p) for p in by_text[text]),
                                 key=lambda x: x[0])
        if 0 < overlap < iou:
            below_iou.append({"gt": match.gt, "prediction": candidate, "iou": overlap})
    unmatched_chars = sum(len(normalize_text(line["text"])) for line in insertions)
    matched_edits = sum(c["matched_text_edits"] for c in classes.values())
    missed_chars = sum(c["unmatched_gt_characters"] for c in classes.values())
    if matched_edits + missed_chars + unmatched_chars != metrics["char_errors"] or len(used) != metrics["num_matched_lines"]:
        raise ValueError("Clean diagnostics do not reproduce the inference ledger")
    return {"by_class": dict(classes), "matched_text_edits": matched_edits,
            "unmatched_gt_characters": missed_chars, "unmatched_prediction_characters": unmatched_chars,
            "exact_text_below_iou": below_iou,
            "largest_gt_line_errors": sorted(examples, key=lambda x: -x["errors"])[:5],
            "longest_unmatched_predictions": sorted(insertions, key=lambda x: -len(x["text"]))[:5]}


def load_verified_run(dataset, run, plan):
    if verify_manifest(plan.selection, dataset):
        raise ValueError("Frozen scan or source evidence changed")
    provenance, job = read_json(run / "run.json"), read_json(run / "job.json")
    contract = FrozenEvaluation.model_validate(job["config"]["evaluation_contract"])
    contract.verify_runtime()
    if (provenance["plan_id"] != plan.plan_id or PilotPlan.model_validate(job["plan"]) != plan
            or provenance["engine"] != "tesseract" or job["engine"] != "tesseract"
            or provenance["configuration_sha256"] != json_sha256(
                {"engine": "tesseract", "config": job["config"], "environment": provenance["environment"]})):
        raise ValueError("Inference plan/settings differ from the frozen GT audit or run ID")
    rows = [json.loads(line) for line in (run / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    results = {r["artifact_id"]: r for r in rows}
    if len(results) != len(rows) or set(results) != {r.artifact_id for r in plan.selection.records}:
        raise ValueError("Inference ledger is missing rows or contains duplicate/unexpected artifacts")

    for record in plan.selection.records:
        row = results[record.artifact_id]
        context = {key: getattr(record, key) for key in ("language", "article_id", "template", "source_page_number", "profile")}
        if any(row[key] != value for key, value in context.items()) or (
                row["plan_id"] != plan.plan_id or row["configuration_sha256"] != provenance["configuration_sha256"]):
            raise ValueError("Incompatible inference row")
    return contract, provenance, results


def verified_predictions(dataset, run, record, row, contract):
    counts = row["metrics"]
    if counts["evaluation_contract_id"] != contract.contract_id:
        raise ValueError("Metrics use a different evaluation contract")
    gt = read_json(dataset / record.image_gt.path)
    prediction = read_json(run / row["prediction_path"])
    saved_ledger = read_json(run / row["scope_path"])
    prepared = prepare_scope(gt, "quality", contract.settings.visibility_policy)
    kept, scope, coverage = prepared.filter_predictions(prediction)
    if json_sha256(saved_ledger) != json_sha256(scope) or any(counts[k] != v for k, v in coverage.items()):
        raise ValueError("Saved visibility evidence does not match the original prediction and GT")
    return gt, prepared, kept


def build_report(source, output, plan):
    dataset, run = source / "dataset", output / "run"
    contract, provenance, results = load_verified_run(dataset, run, plan)
    references, clean, per_image = {}, [], []
    for record in plan.selection.records:
        row = results[record.artifact_id]
        counts = row.get("metrics") if row["status"] == "success" else None
        per_image.append({key: value for key, value in row.items() if key != "metrics"} | (counts or {}))
        if counts is None:
            continue
        gt, prepared, kept = verified_predictions(dataset, run, record, row, contract)
        references[record.artifact_id] = json_sha256({"lines": sorted((line["id"], line["text"]) for line in prepared.gt)})
        if record.profile == "clean":
            diagnostic = clean_diagnostics(gt, prepared, kept, counts, contract.settings.quality_iou)
            clean.append({"artifact_id": record.artifact_id, "language": record.language, "article_id": record.article_id,
                          "page": record.source_page_number, "micro_CER": counts["micro_CER"],
                          "image": relative_link(dataset / record.image.path, output),
                          "image_gt": relative_link(dataset / record.image_gt.path, output),
                          "predictions": quote(f"run/{row['prediction_path']}", safe="/."),
                          **diagnostic})

    pairs, summary = paired_results(plan, results, references)
    write_csv(output / "images.csv", per_image)
    write_csv(output / "paired_pages.csv", pairs)
    write_csv(output / "summary.csv", summary)
    (output / "clean_diagnostics.json").write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    success = sum(row["status"] == "success" for row in results.values())
    write_summary(output, source, contract, provenance, summary, pairs, clean, success)
    return success, len(results)


def percent(value):
    return "n/a" if value is None else f"{value:.2%}"


def write_summary(output, source, contract, provenance, summary, pairs, clean, success):
    pages = summary[0]["selected_base_pages"]
    complete = summary[0]["complete_base_pages"]
    coverage = lambda r: f"{r['scope_eligible_gt']}/{r['scope_input_gt']}" if "scope_input_gt" in r else "n/a"
    lines = ["# Wikipedia OCR pilot", "",
             f"{success}/{pages * len(PROFILES)} runs succeeded. {complete}/{pages} base pages have comparable "
             "results in all conditions. This is a development sample, not held-out evaluation.", "",
             f"Engine: {provenance['environment']['tesseract_version']}; protocol 0.3; "
             f"line bbox IoU threshold {contract.settings.quality_iou}.", "",
             f"[GT gallery]({relative_link(source / 'audit/index.html', output)}) | [Run metadata](run/run.json) | "
             "[Per-image metrics](images.csv) | [Page pairs](paired_pages.csv) | "
             "[Clean diagnostic cases](clean_diagnostics.json)", "",
             "| Condition | Micro CER | Micro WER | Line precision | Line recall | Line F1 | Eligible / input lines | Ignored OCR lines |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in summary:
        lines.append("| " + " | ".join([LABELS[row["profile"]], *(percent(row[k]) for k in MEASURES),
                                       coverage(row), str(row.get("scope_ignored_predictions", "n/a"))]) + " |")
    lines += ["", "Micro rates pool error and reference counts. The table uses only pages with identical eligible "
              "GT line IDs and text in all three conditions; the pairing CSV also preserves failed or incomparable pairs. "
              "CER/WER include edits on matched lines and full costs for unmatched lines. Reading order and formulas "
              "are not scored as text objects; labels printed inside figures are untranscribed.", "",
              "## Paired changes from clean", "",
              "| Condition | Comparable pairs | CER worse / same / better | Pooled CER delta | Pooled WER delta |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for profile, row in zip(PROFILES[1:], summary[1:]):
        changes = [p["delta_micro_CER"] for p in pairs if p["profile"] == profile and p["delta_micro_CER"] is not None]
        deltas = [row[k] - summary[0][k] if row[k] is not None and summary[0][k] is not None else None
                  for k in ("micro_CER", "micro_WER")]
        cells = " | ".join("n/a" if value is None else f"{100 * value:+.2f} pp" for value in deltas)
        lines.append(f"| {LABELS[profile]} | {len(changes)}/{pages} | "
                     f"{sum(d > 0 for d in changes)} / {sum(d == 0 for d in changes)} / {sum(d < 0 for d in changes)} | {cells} |")
    lines += ["", "## Clean line matching", "",
              "These counts are diagnostic, not a second OCR engine. An unmatched line can come from missed "
              "text, different segmentation, or insufficient geometric overlap.", "",
              "| GT line class | Matched / eligible | Matched text edits | Characters on unmatched GT lines |",
              "| --- | ---: | ---: | ---: |"]
    for kind in sorted({kind for row in clean for kind in row["by_class"]}):
        c = [row["by_class"][kind] for row in clean if kind in row["by_class"]]
        totals = [sum(row[key] for row in c) for key in ("matched_lines", "gt_lines", "matched_text_edits", "unmatched_gt_characters")]
        lines.append(f"| {kind} | {totals[0]}/{totals[1]} | {totals[2]} | {totals[3]} |")
    lines += ["", f"Unmatched predictions contribute {sum(r['unmatched_prediction_characters'] for r in clean)} "
              "additional character errors; they are not attributed to a GT class.", "",
              f"On clean pages, {sum(len(r['exact_text_below_iou']) for r in clean)} unmatched GT lines have an "
              "overlapping unmatched OCR line with identical normalized text but below-threshold IoU. "
              "These candidates are evidence of metric sensitivity; no matches or scores were changed.", "",
              "### Highest clean CER", ""]
    for row in sorted((r for r in clean if r["micro_CER"] is not None), key=lambda r: -r["micro_CER"])[:3]:
        lines.append(f"- {row['language']}/{row['article_id']}, page {row['page']}: "
                     f"{percent(row['micro_CER'])}. [Scan]({row['image']}) / "
                     f"[GT]({row['image_gt']}) / [OCR]({row['predictions']}).")
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--evaluation-contract", type=Path, default=Path("configs/evaluation_publication.json"))
    parser.add_argument("--report-only", action="store_true", help="Reuse saved OCR predictions, without running Tesseract")
    args = parser.parse_args(argv)
    audit = GTAuditPlan.model_validate(read_json(args.input_dir / "audit/audit_plan.json"))
    plan = audit.pilot
    if set(plan.profiles) != set(PROFILES):
        parser.error("Expected the clean, fixed rotation and medium scan conditions")
    if not args.report_only:
        contract = load_evaluation_settings(args.evaluation_contract)
        run_pilot(plan, args.input_dir / "dataset", args.output_dir / "run", engine="tesseract",
                  config=contract.model_config_values(), timeout_per_image=120)
    successful, total = build_report(args.input_dir, args.output_dir, plan)
    print(f"{successful}/{total} successful; report: {args.output_dir / 'report.md'}")
    return int(successful != total)


if __name__ == "__main__":
    raise SystemExit(main())
