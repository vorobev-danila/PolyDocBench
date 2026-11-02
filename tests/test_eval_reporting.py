import csv

import pytest

from polydocbench.eval.protocol import result_protocol_version
from polydocbench.eval.quality import evaluate_ocr_quality
from polydocbench.eval.reporting import format_metric, mean_available
from scripts.run_dotsocr_ordering_experiment import _write_summary as write_ordering_summary
from scripts.run_tesseract_ocr_experiment import _write_summary as write_quality_summary


def test_optional_metric_reporting():
    assert mean_available([None, 0.0, 1.0]) == 0.5
    assert mean_available([None]) is None
    assert format_metric(None) == "N/A"
    assert format_metric(0.0, 3) == "0.000"


def test_protocol_versions_are_not_silently_mixed():
    assert result_protocol_version([{}]) == "legacy"
    assert result_protocol_version([{"evaluation_protocol_version": "0.2"}]) == "0.2"
    with pytest.raises(ValueError, match="different evaluation protocols"):
        result_protocol_version([{}, {"evaluation_protocol_version": "0.2"}])


def test_quality_csv_uses_pooled_micro_counts(tmp_path):
    def row(text, prediction):
        bbox = {"x": 0, "y": 0, "width": 10, "height": 10}
        return {"language": "en", "language_name": "English", "tesseract_lang": "eng",
                "article_id": text, "template": "simple_article", "profile": "light_scan",
                **evaluate_ocr_quality([{"text": text, "bbox": bbox}], [{"text": prediction, "bbox": bbox}])}

    path = tmp_path / "summary.csv"
    write_quality_summary(path, [row("a", "x"), row("bbbbbbbbb", "bbbbbbbbb")])
    with path.open(encoding="utf-8", newline="") as file:
        summary = next(csv.DictReader(file))
    assert float(summary["mean_CER"]) == 0.5
    assert float(summary["micro_CER"]) == 0.1
    assert summary["evaluation_protocol_version"] == "0.2"


def test_ordering_csv_excludes_undefined_scores_but_reports_valid_count(tmp_path):
    base = {"language": "en", "model": "test", "article_id": "a", "template": "simple_article",
            "profile": "light_scan", "evaluation_protocol_version": "0.2",
            "ordered_CER": 0.1, "ordered_WER": 0.2, "token_F1": 0.9, "matched_block_ratio": 1.0}
    rows = [{**base, "kendall_tau": None, "pairwise_accuracy": None, "num_order_pairs": 0, "order_pair_coverage": 0.0},
            {**base, "kendall_tau": -1.0, "pairwise_accuracy": 0.0, "num_order_pairs": 1, "order_pair_coverage": 1.0}]
    path = tmp_path / "summary.csv"
    write_ordering_summary(path, rows)
    with path.open(encoding="utf-8", newline="") as file:
        summary = next(csv.DictReader(file))
    assert summary["count"] == "2"
    assert summary["valid_order_count"] == "1"
    assert summary["mean_pairwise_accuracy"] == "0.0"
    assert summary["num_order_pairs"] == "1"


@pytest.mark.parametrize("writer", [write_quality_summary, write_ordering_summary])
def test_csv_rejects_mixed_protocols_before_writing(tmp_path, writer):
    path = tmp_path / "summary.csv"
    with pytest.raises(ValueError, match="different evaluation protocols"):
        writer(path, [{}, {"evaluation_protocol_version": "0.2"}])
    assert not path.exists()
