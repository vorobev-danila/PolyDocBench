import json
import subprocess
import sys
from pathlib import Path

from PIL import Image


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "polydocbench", *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_cli_lists_layout_templates():
    result = run_cli("list-templates")

    assert "simple_article" in result.stdout
    assert "scientific_paper" in result.stdout
    assert "magazine_layout" in result.stdout


def test_cli_renders_bundled_example():
    output_pdf = Path("outputs/test_runs/cli_render_smoke.pdf")
    output_gt = Path("outputs/test_runs/cli_render_smoke_gt.json")
    output_pdf.unlink(missing_ok=True)
    output_gt.unlink(missing_ok=True)

    run_cli(
        "render",
        "examples/wiki_formulas.json",
        "-o",
        str(output_pdf),
        "--template",
        "simple_article",
    )

    assert output_pdf.exists()
    assert output_gt.exists()


def test_cli_draws_gt_overlay_modes():
    output_dir = Path("outputs/test_runs")
    image_path = output_dir / "overlay_input.jpg"
    gt_path = output_dir / "overlay_input_gt.json"
    output_path = output_dir / "overlay_polygon.jpg"
    output_dir.mkdir(parents=True, exist_ok=True)

    Image.new("RGB", (80, 60), "white").save(image_path)
    gt_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "containers": [
                            {
                                "elements": [
                                    {
                                        "id": "line_1",
                                        "bbox": {"x": 10, "y": 10, "width": 30, "height": 12},
                                        "polygon": [[10, 10], [40, 10], [40, 22], [10, 22]],
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    run_cli(
        "draw-gt-overlay",
        str(image_path),
        str(gt_path),
        "-o",
        str(output_path),
        "--mode",
        "polygon",
    )

    assert output_path.exists()
