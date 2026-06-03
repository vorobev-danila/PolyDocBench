from pathlib import Path

import pytest

from polydocbench.eval import write_structure_dashboard


pytest.importorskip("plotly")


def test_structure_dashboard_contains_expected_metrics(tmp_path: Path):
    rows = [
        {
            "language": "en",
            "template": "simple_article",
            "profile": "light_scan",
            "structure_score": 0.8,
            "detection_F1": 0.9,
            "type_accuracy": 0.7,
            "mean_iou": 0.8,
        }
    ]
    output_path = tmp_path / "dashboard.html"

    write_structure_dashboard(output_path, rows)
    html = output_path.read_text(encoding="utf-8")

    assert "PolyDocBench Structure Evaluation Dashboard" in html
    assert "Structure Score by Language and Noise Profile" in html
    assert "simple_article" in html


def test_structure_dashboard_handles_empty_rows(tmp_path: Path):
    output_path = tmp_path / "dashboard.html"

    write_structure_dashboard(output_path, [])

    assert "No structure metrics were generated." in output_path.read_text(encoding="utf-8")
