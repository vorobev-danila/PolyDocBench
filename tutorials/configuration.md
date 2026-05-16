# Configuration

PolyDocBench keeps runtime configuration in `configs/`.

## Layout Templates

Layout templates live in [../configs/layout_templates.yaml](../configs/layout_templates.yaml).

Example:

```yaml
templates:
  simple_article:
    layout_type: single_column
    typography:
      body_size: 10
      line_height: 1.2
```

List available templates:

```powershell
uv run python -m polydocbench list-templates
```

Use a template during rendering:

```powershell
uv run python -m polydocbench render examples\wiki_formulas_isl.json -o outputs\paper.pdf --template scientific_paper
```

## Render Config

Render settings live in [../configs/render_config.yaml](../configs/render_config.yaml).

They control PDF metadata, debug colors, image cache settings, and renderer defaults.

## Source JSON Shape

The canonical data format is documented in [Data Format](data-format.md).

```json
{
  "schema_version": "0.1",
  "title": "Example",
  "url": "https://example.org",
  "content": [
    {
      "type": "paragraph",
      "text": "A paragraph that will be wrapped, justified, and exported as line-level GT."
    },
    {
      "type": "formula",
      "image_src": "examples/assets/formula.png",
      "latex": "x^2 + y^2 = z^2",
      "width": 180,
      "height": 48
    }
  ]
}
```
