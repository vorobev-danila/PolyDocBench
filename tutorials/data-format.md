# Data Format

PolyDocBench uses explicit JSON formats for source documents and ground-truth output. Both formats include a top-level `schema_version`.

Current schema version:

```text
0.1
```

The Pydantic models live in:

- `polydocbench.document.schema`
- `polydocbench.gt.schema`

## Source JSON

Source JSON is the input consumed by the layout engine.

```json
{
  "schema_version": "0.1",
  "title": "Example article",
  "url": "https://example.org/article",
  "content": [
    {
      "type": "paragraph",
      "text": "A paragraph that will be wrapped and rendered."
    },
    {
      "type": "heading",
      "level": 2,
      "text": "Section",
      "id": "Section",
      "content": []
    },
    {
      "type": "formula",
      "formula_type": "display",
      "latex": "x^2 + y^2 = z^2",
      "image_src": "examples/assets/formula.png",
      "width": 180,
      "height": 48
    }
  ]
}
```

`schema_version` is optional for older files. If it is missing, the validator assumes `0.1`.

## Supported Source Elements

| Type | Required fields | Notes |
| --- | --- | --- |
| `paragraph` | `text` or string `content` | Main text block |
| `hatnote` | `text` or string `content` | Rendered as paragraph with metadata |
| `heading` | `text` or string `content` | May contain nested `content` |
| `list` | `items` | Converted to paragraph lines with markers |
| `image` | `src`, `url`, `path`, or `image_src` | Extra metadata is preserved |
| `formula` | `latex`, `mathml`, `image_src`, or alt text | Rendered through image fallback when available |
| `table` | `rows` | Currently treated as a graphic/table-like block |

Unknown element types are allowed and preserved. The layout engine can decide how to handle them.

## Processed Layout Input

The layout engine also accepts pre-flattened input through `elements`:

```json
{
  "schema_version": "0.1",
  "title": "Processed example",
  "elements": [
    {
      "type": "paragraph",
      "content": "Already normalized paragraph text."
    }
  ]
}
```

## Validation Before Layout

`ContentLoader.load_json(...)` validates source files before layout/render:

```python
from polydocbench.layout.content_loader import ContentLoader

elements = ContentLoader.load_json("examples/wiki_formulas_isl.json")
```

Invalid files raise a Pydantic `ValidationError` before any layout work starts.

## Ground Truth JSON

Ground-truth JSON is exported after layout/render.

```json
{
  "schema_version": "0.1",
  "metadata": {
    "generator": "PolyDocBench",
    "format_version": "0.1",
    "page_count": 1,
    "element_count": 2
  },
  "reading_order": {
    "blocks": ["paragraph_0001"],
    "lines": ["paragraph_0001_line_0001"]
  },
  "pages": [
    {
      "page_number": 1,
      "width": 595.0,
      "height": 842.0,
      "containers": [
        {
          "id": "main_content",
          "type": "single_column",
          "bbox": {
            "x": 50,
            "y": 50,
            "width": 495,
            "height": 742,
            "page": 1
          },
          "elements": []
        }
      ]
    }
  ],
  "elements": [
    {
      "id": "paragraph_0001",
      "type": "paragraph",
      "content": "A paragraph.",
      "bbox": {
        "x": 50,
        "y": 760,
        "width": 200,
        "height": 14,
        "page": 1
      },
      "dimensions": {},
      "metadata": {
        "role": "block",
        "reading_order": 1
      }
    }
  ]
}
```

## Validate GT

```python
import json
from pathlib import Path

from polydocbench.gt.schema import validate_gt_document

data = json.loads(Path("outputs/document_gt.json").read_text(encoding="utf-8"))
gt = validate_gt_document(data)
print(gt.schema_version)
```

## Versioning Policy

- `0.1` is the first explicit schema version.
- Backward-compatible additions should keep the same major version.
- Breaking changes should introduce a new schema version and migration notes.
- Exported GT stores the version both at top level as `schema_version` and in metadata as `format_version`.
