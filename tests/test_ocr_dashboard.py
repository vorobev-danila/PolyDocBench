from pathlib import Path

import pytest

from polydocbench.eval.dashboard import write_ocr_dashboard


pytest.importorskip("plotly")


def test_dashboard_contains_metric_views(tmp_path: Path):
    rows = [
        {
            "language": "en",
            "template": "simple_article",
            "profile": "light_scan",
            "CER": 0.1,
            "WER": 0.2,
            "IoU": 0.8,
            "matched_ratio": 0.9,
        },
        {
            "language": "ru",
            "template": "scientific_paper",
            "profile": "medium_scan",
            "CER": 0.3,
            "WER": 0.4,
            "IoU": 0.6,
            "matched_ratio": 0.7,
        },
    ]
    output_path = tmp_path / "dashboard.html"

    result = write_ocr_dashboard(output_path, rows)
    html = result.read_text(encoding="utf-8")

    assert result == output_path
    assert "PolyDocBench OCR Quality Dashboard" in html
    assert "CER by Language and Noise Profile" in html
    assert "scientific_paper" in html
    assert "medium_scan" in html


def test_dashboard_can_report_empty_experiment(tmp_path: Path):
    output_path = tmp_path / "dashboard.html"

    write_ocr_dashboard(output_path, [])

    assert "No experiment metrics were generated." in output_path.read_text(encoding="utf-8")
