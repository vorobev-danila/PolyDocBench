"""Example script for parsing one Wikipedia page.

Prefer the CLI for day-to-day use:

    python -m polydocbench parse-wiki URL -o article.json
"""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from polydocbench.sources.wikipedia import WikipediaParser


url = "https://en.wikipedia.org/wiki/Linear_regression"
out = "linear_regression.json"

parser = WikipediaParser()
data = parser.parse_from_url(url)

if "error" in data:
    raise RuntimeError(data["error"])

parser.save_to_file(data, out)
print(data["title"], len(data["content"]), "saved to", out)
