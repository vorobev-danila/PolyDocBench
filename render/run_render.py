"""Compatibility script for rendering a bundled example document.

The rendering pipeline now lives in :mod:`polydocbench`. This file remains as a
convenient entry point for users who previously launched ``render/run_render.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "examples" / "wiki_formulas.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "outputs" / "run_render.pdf"
DEFAULT_TEMPLATE = "magazine_layout"


def main() -> int:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from polydocbench.cli import main as cli_main

    return cli_main(
        [
            "render",
            str(DEFAULT_INPUT),
            "-o",
            str(DEFAULT_OUTPUT),
            "--template",
            DEFAULT_TEMPLATE,
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
