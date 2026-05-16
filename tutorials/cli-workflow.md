# CLI and Python Workflow

This tutorial shows the local workflow:

```text
parse -> render -> degrade -> evaluate
```

Parsing and rendering are exposed through the CLI. Degradation and evaluation
can be used from Python or through the FastAPI workflow.

## List Templates

```powershell
uv run python -m polydocbench list-templates
```

## Parse a Wikipedia Page

```powershell
uv run python -m polydocbench parse-wiki "https://simple.wikipedia.org/wiki/History_of_Russia" -o outputs\history_of_russia.json
```

## Render PDF and Ground Truth

```powershell
uv run python -m polydocbench render outputs\history_of_russia.json -o outputs\history_of_russia.pdf --template scientific_paper --debug
```

The renderer writes:

- `outputs/history_of_russia.pdf`
- `outputs/history_of_russia_gt.json`

## Render a Bundled Example

```powershell
uv run python -m polydocbench render examples\wiki_formulas_isl.json -o outputs\wiki_formulas_isl.pdf --template simple_article
```

## Generate Noisy Scan Variants

```python
from polydocbench.degradation import pdf_to_noisy_images

result = pdf_to_noisy_images(
    pdf_path="outputs/history_of_russia.pdf",
    output_dir="outputs/history_of_russia_scans",
    page_index=0,
    n_variants=1,
    dpi=200,
    profiles=["light_scan", "medium_scan"],
)

print(result["images"])
```

Generate paired noisy images and transformed pixel-coordinate GT:

```python
from polydocbench.degradation import pdf_to_noisy_dataset

result = pdf_to_noisy_dataset(
    pdf_path="outputs/history_of_russia.pdf",
    gt_path="outputs/history_of_russia_gt.json",
    output_dir="outputs/history_of_russia_dataset",
    page_index=0,
    n_variants=1,
    dpi=200,
    profiles=["medium_scan"],
)

print(result["artifacts"])
```

Available profiles:

- `light_scan`
- `medium_scan`
- `heavy_scan`

## Render from Python

```python
from polydocbench.layout import LayoutEngine
from polydocbench.render import PDFRenderer

layout = LayoutEngine(font_path="DejaVu Sans/DejaVuSans.ttf").layout_document(
    "examples/wiki_formulas_isl.json",
    template_name="simple_article",
)

PDFRenderer(debug=True).render(layout, "outputs/wiki_formulas_isl_debug.pdf")
```
