# Live Wikipedia Table Checks

`scripts/check_wikipedia_tables.py` performs network-dependent integration checks
separately from the offline pytest suite. It does not run OCR models or compute
OCR quality metrics.

## Run

From the project root, with the `noise` extra installed for PyMuPDF:

```powershell
uv run python scripts/check_wikipedia_tables.py --max-tables 0
```

The default cases are:

| Case | URL | Coverage |
| --- | --- | --- |
| `en_ascii` | https://en.wikipedia.org/wiki/ASCII | Wide grids, merged cells, control-picture glyphs |
| `ru_ascii` | https://ru.wikipedia.org/wiki/ASCII | Empty corner headers and long Cyrillic descriptions |
| `en_languages` | https://en.wikipedia.org/wiki/Comparison_of_programming_languages | Long comparison table and repeated headers |
| `de_prefixes` | https://de.wikipedia.org/wiki/SI-Pr%C3%A4fix | German text, numeric tables and merged headers |

Every selected case attempts full-article rendering and separate supported-table
probes under `technical_report` and `reference_sheet`. The default limit is three
table probes per article; `--max-tables 0` removes that limit. Validation errors
and extraction warnings are reported, not counted as successfully rendered tables.

Reparse and rerender the saved HTML without new article downloads:

```powershell
uv run python scripts/check_wikipedia_tables.py --reuse-html --max-tables 0
```

This reuse mode verifies the HTML checksum and does not reuse PDFs, GT or metrics.
Remote image/formula resources may still need network access if not cached.
To audit extraction without rendering, use `--parse-only`.

## Output

```text
outputs/validation/wiki_tables/
  report.json
  en_ascii/
    fetch.json
    source.html
    source.json
    table_003.json
    table_003_technical_report.pdf
    table_003_technical_report_gt.json
    table_003_technical_report_page_001.png
```

`fetch.json` records the requested/resolved URL, response status, retrieval time,
and SHA-256 of the raw downloaded HTML. `report.json` includes table dimensions,
merged/header counts, unsupported content, selected/excluded table indices,
PDF/GT paths, page counts, and validation failures. Keep these generated snapshots
in `outputs/`, not in version control.

## Validation Contract

- All source logical cells must occur in GT; repeated headers are deduplicated
  by logical table ID and row/column position for this check.
- Element IDs must be unique, bboxes must stay on their page, and cell text must
  remain inside its cell. Container ownership must match the element page.
- PDF and GT page counts must agree.
- Exported line characters must survive PDF text extraction. Whitespace is
  ignored only for this diagnostic because PDF extractors may omit spaces between
  separately positioned justified words. This does not change CER/WER evaluation.
- PNG previews cover the first/last page and selected table pages. Automated
  checks complement visual review; they cannot prove every typographic choice.

## Interpreting Results

The checked snapshot contained 13 tables, including 2 image-bearing infoboxes.
All 11 supported data tables passed under all five new templates (55 table probes),
including a 141-row comparison table. Two full articles passed all five templates;
the full EN/RU ASCII articles correctly failed strict rendering because their
infoboxes contain images inside cells. These are known unsupported inputs, not
successful end-to-end cases. Article contents can change, so use the saved report
and HTML checksums to identify the actual tested snapshot.

The expanded check used:

```powershell
uv run python scripts/check_wikipedia_tables.py --reuse-html --max-tables 0 --templates technical_report reference_sheet research_illustrated financial_report magazine_feature
```

Exit code `1` means at least one full article/probe failed or had validation
issues. The full default run therefore reports the known infobox limitation.
For supported table-only probes, use:

```powershell
uv run python scripts/check_wikipedia_tables.py --reuse-html --max-tables 0 --tables-only
```

This mode explicitly excludes unsupported tables and retains their indices and
warnings in the report. It does not claim that infobox images are supported.
Use a different `--output-dir` to retain reports from different modes side by side.

## Rendering Improvements

Column widths now adapt to text lengths and short tokens unless `column_weights`
is provided; `tables.auto_column_widths: false` restores equal widths. Explicit
`thead`, header `scope`, and an empty corner cell are respected during header
repetition. Noto Sans Symbols 2 supplies missing control-picture glyphs through
the same font runs used for measurement and drawing. Its OFL license is bundled
under `fonts/`; it does not provide universal Unicode/shaping coverage.

Basic table-cell superscripts/subscripts are preserved as Unicode (for example
`10³⁰`, `10⁻³`, `H₂O`) when representable, otherwise as explicit `^(...)` / `_(...)`
notation. Identified citation nodes are removed structurally, numeric bracketed
data such as `array[1]` is retained, and linked/letter footnotes are not treated
as exponents. This prevents the source-to-GT mistake of flattening `10<sup>30</sup>`
into the mathematically different text `10 30`. Full rich inline typography is
still outside this implementation.
