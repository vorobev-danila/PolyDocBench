from types import SimpleNamespace

from polydocbench.eval.matching import match_lines
from polydocbench.eval.quality import evaluate_ocr_quality
from scripts.analyze_wikipedia_ocr_sensitivity import class_counts, class_rates, diagnostic_cases


def line(identifier, text, x, width, y=0):
    return {"id": identifier, "text": text, "bbox": {"x": x, "y": y, "width": width, "height": 10}}


def prepare(eligible, excluded=()):
    return SimpleNamespace(gt_decisions=[{"id": p["id"], "eligible": True} for p in eligible]
                           + [{"id": p["id"], "eligible": False} for p in excluded])


def test_threshold_replays_full_penalty_and_class_diagnostics_without_reclassifying_insertions():
    gt = [line("h", "Heading", 0, 100), line("b", "Body", 0, 80, 20)]
    excluded = [line("c", "Ignored caption", 0, 70, 70)]
    predictions = [line("p", "HEADING", 0, 20), line("q", "Bodi", 0, 80, 20), line("r", "Extra words", 0, 80, 40)]
    classes = {"h": "heading", "b": "body_or_other", "c": "caption"}
    stats = []
    for threshold in (0.20, 0.30):
        metrics = evaluate_ocr_quality(gt, predictions, threshold)
        matches = match_lines(gt, predictions, threshold)
        counts, insertions = class_counts(prepare(gt, excluded), matches, predictions, classes, metrics)
        heading, caption, body = (class_rates(counts[k]) for k in ("heading", "caption", "body_or_other"))
        assert caption["eligible_fraction"] == 0
        assert caption["gt_attributed_CER"] is None
        assert body["matched_only_CER"] == body["gt_attributed_CER"] == 0.25
        stats.append((heading["line_recall"], heading["matched_only_CER"], metrics["char_errors"], insertions["unattributed_chars"]))
    assert stats == [(1.0, 0.0, 12, 11), (0.0, None, 26, 18)]


def test_spot_checks_distinguish_tight_boxes_merged_cells_and_possible_omission():
    gt = [line("a", "Title", 0, 100), line("b", "north", 0, 12, 20), line("c", "west", 16, 12, 20),
          line("d", "A missing phrase", 0, 100, 40)]
    predictions = [line("p", "TITLE", 0, 20), line("q", "north west", 0, 100, 20)]
    matches = match_lines(gt, predictions, 0.30)
    diagnostics = diagnostic_cases(matches, predictions, {"a": "heading", "b": "table_cell", "c": "table_cell", "d": "body_or_other"}, 0.30)
    assert diagnostics["exact_text_below_iou"][0]["iou"] == 0.20
    assert [p["id"] for p in diagnostics["merged_cell_text"][0]["gt"]] == ["b", "c"]
    assert diagnostics["possible_omission"][0]["gt"] == [gt[3]]
    assert all(m.prediction is None for m in matches)


def test_same_word_cannot_cover_two_gt_cells_in_merge_evidence():
    gt = [line("a", "zero", 0, 10), line("b", "zero", 15, 10)]
    predictions = [line("p", "zero", 0, 40)]
    matches = match_lines(gt, predictions, 0.30)
    diagnostics = diagnostic_cases(matches, predictions, {"a": "table_cell", "b": "table_cell"}, 0.30)
    assert not diagnostics["merged_cell_text"]
