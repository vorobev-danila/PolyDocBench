# FastAPI Workflow

FastAPI exposes the main research pipeline through HTTP endpoints.

## Start the API

```powershell
uv pip install -e ".[api,noise]"
uv run python -m uvicorn polydocbench.api.app:app --reload --host 127.0.0.1 --port 8000
```

Open the interactive docs:

```text
http://127.0.0.1:8000/docs
```

## Endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Server health check |
| `GET` | `/templates` | List layout templates |
| `POST` | `/parse/wikipedia` | Parse Wikipedia page to source JSON |
| `POST` | `/parse/wikipedia-snapshot` | Capture a fixed revision with raw MediaWiki evidence |
| `POST` | `/render` | Render JSON to PDF and GT |
| `GET` | `/noise/profiles` | List noise profiles |
| `POST` | `/noise/pdf` | Generate noisy scan images from PDF |
| `POST` | `/noise/pdf-with-gt` | Generate noisy images with transformed pixel-coordinate GT |
| `POST` | `/evaluate/quality` | Evaluate OCR text/geometry quality |
| `POST` | `/evaluate/ordering` | Evaluate predicted reading order |
| `POST` | `/evaluate/structure` | Evaluate predicted document structure |

## Parse Request

```json
{
  "url": "https://simple.wikipedia.org/wiki/History_of_Russia",
  "output_path": "outputs/api/history_of_russia.json",
  "debug": false
}
```

For a revision-bound capture, use `POST /parse/wikipedia-snapshot` with a new
or empty output directory:

```json
{
  "url": "https://en.wikipedia.org/wiki/ASCII",
  "output_dir": "outputs/api/sources/en/ascii",
  "revision_id": null
}
```

The endpoint refuses to overwrite source evidence. Offline verification is a
CLI operation; see [Wikipedia Revisions And Benchmark Splits](source-revisions-and-splits.md).

## Render Request

```json
{
  "json_path": "outputs/api/history_of_russia.json",
  "output_pdf": "outputs/api/history_of_russia.pdf",
  "template": "scientific_paper",
  "font_path": "DejaVu Sans/DejaVuSans.ttf",
  "debug": true
}
```

## Rich Render Profiles

The render endpoint also accepts `technical_report`, `research_illustrated`,
`financial_report`, `magazine_feature`, and `reference_sheet` in `template`.
For an offline smoke run, use `examples/complex_document.json` as `json_path`.
Rendering returns `layout_warnings`; new strict profiles fail with HTTP 400 on
unavailable images or impossible/unsupported placements. Details:
[Complex Layouts](complex-layouts.md).

## Noise Request

Both noise endpoints support opt-in `clean` PNG controls and return pipeline
version `0.2` with per-artifact generation traces. Defaults remain three noisy
profiles. Clean always has one variant. See [Reproducible Noise](reproducible-noise.md).

```json
{
  "pdf_path": "outputs/api/history_of_russia.pdf",
  "output_dir": "outputs/api/history_of_russia_scans",
  "page_index": 0,
  "variants": 1,
  "seed": 42,
  "dpi": 200,
  "profiles": ["light_scan", "medium_scan"]
}
```

Use `/noise/pdf-with-gt` when geometric transforms should also update GT:

```json
{
  "pdf_path": "outputs/api/history_of_russia.pdf",
  "gt_path": "outputs/api/history_of_russia_gt.json",
  "output_dir": "outputs/api/history_of_russia_dataset",
  "page_index": 0,
  "variants": 1,
  "seed": 42,
  "dpi": 200,
  "profiles": ["medium_scan"]
}
```

## Evaluate OCR Quality

```json
{
  "gt_path": "outputs/api/history_of_russia_gt.json",
  "page_number": 1,
  "iou_threshold": 0.3,
  "predicted_lines": [
    {
      "id": "pred_1",
      "text": "recognized text",
      "bbox": {
        "x": 50,
        "y": 700,
        "width": 200,
        "height": 14
      },
      "confidence": 0.95
    }
  ]
}
```

## Evaluation Responses

OCR quality responses include `evaluation_protocol_version: "0.2"`, legacy
`CER`/`WER`, insertion-aware `micro_CER`/`micro_WER`, error counts, and
`line_precision`/`line_recall`/`line_F1`.

`POST /evaluate/ordering` accepts the quality request fields plus `num_columns`.
This endpoint evaluates the existing geometric line-order heuristic. With fewer
than two matched lines, `kendall_tau` and `pairwise_accuracy` are JSON `null`;
`num_order_pairs` and `order_pair_coverage` describe available evidence.
The dots.ocr semantic experiment is a separate workflow, not this endpoint.
See [Evaluation Protocol](evaluation-protocol.md) for definitions and limitations.

## Evaluate Structure

```json
{
  "gt_path": "outputs/api/history_of_russia_gt.json",
  "page_number": 1,
  "iou_threshold": 0.5,
  "predicted_elements": [
    {
      "id": "docling_1",
      "type": "paragraph",
      "text": "recognized block text",
      "bbox": {
        "x": 50,
        "y": 120,
        "width": 300,
        "height": 80
      },
      "reading_order": 1
    }
  ]
}
```
