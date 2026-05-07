import subprocess
import sys
from pathlib import Path


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
        "examples/wiki_formulas_isl.json",
        "-o",
        str(output_pdf),
        "--template",
        "simple_article",
    )

    assert output_pdf.exists()
    assert output_gt.exists()
