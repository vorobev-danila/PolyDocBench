from polydocbench.eval.geometry import bbox_iou
from polydocbench.eval.ordering import evaluate_ordering
from polydocbench.eval.quality import evaluate_ocr_quality
from polydocbench.eval.text_metrics import cer, wer


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
