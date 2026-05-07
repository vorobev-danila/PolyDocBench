import json
from pathlib import Path

from polydocbench.api.services import evaluate_quality_from_gt, render_document


def test_api_render_service_renders_document():
    output_pdf = Path("outputs/test_runs/api_service_render.pdf")
    output_gt = Path("outputs/test_runs/api_service_render_gt.json")
    output_pdf.unlink(missing_ok=True)
    output_gt.unlink(missing_ok=True)

    result = render_document(
        json_path="examples/wiki_formulas_isl.json",
        output_pdf=output_pdf,
        template="simple_article",
        debug=False,
    )

    assert Path(result["pdf_path"]).exists()
    assert Path(result["gt_path"]).exists()
    assert result["page_count"] >= 1


def test_api_quality_service_uses_gt_file():
    gt_path = Path("outputs/test_runs/api_quality_gt.json")
    gt_path.parent.mkdir(parents=True, exist_ok=True)
    gt_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_number": 1,
                        "containers": [
                            {
                                "id": "main",
                                "elements": [
                                    {
                                        "id": "line_1",
                                        "type": "text_line",
                                        "content": "Hello world",
                                        "bbox": {"x": 0, "y": 0, "width": 100, "height": 10, "page": 1},
                                    }
                                ],
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    metrics = evaluate_quality_from_gt(
        gt_path=gt_path,
        predicted_lines=[{"id": "pred_1", "text": "Hello", "bbox": {"x": 0, "y": 0, "width": 100, "height": 10}}],
    )

    assert metrics["matched_ratio"] == 1.0
    assert metrics["WER"] == 0.5
