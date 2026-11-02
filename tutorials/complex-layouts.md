# Complex Document Layouts

PolyDocBench renders tables as vector grids and searchable text, and figures as
aspect-preserving images with separate caption blocks. All coordinates come from
the same layout plan used to render the PDF. No browser or additional table-rendering
dependency is required; ReportLab and Pillow are already core dependencies.

## Offline Quick Start

The bundled example includes a local bitmap, two tables, merged headers, and
captions. Its chart values are illustrative, not measured benchmark results.

```powershell
uv run python -m polydocbench render examples\complex_document.json -o outputs\complex_layouts\research_illustrated.pdf --template research_illustrated
```

The command writes the PDF and `research_illustrated_gt.json`. Add `--debug` for
bounding-box overlays. View the PDF without overlays to inspect the actual page.

The local figure is committed under `examples/assets/benchmark_chart.png`.
Regenerate it with `uv run python scripts/generate_complex_example_asset.py`.

## Page Profiles

| Template | Layout | Distinctive behavior |
| --- | --- | --- |
| `technical_report` | One column | Captioned figures and paginated tables |
| `research_illustrated` | Two columns | Balanced text bands interrupted by full-width figures/tables |
| `financial_report` | One column | Compact table padding and right-aligned numeric cells |
| `magazine_feature` | Three columns | Balanced text bands with full-width illustrated inserts |
| `reference_sheet` | Landscape, one column | Wide comparison tables on 842 x 595 point pages |

The original `simple_article`, `scientific_paper`, and `magazine_layout` remain
available. All templates can place tables and images. New profiles use
`strict_layout: true`: unavailable resources, unsupported extracted table content,
and impossible placements fail explicitly. Legacy profiles record skipped elements
in GT `metadata.layout_warnings`; the API also returns `layout_warnings`.

## Tables

```json
{
  "type": "table",
  "caption": "Table 1. Measurement conditions.",
  "header_rows": 2,
  "column_weights": [2, 1, 1],
  "rows": [
    [
      {"text": "Method", "rowspan": 2, "is_header": true},
      {"text": "Conditions", "colspan": 2, "is_header": true}
    ],
    [{"text": "Light", "is_header": true}, {"text": "Heavy", "is_header": true}],
    [{"text": "Baseline"}, {"text": "0.12", "align": "right"}, {"text": ""}]
  ]
}
```

Rows list the logical anchor cells in source order. Cells covered by a previous
`rowspan` or `colspan` are not repeated; genuinely empty cells must be represented
by `{"text": ""}`. Spans are positive integers and cannot extend beyond the table.
Overlapping cells and invalid column weights are rejected before placement.
`align` can be `left`, `center`, or `right`; otherwise profile defaults apply.

Explicit column weights determine proportional column widths; otherwise widths
adapt to content and short tokens. Use `tables.auto_column_widths: false` for
equal widths. ReportLab measures row
heights from wrapped cell text. A long table continues into the next column/page,
never splitting a merged row group. Leading header rows repeat on continuations.
`header_rows` makes the repeated region explicit; otherwise leading header rows
are detected, allowing an empty non-header corner. Row-scoped headers do not
turn data rows into repeated column headings. Explicit HTML `thead` and `scope`
are retained by the parser. A span crossing that boundary extends the header region.

Basic cell `<sup>`/`<sub>` notation is preserved as Unicode when possible (for
example `10³⁰`, `H₂O`), with explicit `^(...)` / `_(...)` fallbacks for unsupported
combinations. Citation nodes and letter footnotes are not interpreted as powers.

The caption appears above the first fragment and stays with its first data row
group. Rows or merged groups that cannot fit on a fresh page are rejected rather
than endlessly creating new pages. Reduce padding/font size, use a landscape
profile, or split the source content in that case.

## Figures

```json
{
  "type": "image",
  "src": "assets/benchmark_chart.png",
  "caption": "Figure 1. A local figure with a separate text caption.",
  "width": 400,
  "height": 180,
  "span_columns": "all"
}
```

Local paths are resolved from the working directory first, then relative to the
source JSON. Remote resources use the shared image cache. Actual file dimensions
determine aspect ratio; `width` and `height` are maximum PDF-point allocations,
not a request to distort the image. Without explicit dimensions, profile limits
determine size. The image and its complete caption are kept on the same page and
inside the same region. The image bbox excludes the caption.

Raster images need no optional extras. SVG support uses the existing `formula`
extra (`uv sync --extra formula`). Wikimedia `pixel_width` / `pixel_height` and
`srcset` are retained by the parser as source information; they are not PDF-point
dimensions, and a higher-resolution `srcset` candidate is not selected automatically.

## Region Configuration

The implemented configuration keys are:

```yaml
strict_layout: true
balance_before_spans: true
tables:
  span_columns: all
  font_size: 8
  auto_column_widths: true
  cell_padding: 4
  repeat_headers: true
  header_fill: "#e5eef6"
  grid_color: "#9aa5b1"
  grid_width: 0.4
  numeric_alignment: right
images:
  span_columns: all
  width_fraction: 0.9
  max_height_fraction: 0.4
  caption_size: 9
```

`span_columns: all` can also be set on an individual table/figure. It creates a
full-width region below the preceding text, followed by a new column region.
`balance_before_spans` compacts the preceding text into a balanced column band
when that text fits the current page. Without it, normal sequential column filling
is preserved. This is not arbitrary floating-image text wrapping or column-span-2
placement in a three-column page.

Older YAML string `rules`, `column_rules`, and `columns.balance` are not a general
rule interpreter. Do not use those declarations to request unsupported placement.

## Ground Truth and Evaluation

- Every visible table fragment is a `table` block with its own ID, bbox and
  `metadata.table_id` linking it to the original logical table.
- Each `table_cell` has a bbox and row/column indices, spans, header status,
  `parent_id`, and stable `source_cell_id` in metadata.
- Repeated headers receive new visible IDs with `repeated_header: true` but keep
  their logical source-cell identity.
- Cell text is exported as ordinary `text_line` elements, with `owner_type: table`.
- Captions have separate blocks and lines linked through `caption_for`.
- Paragraphs crossing pages/regions receive page-local fragments linked through
  `source_block_id`; heading text is also exported as visible GT lines.

Scan noising transforms cell and caption bboxes into polygons just like other
elements. Noisy GT reading-order lists contain only IDs visible on the selected page.
The source/GT schema remains `0.1`; these are additive fields and element types.

OCR quality includes table-cell text. Its current one-to-one line matching can
penalize OCR that merges adjacent cells into a single line; it is not a table-aware
recognition metric. Structure evaluation treats each visible table as one object,
not its cells as extra paragraphs. Semantic reading-order evaluation includes
captions but excludes table interiors. Cell topology/TEDS evaluation is not yet
implemented. Re-render datasets after this change: old PDFs/GT do not gain table
content or heading lines by recalculating metrics alone.

Previously parsed Wikipedia JSON may already have lost empty cells and span
attributes. Reparse the article to recover those fields; re-rendering old JSON
cannot infer them. Use a fresh experiment output directory and regenerate scans
and predictions, rather than `--reuse` artifacts from an older rendering pipeline.

## Parser Scope and Limitations

Wikipedia extraction preserves empty cells, merged spans, table captions, image
dimensions, and gallery figures. Nested table rows are not mixed into the parent
grid, but nested table text is flattened and a warning is recorded. Images inside
table cells likewise produce an extraction warning, not a claim of full support.
Strict profiles reject these cases. Full nested tables, rich inline cell content,
multi-panel figure groups, floating text wrapping, and splitting a single oversized
row across pages are outside this implementation.

For real-URL integration checks and current limitations, see
[Live Wikipedia Checks](live-wikipedia-check.md). Missing supported symbols use
the bundled Noto Sans Symbols 2 fallback with matching width/baseline calculation;
unsupported glyphs fail explicitly rather than becoming missing-glyph boxes.
