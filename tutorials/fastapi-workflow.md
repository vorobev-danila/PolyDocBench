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
| `POST` | `/render` | Render JSON to PDF and GT |
| `GET` | `/noise/profiles` | List noise profiles |
| `POST` | `/noise/pdf` | Generate noisy scan images from PDF |
| `POST` | `/noise/pdf-with-gt` | Generate noisy images with transformed pixel-coordinate GT |
| `POST` | `/evaluate/quality` | Evaluate OCR text/geometry quality |
| `POST` | `/evaluate/ordering` | Evaluate predicted reading order |

## Parse Request

```json
{
  "url": "https://simple.wikipedia.org/wiki/History_of_Russia",
  "output_path": "outputs/api/history_of_russia.json",
  "debug": false
}
```

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

## Noise Request

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
