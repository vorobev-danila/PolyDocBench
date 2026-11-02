from pathlib import Path

import pytest

from polydocbench.eval.dashboard import _group_means, write_ocr_dashboard
from polydocbench.eval.quality import evaluate_ocr_quality


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


def test_dashboard_pools_micro_counts_and_shows_new_protocol(tmp_path: Path):
    bbox = {"x": 0, "y": 0, "width": 10, "height": 10}
    base = {"language": "en", "template": "simple_article", "profile": "light_scan"}
    rows = [{**base, **evaluate_ocr_quality([{"text": gt, "bbox": bbox}], [{"text": pred, "bbox": bbox}])}
            for gt, pred in [("a", "x"), ("bbbbbbbbb", "bbbbbbbbb")]]
    assert _group_means(rows, "language", ["en"], "micro_CER", "light_scan") == [0.1]
    output = write_ocr_dashboard(tmp_path / "micro.html", rows)
    html = output.read_text(encoding="utf-8")
    assert "Micro CER by Language" in html
    assert "Line F1" in html
    assert "protocol 0.2" in html


def test_dashboard_rejects_mixed_protocols(tmp_path: Path):
    with pytest.raises(ValueError, match="different evaluation protocols"):
        write_ocr_dashboard(tmp_path / "mixed.html", [{}, {"evaluation_protocol_version": "0.2"}])
