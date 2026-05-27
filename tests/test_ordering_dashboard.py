from pathlib import Path

import pytest

from polydocbench.eval.ordering_dashboard import write_ordering_dashboard


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
