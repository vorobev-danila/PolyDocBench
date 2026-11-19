from types import SimpleNamespace

from scripts.run_wikipedia_ocr_pilot import PROFILES, clean_diagnostics, paired_results


def make_pair():
    records, rows, references = [], {}, {}
    for index, profile in enumerate(PROFILES):
        records.append(SimpleNamespace(language="en", article_id="sample", source=SimpleNamespace(sha256="source"),
                                       template="technical_report", source_page_number=1, artifact_id=profile,
                                       profile=profile))
        rows[profile] = {"artifact_id": profile, "status": "success", "language": "en", "article_id": "sample",
                         "template": "technical_report", "source_page_number": 1,
                         "metrics": {"char_errors": index, "word_errors": index, "gt_char_count": 10,
                                     "gt_word_count": 2, "num_gt_lines": 1, "num_predicted_lines": 1,
                                     "num_matched_lines": 1, "micro_CER": index / 10}}
        references[profile] = "same_ids_and_text"
    return SimpleNamespace(selection=SimpleNamespace(records=records)), rows, references


def test_pairing_rejects_changed_line_identity_even_with_identical_counts():
    plan, rows, refs = make_pair()
    pairs, metrics = paired_results(plan, rows, refs)
    assert [p["delta_micro_CER"] for p in pairs] == [0.1, 0.2]
    assert [p["complete_base_pages"] for p in metrics] == [1, 1, 1]
    refs["medium_scan"] = "different_ids_same_count"
    pairs, metrics = paired_results(plan, rows, refs)
    assert pairs[1]["status"] == "different_eligible_lines"
    assert pairs[1]["delta_micro_CER"] is None
    assert all(r["complete_base_pages"] == 0 for r in metrics)
    assert all(r["micro_CER"] is None for r in metrics)


def test_pairing_reconciles_a_failed_scan_without_treating_it_as_zero_error():
    plan, rows, refs = make_pair()
    rows["medium_scan"].update(status="failed", metrics=None)
    del refs["medium_scan"]
    pairs, _ = paired_results(plan, rows, refs)
    assert pairs[0]["status"] == "paired"
    assert pairs[1]["status"] == "unscored"
    assert pairs[1]["noisy_micro_CER"] is None


def test_clean_same_text_below_threshold_is_diagnostic_not_a_match():
    gt = {"elements": [{"id": "headline", "type": "heading2"},
                       {"id": "line", "type": "text_line", "metadata": {"parent_id": "headline"}}]}
    line = {"id": "line", "text": "Title", "bbox": {"x": 0, "y": 0, "height": 20, "width": 100}}
    prediction = {"id": "p", "text": "TITLE", "bbox": {"x": 0, "y": 0, "height": 20, "width": 20}}
    diag = clean_diagnostics(gt, SimpleNamespace(gt=[line]), [prediction],
                             {"char_errors": 10, "num_matched_lines": 0}, iou=0.3)
    assert diag["by_class"]["heading"]["matched_lines"] == 0
    assert diag["unmatched_gt_characters"] == diag["unmatched_prediction_characters"] == 5
    assert diag["exact_text_below_iou"][0]["iou"] == 0.2
