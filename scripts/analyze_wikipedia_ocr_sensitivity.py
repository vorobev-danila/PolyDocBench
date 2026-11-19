"""Rescore a saved Wikipedia Tesseract pilot on a fixed bbox-IoU grid."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from polydocbench.benchmark.gt_audit import GTAuditPlan
from polydocbench.eval.geometry import bbox_iou
from polydocbench.eval.matching import match_lines
from polydocbench.eval.quality import evaluate_ocr_quality
from polydocbench.eval.text_metrics import edit_distance, normalize_text
from polydocbench.provenance import fingerprint_file, json_sha256
from scripts.run_wikipedia_ocr_pilot import (
    LABELS, PROFILES, gt_line_class, load_verified_run, paired_results, percent,
    read_json, relative_link, verified_predictions, write_csv,
)


IOU_GRID = (0.10, 0.20, 0.30, 0.40, 0.50)
CLASSES = ("body_or_other", "heading", "caption", "table_cell")
COUNTS = ("char_errors", "word_errors", "gt_char_count", "gt_word_count",
          "num_gt_lines", "num_predicted_lines", "num_matched_lines")
CLASS_COUNTS = ("matched_lines", "gt_chars", "gt_words", "matched_chars", "matched_words",
                "matched_char_edits", "matched_word_edits", "missing_chars", "missing_words")


def class_counts(prepared, matches, predictions, classes, metrics):
    counts = {kind: Counter({key: 0 for key in (*CLASS_COUNTS, "input_lines", "eligible_lines")}) for kind in CLASSES}
    for decision in prepared.gt_decisions:
        row = counts[classes[decision["id"]]]
        row["input_lines"] += 1
        row["eligible_lines"] += int(decision["eligible"])
    used = set()
    for match in matches:
        row = counts[classes[match.gt["id"]]]
        reference = normalize_text(match.gt["text"])
        words = reference.split()
        row.update(gt_chars=len(reference), gt_words=len(words))
        if match.prediction is None:
            row.update(missing_chars=len(reference), missing_words=len(words))
        else:
            got = normalize_text(match.prediction["text"])
            used.add(match.prediction_index)
            row.update(matched_lines=1, matched_chars=len(reference), matched_words=len(words),
                       matched_char_edits=edit_distance(reference, got), matched_word_edits=edit_distance(words, got.split()))
    unmatched = [normalize_text(p["text"]) for i, p in enumerate(predictions) if i not in used]
    insertions = {"unattributed_lines": len(unmatched), "unattributed_chars": sum(map(len, unmatched)),
                  "unattributed_words": sum(len(text.split()) for text in unmatched)}
    pooled = Counter()
    for row in counts.values():
        pooled.update(row)
    expected = (pooled["matched_char_edits"] + pooled["missing_chars"] + insertions["unattributed_chars"],
                pooled["matched_word_edits"] + pooled["missing_words"] + insertions["unattributed_words"],
                pooled["gt_chars"], pooled["gt_words"], pooled["eligible_lines"], len(predictions), pooled["matched_lines"])
    if tuple(metrics[key] for key in COUNTS) != expected:
        raise ValueError("Class counts do not reconcile with page-level evaluation")
    return counts, insertions


def class_rates(counts):
    def rate(n, d):
        return n / d if d else None

    return {
        "eligible_fraction": rate(counts["eligible_lines"], counts["input_lines"]),
        "line_recall": rate(counts["matched_lines"], counts["eligible_lines"]),
        "gt_attributed_CER": rate(counts["matched_char_edits"] + counts["missing_chars"], counts["gt_chars"]),
        "gt_attributed_WER": rate(counts["matched_word_edits"] + counts["missing_words"], counts["gt_words"]),
        "matched_only_CER": rate(counts["matched_char_edits"], counts["matched_chars"]),
        "matched_only_WER": rate(counts["matched_word_edits"], counts["matched_words"]),
    }


def diagnostic_cases(matches, predictions, classes, threshold):
    """Produce evidence for spot checks, never extra matches or score changes."""
    used = {m.prediction_index for m in matches if m.prediction_index is not None}
    text = [normalize_text(p["text"]) for p in predictions]
    exact, merges, missing = [], [], []
    for match in matches:
        if match.prediction is not None:
            continue
        ref = normalize_text(match.gt["text"])
        overlaps = [(bbox_iou(match.gt["bbox"], p["bbox"]), i) for i, p in enumerate(predictions)]
        exact_overlaps = [(score, i) for score, i in overlaps if 0 < score < threshold and i not in used and ref == text[i]]
        if exact_overlaps and ref:
            score, i = max(exact_overlaps, key=lambda item: item[0])
            exact.append({"gt": [match.gt], "predictions": [predictions[i]], "iou": score})
        if len(ref) >= 12 and not any(score > 0 for score, _ in overlaps) and not any(ref in t for t in text):
            missing.append({"gt": [match.gt], "predictions": []})
    for index, prediction in enumerate(predictions):
        cells = [m for m in matches if (m.prediction is None or m.prediction_index == index)
                 and classes[m.gt["id"]] == "table_cell" and bbox_iou(m.gt["bbox"], prediction["bbox"]) > 0]
        remaining = f" {text[index]} "
        included = []
        for match in sorted(cells, key=lambda m: m.gt["bbox"]["x"]):
            ref = normalize_text(match.gt["text"])
            offset = remaining.find(f" {ref} ")
            if ref and offset >= 0:
                included.append(match.gt)
                remaining = remaining[offset + len(ref) + 1:]
        if len(included) >= 2:
            merges.append({"gt": included, "predictions": [prediction]})
    return {"exact_text_below_iou": exact, "merged_cell_text": merges, "possible_omission": missing}


def build_sensitivity(source, prior, output):
    plan = GTAuditPlan.model_validate(read_json(source / "audit/audit_plan.json")).pilot
    dataset, run = source / "dataset", prior / "run"
    if set(plan.profiles) != set(PROFILES):
        raise ValueError("Expected the three frozen Wikipedia pilot conditions")
    contract, provenance, original = load_verified_run(dataset, run, plan)
    primary = contract.settings.quality_iou
    if primary not in IOU_GRID:
        raise ValueError("Saved IoU threshold must belong to the fixed sensitivity grid")
    rows = {threshold: {} for threshold in IOU_GRID}
    partitions, references, image_rows, examples = {}, {}, [], []
    for record in plan.selection.records:
        identifier = record.artifact_id
        saved = original[identifier]
        context = {key: saved[key] for key in ("artifact_id", "status", "language", "article_id", "template", "source_page_number", "profile")}
        if saved["status"] != "success":
            for threshold in IOU_GRID:
                rows[threshold][identifier] = saved
                image_rows.append(dict(context, iou_cutoff=threshold))
            continue
        gt, prepared, kept = verified_predictions(dataset, run, record, saved, contract)
        by_id = {e["id"]: e for e in gt["elements"]}
        classes = {d["id"]: gt_line_class(by_id[d["id"]], by_id) for d in prepared.gt_decisions}
        references[identifier] = json_sha256({"lines": sorted((line["id"], line["text"], classes[line["id"]]) for line in prepared.gt)})
        for threshold in IOU_GRID:
            metrics = evaluate_ocr_quality(prepared.gt, kept, iou_threshold=threshold)
            metrics.update({key: value for key, value in saved["metrics"].items() if key.startswith("scope_")})
            metrics["evaluation_protocol_version"] = contract.settings.evaluation_protocol_version
            if not prepared.gt:
                metrics = {key: None if isinstance(value, float) and not key.startswith("scope_")
                           and key != "matching_iou_threshold" else value for key, value in metrics.items()}
            if threshold == primary and any(saved["metrics"].get(k) != v for k, v in metrics.items()):
                raise ValueError(f"Primary replay differs from the saved scores for {identifier}")
            matches = match_lines(prepared.gt, kept, iou_threshold=threshold)
            counts, unmatched = class_counts(prepared, matches, kept, classes, metrics)
            partitions[threshold, identifier] = counts
            rows[threshold][identifier] = dict(context, metrics=metrics)
            image_rows.append(dict(context, iou_cutoff=threshold, **metrics, **unmatched))
            if threshold == primary and record.profile == "clean":
                e = diagnostic_cases(matches, kept, classes, primary)
                if any(e.values()):
                    examples.append(dict(context, **e, image=relative_link(dataset / record.image.path, output),
                                         predictions=relative_link(run / saved["prediction_path"], output)))

    paired, overall, by_class = [], [], []
    for threshold, scored in rows.items():
        pairs, summary = paired_results(plan, scored, references)
        # Only complete triples enter both the pooled and per-class tables.
        by_clean = defaultdict(list)
        for pair in pairs:
            by_clean[pair["clean_artifact_id"]].append(pair)
        complete = {identifier for clean, group in by_clean.items() if all(p["status"] == "paired" for p in group)
                    for identifier in [clean, *(p["noisy_artifact_id"] for p in group)]}
        paired.extend(dict(pair, iou=threshold, in_complete_cohort=pair["clean_artifact_id"] in complete) for pair in pairs)
        for pooled in summary:
            profile = pooled["profile"]
            identifiers = sorted(i for i in complete if scored[i]["profile"] == profile)
            if len(identifiers) != pooled["complete_base_pages"]:
                raise ValueError("Class and overall cohorts differ")
            totals = {kind: Counter() for kind in CLASSES}
            for identifier in identifiers:
                for kind, counts in partitions[threshold, identifier].items():
                    totals[kind].update(counts)
            for kind, counts in totals.items():
                by_class.append(dict(iou=threshold, profile=profile, gt_class=kind, **counts, **class_rates(counts)))
            unattributed = {}
            for metric, suffix in (("char_errors", "char"), ("word_errors", "word")):
                unattributed[f"unattributed_{suffix}s"] = (pooled[metric] - sum(c[f"matched_{suffix}_edits"] + c[f"missing_{suffix}s"]
                                                            for c in totals.values())) if identifiers else None
            overall.append(dict(iou=threshold, **pooled, **unattributed))

    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "overall.csv", overall)
    write_csv(output / "by_class.csv", by_class)
    write_csv(output / "per_image.csv", image_rows)
    write_csv(output / "paired_pages.csv", paired)
    save_json(output / "cases.json", examples)
    save_json(output / "provenance.json", {
        "plan_id": plan.plan_id, "quality_contract_id": contract.contract_id,
        "quality_protocol": contract.settings.evaluation_protocol_version,
        "primary_iou": primary, "diagnostic_iou_grid": IOU_GRID,
        "inference_configuration_sha256": provenance["configuration_sha256"],
        "inference_version": provenance["environment"]["tesseract_version"],
        "results_ledger": fingerprint_file(run, run / "results.jsonl").model_dump(),
        "verified_successes": len(references), "selected_scans": len(original),
    })
    write_report(output, overall, by_class, primary, len(references), len(original))


def save_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_report(output, overall, by_class, primary, successes, selected):
    table = ["# Wikipedia OCR matching sensitivity", "",
             f"Replayed {successes}/{selected} saved predictions without inference; the IoU {primary:.2f} replay matches the original ledger.",
             "Development data only. Visibility, normalization and greedy one-to-one assignment are unchanged; only the bbox-IoU cutoff varies.", "",
             "[Counts](overall.csv) | [By GT class](by_class.csv) | [Page pairs](paired_pages.csv) | "
             "[Per-image metrics](per_image.csv) | [Spot-check candidates](cases.json) | [Provenance](provenance.json)", "",
             "| IoU | Condition | Complete pages | Eligible / input GT | Ignored OCR | Micro CER | Micro WER | Line F1 | CER change vs clean |",
             "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    clean = {r["iou"]: r["micro_CER"] for r in overall if r["profile"] == "clean"}
    for row in overall:
        iou, cer = row["iou"], row["micro_CER"]
        delta = "n/a" if cer is None or clean[iou] is None else f"{100 * (cer - clean[iou]):+.2f} pp"
        coverage = f"{row['scope_eligible_gt']}/{row['scope_input_gt']}" if "scope_input_gt" in row else "n/a"
        table.append(f"| {iou:.2f} | {LABELS[row['profile']]} | {row['complete_base_pages']}/{row['selected_base_pages']} | "
                     f"{coverage} | {row.get('scope_ignored_predictions', 'n/a')} | {percent(cer)} | {percent(row['micro_WER'])} | "
                     f"{percent(row['line_F1'])} | {delta} |")
    table += ["", "The pooled cohort uses only complete triples with identical eligible GT IDs, text and class. "
              "The page-pair export also keeps failures and incompatible scopes. Unsupported regions (e.g. figure interiors) "
              "are not transcribed by the GT. This comparison does not isolate recognition from segmentation, or establish severity levels.", "",
              f"## GT classes at primary IoU {primary:.2f}", "",
              "| Condition | GT class | Matched / eligible | Eligible / input | GT-attributed CER | GT-attributed WER | Matched-only CER | Matched-only WER |",
              "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in by_class:
        if row["iou"] == primary:
            table.append(f"| {LABELS[row['profile']]} | {row['gt_class']} | {row.get('matched_lines', 0)}/{row.get('eligible_lines', 0)} | "
                         f"{row.get('eligible_lines', 0)}/{row.get('input_lines', 0)} | " + " | ".join(percent(row[k]) for k in
                         ("gt_attributed_CER", "gt_attributed_WER", "matched_only_CER", "matched_only_WER")) + " |")
    table += ["", "GT-attributed rates count matched edits and missed GT text. They do not include unattributed insertions, "
              "which remain in the overall score and are exported separately. Tesseract does not label predictions with GT classes, "
              "so per-class precision and F1 are undefined. Matched-only rates condition on successful matches and can understate errors.", ""]
    (output / "report.md").write_text("\n".join(table), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True, help="Audited Wikipedia GT pilot root")
    parser.add_argument("--ocr-run-dir", type=Path, required=True, help="Previous OCR output directory containing run/")
    parser.add_argument("--output-dir", type=Path, required=True, help="Separate directory for sensitivity results")
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    for path in (args.input_dir, args.ocr_run_dir):
        original = path.resolve()
        if output == original or output.is_relative_to(original) or original.is_relative_to(output):
            parser.error("Keep sensitivity results separate from the audited inputs and the original OCR run")
    build_sensitivity(args.input_dir, args.ocr_run_dir, args.output_dir)
    print(f"Sensitivity report: {args.output_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
