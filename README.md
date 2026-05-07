# PolyDocBench

Synthetic document generation and evaluation toolkit for OCR, document layout,
ground-truth extraction, and reading-order research.

## Project Layout

```text
polydocbench/
  sources/       # Wikipedia parsing and future source adapters
  document/      # Canonical document data model
  layout/        # Public layout API; currently wraps the legacy backend
  render/        # PDF rendering, fonts, debug rendering, element renderers
  gt/            # Ground-truth schema, exporters, validators
  degradation/   # Synthetic scan/noise generation
  eval/          # OCR quality and reading-order metrics
  cli.py         # Command line interface

configs/         # Canonical config files
examples/        # Small examples and fixtures
notebooks/       # Exploratory notebooks
outputs/         # Generated files, ignored by git
render/          # Legacy compatibility wrappers
scripts/         # Small manual examples
tests/           # Pytest tests
```

The old `render/` package is still present as a compatibility layer. New code
should import from `polydocbench`.

## Public API

Use `polydocbench` for new code:

```python
from polydocbench.sources import WikipediaParser
from polydocbench.layout import LayoutEngine
from polydocbench.render import PDFRenderer
```

Legacy imports from `render.*`, `layout_engine.*`, and `render.render.*` are
kept only so older scripts continue to run during the migration.

## Common Commands

Parse a Wikipedia page:

```powershell
.\.venv\Scripts\python.exe -m polydocbench parse-wiki "https://simple.wikipedia.org/wiki/History_of_Russia" -o outputs\history_of_russia.json
```

List layout templates:

```powershell
.\.venv\Scripts\python.exe -m polydocbench list-templates
```

Render parsed JSON:

```powershell
.\.venv\Scripts\python.exe -m polydocbench render outputs\history_of_russia.json -o outputs\history_of_russia.pdf --template simple_article
```

Render a bundled example:

```powershell
.\.venv\Scripts\python.exe -m polydocbench render examples\wiki_formulas_isl.json -o outputs\wiki_formulas_isl.pdf --template simple_article
```

Image blocks can reference local files or remote image URLs:

```json
{
  "type": "image",
  "src": "examples/assets/sample.png",
  "width": 240,
  "height": 160,
  "caption": "Sample image"
}
```

Formula blocks can use the same rendering path through an image fallback:

```json
{
  "type": "formula",
  "image_src": "examples/assets/formula.png",
  "latex": "x^2 + y^2 = z^2",
  "width": 180,
  "height": 48
}
```

SVG formula rendering, used by many Wikipedia math images, requires the
optional formula dependency:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[formula]"
```

Compatibility script for older workflows:

```powershell
.\.venv\Scripts\python.exe render\run_render.py
```

Run tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

## FastAPI

Install API dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[api]"
```

Start the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn polydocbench.api.app:app --reload --host 127.0.0.1 --port 8000
```

Open the interactive docs:

```text
http://127.0.0.1:8000/docs
```

Initial endpoints:

- `GET /health`
- `GET /templates`
- `POST /parse/wikipedia`
- `POST /render`
- `POST /evaluate/quality`
- `POST /evaluate/ordering`
