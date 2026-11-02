import pytest

from polydocbench.eval.geometry import bbox_iou
from polydocbench.eval.ordering import evaluate_ordering
from polydocbench.eval.quality import evaluate_ocr_quality
from polydocbench.eval.text_metrics import cer, wer
from polydocbench.eval.quality import aggregate_ocr_counts
from polydocbench.eval.ordering import evaluate_order_pairs, kendall_tau, pairwise_accuracy


def test_bbox_iou_partial_overlap():
    first = {"x": 0, "y": 0, "width": 10, "height": 10}
    second = {"x": 5, "y": 5, "width": 10, "height": 10}

    assert round(bbox_iou(first, second), 4) == 0.1429


def test_text_metrics():
    assert round(cer("abc", "axc"), 4) == 0.3333
    assert wer("hello world", "hello") == 0.5


def test_quality_metrics_use_unmatched_lines():
    gt = [{"id": "g1", "text": "Hello world", "bbox": {"x": 0, "y": 0, "width": 10, "height": 10}}]
    pred = [{"id": "p1", "text": "Hello", "bbox": {"x": 0, "y": 0, "width": 10, "height": 10}}]

    metrics = evaluate_ocr_quality(gt, pred)

    assert metrics["IoU"] == 1.0
    assert metrics["matched_ratio"] == 1.0
    assert metrics["WER"] == 0.5


def test_ordering_detects_column_order_errors():
    gt = [
        {"id": "left", "text": "left", "bbox": {"x": 0, "y": 0, "width": 10, "height": 10}, "container_id": "column_1"},
        {"id": "right", "text": "right", "bbox": {"x": 100, "y": 100, "width": 10, "height": 10}, "container_id": "column_2"},
    ]
    pred = [
        {"id": "p_right", "text": "right", "bbox": {"x": 100, "y": 100, "width": 10, "height": 10}},
        {"id": "p_left", "text": "left", "bbox": {"x": 0, "y": 0, "width": 10, "height": 10}},
    ]

    metrics = evaluate_ordering(gt, pred, num_columns=1)

    assert metrics["kendall_tau"] == -1.0
    assert metrics["pairwise_accuracy"] == 0.0


def _line(text, x=0):
    return {"id": str(x), "text": text, "bbox": {"x": x, "y": 0, "width": 10, "height": 10}}


def test_quality_penalizes_extra_predictions_without_changing_legacy_means():
    metrics = evaluate_ocr_quality([_line("hello")], [_line("hello"), _line("extra words", 20)])

    assert metrics["evaluation_protocol_version"] == "0.2"
    assert metrics["CER"] == metrics["macro_CER"] == 0.0
    assert metrics["WER"] == metrics["macro_WER"] == 0.0
    assert metrics["char_errors"] == len("extra words")
    assert metrics["word_errors"] == 2
    assert metrics["micro_CER"] == len("extra words") / 5
    assert metrics["micro_WER"] == 2.0
    assert metrics["false_positive_lines"] == 1
    assert metrics["false_negative_lines"] == 0
    assert metrics["line_precision"] == 0.5
    assert metrics["line_recall"] == 1.0
    assert metrics["line_F1"] == pytest.approx(2 / 3)


def test_quality_micro_weights_by_reference_length():
    metrics = evaluate_ocr_quality(
        [_line("a"), _line("bbbbbbbbb", 20)], [_line("x"), _line("bbbbbbbbb", 20)],
    )
    assert metrics["macro_CER"] == 0.5
    assert metrics["micro_CER"] == 0.1


def test_quality_missing_prediction_counts_deletions():
    metrics = evaluate_ocr_quality([_line("hello world")], [])
    assert metrics["char_errors"] == 11
    assert metrics["word_errors"] == 2
    assert metrics["micro_CER"] == metrics["micro_WER"] == 1.0
    assert metrics["false_negative_lines"] == 1
    assert metrics["line_F1"] == 0.0


def test_quality_empty_gt_still_counts_insertions():
    metrics = evaluate_ocr_quality([], [_line("hello world")])
    assert metrics["CER"] == 0.0
    assert metrics["micro_CER"] == 11.0
    assert metrics["micro_WER"] == 2.0
    assert metrics["false_positive_lines"] == 1
    assert metrics["gt_char_count"] == 0


def test_quality_empty_inputs_and_normalization():
    empty = evaluate_ocr_quality([], [])
    assert empty["micro_CER"] == empty["micro_WER"] == empty["line_F1"] == 0.0
    normalized = evaluate_ocr_quality([_line(" HELLO   World ")], [_line("hello world")])
    assert normalized["gt_char_count"] == 11
    assert normalized["gt_word_count"] == 2
    assert normalized["micro_CER"] == 0.0


def test_quality_counts_duplicate_prediction_instances_as_false_positives():
    prediction = _line("hello")
    metrics = evaluate_ocr_quality([_line("hello")], [prediction, prediction])
    assert metrics["num_matched_lines"] == 1
    assert metrics["false_positive_lines"] == 1
    assert metrics["micro_CER"] == 1.0


def test_quality_aggregation_pools_counts_not_page_rates():
    rows = [evaluate_ocr_quality([_line("a")], [_line("x")]),
            evaluate_ocr_quality([_line("bbbbbbbbb")], [_line("bbbbbbbbb")])]
    pooled = aggregate_ocr_counts(rows)
    assert pooled["micro_CER"] == 0.1
    assert pooled["char_errors"] == 1
    assert pooled["gt_char_count"] == 10
    assert aggregate_ocr_counts([{"CER": 0.1}])["micro_CER"] is None


@pytest.mark.parametrize("predicted", [[], ["a"], ["unknown"]])
def test_ordering_is_undefined_without_comparable_pairs(predicted):
    assert kendall_tau(["a", "b"], predicted) is None
    assert pairwise_accuracy(["a", "b"], predicted) is None


def test_order_pairs_exclude_unresolved_internal_group_order():
    metrics = evaluate_order_pairs(["a", "b", "c"], [["b", "a"], ["c"]])
    assert metrics["pairwise_accuracy"] == 1.0
    assert metrics["num_order_pairs"] == 2
    assert metrics["num_unresolved_pairs"] == 1
    assert metrics["order_pair_coverage"] == pytest.approx(2 / 3)


def test_order_pairs_report_inversions_and_ignore_unknown_ids():
    metrics = evaluate_order_pairs(["a", "b", "c"], [["c", "unknown"], ["a", "b"]])
    assert metrics["kendall_tau"] == -1.0
    assert metrics["num_correct_pairs"] == 0
    assert metrics["num_inverted_pairs"] == 2


@pytest.mark.parametrize("gt,groups", [(["a", "a"], [["a"]]), (["a", "b"], [["a"], ["a"]])])
def test_order_pairs_reject_duplicate_ids(gt, groups):
    with pytest.raises(ValueError, match="unique"):
        evaluate_order_pairs(gt, groups)
