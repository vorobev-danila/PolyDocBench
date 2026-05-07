"""Compatibility wrapper for the refactored Wikipedia parser.

The implementation now lives in ``polydocbench.sources.wikipedia``. This file
keeps the historical import path used by older scripts:

    from utils.wiki_parser import WikiParser
"""

from __future__ import annotations

import os
import sys
from typing import Any


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from polydocbench.sources.wikipedia import WikipediaParser


WikiParser = WikipediaParser


def test_wiki_formulas(url: str, output_path: str = "History_of_Russia.json") -> dict[str, Any]:
    """Small manual parser smoke test kept for backwards compatibility."""

    parser = WikiParser(debug=True)
    result = parser.parse_from_url(url)

    if "error" in result:
        print(f"Error: {result['error']}")
        return result

    parser.print_structure(result, max_depth=4)
    parser.save_to_file(result, output_path)
    print(f"Saved to {output_path}")
    return result


if __name__ == "__main__":
    test_wiki_formulas("https://simple.wikipedia.org/wiki/History_of_Russia")
