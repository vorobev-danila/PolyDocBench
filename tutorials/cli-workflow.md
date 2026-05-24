# CLI and Python Workflow

This tutorial shows the local workflow:

```text
parse -> render -> noise -> evaluate
```

Parsing and rendering are exposed through the CLI. Noise and evaluation
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
uv run python -m polydocbench render examples\wiki_formulas.json -o outputs\wiki_formulas.pdf --template simple_article
```

## Generate Noisy Scan Variants

First render a PDF and GT pair:

```powershell
uv run python -m polydocbench render examples\wiki_formulas.json -o outputs\wiki_formulas.pdf --template simple_article
```

The command writes:

- `outputs/wiki_formulas.pdf`
- `outputs/wiki_formulas_gt.json`

Generate scan-like JPEG variants without paired GT:

```python
from polydocbench.noise import pdf_to_noisy_images

result = pdf_to_noisy_images(
    pdf_path="outputs/wiki_formulas.pdf",
    output_dir="outputs/wiki_formulas_scans",
    page_index=0,
    n_variants=1,
    dpi=200,
    profiles=["light_scan", "medium_scan", "heavy_scan"],
)

print(result["images"])
```

Generate paired noisy images and transformed pixel-coordinate GT. This is the recommended mode when the noise profile includes rotation or affine transforms:

```python
from polydocbench.noise import pdf_to_noisy_dataset

result = pdf_to_noisy_dataset(
    pdf_path="outputs/wiki_formulas.pdf",
    gt_path="outputs/wiki_formulas_gt.json",
    output_dir="outputs/wiki_formulas_dataset",
    page_index=0,
    n_variants=1,
    dpi=200,
    profiles=["medium_scan"],
)

print(result["artifacts"])
```

The paired dataset contains files like:

```text
outputs/wiki_formulas_dataset/medium_scan_0.jpg
outputs/wiki_formulas_dataset/medium_scan_0_gt.json
```

In the noisy GT:

- `polygon` stores the transformed four-corner geometry;
- `bbox` stores the horizontal box that encloses the polygon;
- `metadata.source_bbox` stores the original PDF-coordinate bbox.

## Visualize Noisy GT

Draw only transformed polygons as red lines:

```powershell
uv run python -m polydocbench draw-gt-overlay outputs\wiki_formulas_dataset\medium_scan_0.jpg outputs\wiki_formulas_dataset\medium_scan_0_gt.json -o outputs\wiki_formulas_dataset\medium_scan_0_polygon.jpg --mode polygon
```

Draw only axis-aligned bboxes as blue rectangles:

```powershell
uv run python -m polydocbench draw-gt-overlay outputs\wiki_formulas_dataset\medium_scan_0.jpg outputs\wiki_formulas_dataset\medium_scan_0_gt.json -o outputs\wiki_formulas_dataset\medium_scan_0_bbox.jpg --mode bbox
```

Draw both layers:

```powershell
uv run python -m polydocbench draw-gt-overlay outputs\wiki_formulas_dataset\medium_scan_0.jpg outputs\wiki_formulas_dataset\medium_scan_0_gt.json -o outputs\wiki_formulas_dataset\medium_scan_0_overlay.jpg --mode both
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
    "examples/wiki_formulas.json",
    template_name="simple_article",
)

PDFRenderer(debug=True).render(layout, "outputs/wiki_formulas_debug.pdf")
```
