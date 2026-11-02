from pathlib import Path

import pytest

from polydocbench.eval.ordering_dashboard import _group_means, _summary_rows, write_ordering_dashboard


pytest.importorskip("plotly")


def test_ordering_dashboard_contains_semantic_metrics(tmp_path: Path):
    rows = [
        {
            "language": "en",
            "template": "scientific_paper",
            "profile": "medium_scan",
            "ordered_WER": 0.2,
            "token_F1": 0.9,
            "kendall_tau": 0.8,
            "pairwise_accuracy": 0.9,
            "matched_block_ratio": 0.75,
        }
    ]
    output_path = tmp_path / "dashboard.html"

    write_ordering_dashboard(output_path, rows)
    html = output_path.read_text(encoding="utf-8")

    assert "PolyDocBench dots.ocr Ordering Dashboard" in html
    assert "Ordered WER by Language and Noise Profile" in html
    assert "medium_scan" in html


def test_ordering_dashboard_handles_no_observable_pairs(tmp_path: Path):
    rows = [{"language": "en", "template": "simple_article", "profile": "light_scan",
             "evaluation_protocol_version": "0.2", "ordered_WER": 0.0, "token_F1": 1.0,
             "kendall_tau": None, "pairwise_accuracy": None, "matched_block_ratio": 1.0,
             "order_pair_coverage": 0.0}]
    assert _group_means(rows, "language", ["en"], "pairwise_accuracy", "light_scan") == [None]
    assert _summary_rows(rows)[0]["valid_order_count"] == 0
    output_path = write_ordering_dashboard(tmp_path / "undefined.html", rows)
    html = output_path.read_text(encoding="utf-8")
    assert "N/A" in html.replace("\\u002f", "/")
    assert "Valid Order Samples" in html
    assert "protocol 0.2" in html


def test_ordering_dashboard_rejects_mixed_protocols(tmp_path: Path):
    with pytest.raises(ValueError, match="different evaluation protocols"):
        write_ordering_dashboard(tmp_path / "mixed.html", [{}, {"evaluation_protocol_version": "0.2"}])
