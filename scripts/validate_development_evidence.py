"""Independently reconcile saved development counts, geometry and calibration pools."""

import argparse
from collections import Counter
import json
from pathlib import Path

from bs4 import BeautifulSoup

from polydocbench.benchmark.manifest import DatasetManifest, verify_manifest
from polydocbench.gt.audit_geometry import visible_polygon_fraction
from polydocbench.provenance import json_sha256


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate(root):
    root = root.resolve(strict=True)
    manifest = DatasetManifest.model_validate_json((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.issues or verify_manifest(manifest, root / "dataset"):
        raise ValueError("Development input fingerprints do not verify")
    spec = json.loads((root / "development_spec.json").read_text(encoding="utf-8"))
    selection = json.loads((root / "page_selection.json").read_text(encoding="utf-8"))["pages"]
    expected_pages = len(spec["sources"]) * len(spec["templates"])
    assert len(selection) == expected_pages
    assert len(manifest.records) == expected_pages * len(spec["profiles"])
    keys = Counter((r.language, r.article_id, r.template) for r in manifest.records)
    assert len(keys) == expected_pages and set(keys.values()) == {len(spec["profiles"])}
    checked, maximum = 0, 0.0
    for record in manifest.records:
        gt = json.loads((root / "dataset" / record.image_gt.path).read_text(encoding="utf-8"))
        for element in gt["elements"]:
            facts = element["metadata"]["geometry_visibility"]
            independent = visible_polygon_fraction(element["polygon"], record.width, record.height)
            maximum = max(maximum, abs(facts["visible_fraction"] - independent))
            checked += 1
    assert checked and maximum < 1e-8
    calibration = root / "calibration"
    pairs = rows(calibration / "paired_results.jsonl")
    aggregates = rows(calibration / "calibration_metrics.jsonl")
    tested = 0
    for aggregate in aggregates:
        candidates = [p for p in pairs if p["operation"] == aggregate["operation"]
                      and (aggregate["dimension"] == "overall" or p[aggregate["dimension"]] == aggregate["group"])]
        available = {p["base_page_id"] for p in candidates}
        complete = {key for key in available if all(p["paired"] for p in candidates if p["base_page_id"] == key)}
        level_pairs = [p for p in candidates if p["level"] == aggregate["level"] and p["base_page_id"] in complete]
        assert len(level_pairs) == aggregate["curve_pairs"]
        for label in ("clean", "noisy"):
            for key in ("char_errors", "word_errors", "gt_char_count", "gt_word_count", "num_gt_lines"):
                value = sum(p[f"{label}_metrics"][key] for p in level_pairs)
                assert value == aggregate[f"{label}_{key}"]
            for metric, errors, count in (("micro_CER", "char_errors", "gt_char_count"), ("micro_WER", "word_errors", "gt_word_count")):
                denominator = aggregate[f"{label}_{count}"]
                actual = aggregate[f"{label}_{errors}"] / denominator if denominator else None
                assert actual == aggregate[f"{label}_{metric}"]
        tested += 1
    ledgers = 0
    for row in rows(calibration / "run/results.jsonl"):
        if row["status"] != "success":
            continue
        ledger = json.loads((calibration / "run" / row["scope_path"]).read_text(encoding="utf-8"))
        predicted = json.loads((calibration / "run" / row["prediction_path"]).read_text(encoding="utf-8"))
        assert ledger["prediction_sha256"] == json_sha256({"predictions": predicted})
        assert len(ledger["gt"]) == row["metrics"]["scope_input_gt"]
        assert sum(d["eligible"] for d in ledger["gt"]) == row["metrics"]["scope_eligible_gt"]
        assert sum(d["ignored"] for d in ledger["predictions"]) == row["metrics"]["scope_ignored_predictions"]
        assert len(ledger["retained_prediction_indices"]) + row["metrics"]["scope_ignored_predictions"] == len(predicted)
        ledgers += 1
    scenario_rows, scenario_ledgers = 0, 0
    if (root / "scenarios/comparison.json").exists():
        comparison = json.loads((root / "scenarios/comparison.json").read_text(encoding="utf-8"))
        native = rows(root / "scenarios/run/results.jsonl")
        assert comparison["selected_images"] == len(native)
        assert comparison["successful_images"] == sum(r["status"] == "success" for r in native)
        # The locally checked run is complete; incomplete runs need cohort-aware reconciliation.
        if comparison["successful_images"] == comparison["selected_images"]:
            for aggregate in comparison["profiles"]:
                selected = [r["metrics"] for r in native if r["profile"] == aggregate["profile"]]
                errors = sum(r["char_errors"] for r in selected)
                denominator = sum(r["gt_char_count"] for r in selected)
                assert aggregate["char_errors"] == errors and aggregate["gt_char_count"] == denominator
                assert aggregate["micro_CER"] == errors / denominator
                scenario_rows += 1
        for row in native:
            if row["status"] != "success":
                continue
            ledger = json.loads((root / "scenarios/run" / row["scope_path"]).read_text(encoding="utf-8"))
            predicted = json.loads((root / "scenarios/run" / row["prediction_path"]).read_text(encoding="utf-8"))
            assert ledger["prediction_sha256"] == json_sha256({"predictions": predicted})
            assert sum(d["eligible"] for d in ledger["gt"]) == row["metrics"]["scope_eligible_gt"]
            scenario_ledgers += 1
    links = 0
    for relative in ("index.html", "audit/index.html", "calibration/dashboard.html"):
        page = root / relative
        soup = BeautifulSoup(page.read_text(encoding="utf-8"), "html.parser")
        for node in soup.select("a[href], img[src]"):
            value = node.get("href", node.get("src"))
            if not value or ":" in value or value.startswith("#"):
                continue
            target = (page.parent / value.split("#", 1)[0]).resolve()
            assert target.exists(), (relative, value)
            links += 1
    result = {"candidate_images_verified": len(manifest.records), "base_pages": expected_pages,
              "polygon_fractions_checked": checked, "max_fraction_error": maximum,
              "independently_pooled_aggregate_rows": tested, "scope_ledgers_reconciled": ledgers,
              "independently_pooled_scenario_rows": scenario_rows, "scenario_scope_ledgers_reconciled": scenario_ledgers,
              "local_links_checked": links, "human_approval": "not_granted_by_this_check"}
    (root / "independent_validation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    print(json.dumps(validate(parser.parse_args().input_dir), indent=2))
