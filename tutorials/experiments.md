# Experiments

For publication-oriented corpus planning and an offline audit of existing
artifacts, see [Benchmark Inventory](benchmark-manifest.md) and the
[ICDAR 2027 roadmap](icdar-2027-plan.md). The current experiment runners do not
yet execute the draft benchmark specification or assign dataset splits.

For a shared, frozen pilot selection with per-model time/memory/failure
accounting, use the separate [Benchmark Pilot](benchmark-pilot.md) workflow.
It consumes an inventory and uses the same task evaluators without changing
the existing experiment runners or their historical results.

New noise generation uses pipeline `0.2`. Use a separate output directory for
new runs; the same seed no longer recreates historical unversioned scans.
Add `clean` to `--profiles` for a lossless control. Requested-pair filtering,
reuse checks, PNG support and migration are described in
[Reproducible Noise](reproducible-noise.md).

Opt into sealed source/config/font/image/code inputs with `--snapshot-inputs`.
URL images additionally require `--allow-asset-downloads`. Use a new output
directory; legacy renders are not retrospectively sealed. See
[Render Snapshots](render-snapshots.md) for exact replay and provenance limits.
Add `--pin-source-revisions` for new publication runs so each source directory
contains its MediaWiki revision evidence. See
[Wikipedia Revisions And Benchmark Splits](source-revisions-and-splits.md).

This guide describes the first OCR benchmark loop:

```text
Wikipedia pages -> synthetic PDFs -> noisy scans -> Tesseract OCR -> quality metrics -> dashboard
```

## Tesseract Setup

Install the Python dependencies:

```powershell
uv pip install -e ".[noise,ocr,dev]"
```

Install the Tesseract executable and language packs separately. The experiment currently uses:

| PolyDocBench code | Tesseract language |
| --- | --- |
| `en` | `eng` |
| `ru` | `rus` |
| `fr` | `fra` |
| `de` | `deu` |
| `es` | `spa` |
| `it` | `ita` |

Check installed Tesseract languages:

```powershell
tesseract --list-langs
```

If `tesseract` works in PowerShell but Python still cannot find it, pass the executable path explicitly:

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --tesseract-cmd "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

## Run The Experiment

By default, the script runs the first `3` configured articles per language, renders each article with three layout templates, and evaluates only the first rendered page:

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --output-dir outputs\experiments\tesseract_quality --variants 1 --profiles light_scan medium_scan heavy_scan
```

The default matrix is:

```text
3 layout templates x 3 noise profiles x 1 variant = 9 noisy document variants per selected page
```

Default layout templates:

| Template | Column layout |
| --- | --- |
| `simple_article` | one column |
| `scientific_paper` | two columns |
| `magazine_layout` | three columns |

The script runs:

1. Wikipedia parsing for each language.
2. PDF and GT rendering for each selected layout template.
3. Scan noise with paired transformed GT for each selected page/profile/variant.
4. Tesseract OCR.
5. Quality evaluation with CER, WER, IoU, and matched line ratio.
6. An interactive Plotly dashboard for comparing languages, templates, and noise profiles.

## Wikipedia Article Pool

The experiment contains `10` configured Wikipedia pages per language. Their URLs
were checked when introduced, but availability is not permanent and does not pin
content. Print the full configured URL list:

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --list-articles
```

Available article IDs:

| Article ID | Content area |
| --- | --- |
| `history_russia` | history |
| `linear_algebra` | mathematics |
| `quantum_mechanics` | physics |
| `literature` | literature / biography |
| `cell_biology` | biology |
| `organic_chemistry` | chemistry |
| `climate` | climate science |
| `ai` | computer science |
| `kant` | philosophy |
| `milky_way` | astronomy |

The configured URLs were checked for HTTP `200` responses before being added to the workflow.

For a new revision-bound run:

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --output-dir outputs\experiments\tesseract_pinned --languages en --article-ids history_russia --profiles clean medium_scan --pin-source-revisions
```

Reuse requires `--reuse --pin-source-revisions`; the saved evidence is verified
offline before rendering. A plain historical `source.json` is never relabelled
as revision-bound.

## Run A Subset

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --languages en ru fr --profiles light_scan --variants 1
```

Run selected articles:

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --languages en ru --article-ids linear_algebra ai --profiles medium_scan
```

Run all configured articles:

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --article-limit-per-language 0
```

Limit to a fixed number of articles per language:

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --article-limit-per-language 5
```

Run selected layout templates only:

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --templates scientific_paper magazine_layout
```

## Page Scope

Choose how many rendered pages should be converted into noisy scans and evaluated:

```powershell
# First rendered page only
uv run python scripts\run_tesseract_ocr_experiment.py --page-scope first

# First half of rendered pages
uv run python scripts\run_tesseract_ocr_experiment.py --page-scope half

# All rendered pages
uv run python scripts\run_tesseract_ocr_experiment.py --page-scope all
```

`--page-scope all` can be slow for long Wikipedia articles because every selected page is rendered to noisy images for every selected profile and variant.

Reuse already generated source/render/noisy artifacts:

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --reuse
```

Regenerate only the dashboard from an existing `metrics.jsonl` file without repeating OCR:

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --output-dir outputs\experiments\tesseract_quality --dashboard-only
```

The dashboard is generated by default. To run without producing HTML output, add `--no-dashboard`.

The experiment script prints compact progress by default:

```text
== EN | linear_algebra | English ==
[1/4] Parse Wikipedia
-- Template: simple_article --
[2/4] Render PDF + GT
      page_scope=first, selected_pages=[1]
[3/4] Generate noisy scans + transformed GT
[4/4] Run Tesseract + evaluate
      page=1 medium_scan_0: CER=0.403 WER=0.412 IoU=0.479 matched=0.700 lines=48/50
```

To show internal layout engine logs, add:

```powershell
--verbose-layout
```

## Outputs

```text
outputs/experiments/tesseract_quality/
  metrics.jsonl
  summary.csv
  dashboard.html
  en/
    linear_algebra/
      source.json
      simple_article/
        document.pdf
        document_gt.json
        noisy/
          page_001/
            light_scan_0.jpg
            light_scan_0_gt.json
            medium_scan_0.jpg
            medium_scan_0_gt.json
        predictions/
          page_001/
            light_scan_0_tesseract.json
            medium_scan_0_tesseract.json
      scientific_paper/
      magazine_layout/
```

`metrics.jsonl` stores one row per language/article/template/page/profile/variant.

`summary.csv` stores aggregated metrics grouped by language, layout template, and noise profile.

`dashboard.html` is a standalone interactive Plotly report with:

- pooled micro-CER and IoU comparisons by language and noise profile;
- pooled micro-WER and line-F1 comparisons by document template and noise profile;
- an aggregated results table for detailed inspection.

Legacy result files retain the original CER/WER/matched-ratio charts. New reports
show their evaluation protocol version and do not combine different versions.

Open it locally after an experiment:

```powershell
Start-Process outputs\experiments\tesseract_quality\dashboard.html
```

## Metric Notes

The `--templates` option also accepts `technical_report`, `research_illustrated`,
`financial_report`, `magazine_feature`, and `reference_sheet`; defaults remain the
three original templates. See [Complex Layouts](complex-layouts.md) for their
content requirements and strict validation. Nested tables and images inside
table cells are not supported by the new strict profiles. Curate compatible
sources before starting a large run. Use a fresh output directory after renderer
changes: `--reuse` can retain old source JSON/PDF/GT/scans and cannot restore table
spans lost by an earlier parser.

## OCR Metric Definitions

- `CER` / `macro_CER`: mean character error rate over GT lines, lower is better.
- `WER` / `macro_WER`: mean word error rate over GT lines, lower is better.
- `micro_CER` / `micro_WER`: length-weighted errors including unmatched predictions.
- `line_precision`, `line_recall`, `line_F1`: geometry-based line detection quality.
- `IoU`: mean geometry overlap over all GT lines, with zero for unmatched lines.
- `matched_ratio`: share of GT lines matched to OCR lines by IoU, higher is better.

Protocol `0.2` preserves legacy CER/WER and adds insertion-aware micro metrics.
Summary micro rates pool error counts and reference lengths, not page averages.
See [Evaluation Protocol](evaluation-protocol.md) for empty-input conventions,
segmentation limitations, and migrating saved predictions.

For noisy scans, the script runs Tesseract in image-coordinate mode, so predicted bboxes are evaluated against the transformed noisy GT rather than the original PDF GT.

## dots.ocr Reading-Order Evaluation

`iairlab/dots.ocr-1.5` is oriented toward document layout understanding and returns semantic blocks such as paragraphs and headings. It should not be evaluated as a text-line detector. PolyDocBench therefore uses this remote model for reading-order evaluation: the text and ordering of returned semantic blocks are compared with visible GT text blocks in exported reading order.

The runner consumes the same noisy images and transformed GT already generated for the Tesseract experiment, so noise and layout conditions remain identical.

Install the client dependencies:

```powershell
uv pip install -e ".[dotsocr,noise,dev]"
```

Create a local `.env` file in the project root. It is excluded by `.gitignore`; do not store tokens in notebooks or committed source files:

```dotenv
LITELLM_API_KEY=sk-...
```

The dots.ocr runner and `notebooks/dotsocr_ordering.ipynb` load this file automatically. Keep the file at `PolyDocBench/.env`, not inside `notebooks/`, so both workflows use the same configuration.

Run a one-image smoke evaluation first:

```powershell
uv run python scripts\run_dotsocr_ordering_experiment.py `
  --input-dir outputs\experiments\tesseract_quality `
  --output-dir outputs\experiments\dotsocr_ordering `
  --languages en `
  --article-ids history_russia `
  --templates scientific_paper `
  --profiles medium_scan `
  --page-numbers 1 `
  --max-images 1
```

Run evaluation on all previously generated noisy images:

```powershell
uv run python scripts\run_dotsocr_ordering_experiment.py `
  --input-dir outputs\experiments\tesseract_quality `
  --output-dir outputs\experiments\dotsocr_ordering
```

The model output is preserved in returned order; it is not geometrically re-sorted. GT is formed by joining visible text lines by source block (`parent_id`) in `line_index` order and sorting those blocks by exported block `reading_order`. Images without text are excluded.

The adapter accepts both structured JSON blocks and the plain Markdown/text sequence that dots.ocr may naturally return. For plain text responses, paragraphs and headings become ordered blocks without geometry; ordered text metrics remain valid, while bbox overlay is unavailable for those predicted blocks.

Metrics:

- `ordered_CER` and `ordered_WER`: OCR text errors after concatenating semantic blocks in their reading order.
- `token_F1`: recognized token overlap without order, useful to distinguish recognition loss from order errors.
- `kendall_tau` and `pairwise_accuracy`: ordering of matched GT pairs across distinct model blocks; `null` when no comparable pairs exist.
- `matched_block_ratio`: GT block coverage; read it together with ordering scores.
- `order_pair_coverage`: share of GT pairs whose order is observable across returned model blocks.

Pairs within a single model block are unresolved, not automatically correct.
Reports show undefined ordering scores as `N/A`; CSV means exclude them and
include `valid_order_count`. These protocol `0.2` scores are not directly
comparable with legacy scores that credited internal GT-span order.

Results:

```text
outputs/experiments/dotsocr_ordering/
  metrics.jsonl
  summary.csv
  dashboard.html
  en/history_russia/scientific_paper/noisy/page_001/
    medium_scan_0_dotsocr_blocks.json
    medium_scan_0_dotsocr_raw.txt
    medium_scan_0_block_matches.json
```

The raw response is saved alongside parsed predictions to make remote-model responses auditable. Rebuild the dashboard without making new API requests:

```powershell
uv run python scripts\run_dotsocr_ordering_experiment.py `
  --output-dir outputs\experiments\dotsocr_ordering `
  --dashboard-only
```

For manual inspection of semantic blocks, visible GT order, matches, and overlays, open `notebooks/dotsocr_ordering.ipynb`. Its configuration cell uses the same language/article/template/page/noise selection as the experiment output structure and supports reusing a saved prediction without a new server request.

If an interrupted batch already saved predictions or raw responses, resume without re-requesting completed items:

```powershell
uv run python scripts\run_dotsocr_ordering_experiment.py `
  --input-dir outputs\experiments\tesseract_quality `
  --output-dir outputs\experiments\dotsocr_ordering `
  --reuse `
  --continue-on-error
```

## Docling Structure Evaluation

Docling is used for document structure extraction rather than line-level OCR scoring. PolyDocBench compares Docling structure elements with transformed GT elements by type and geometry.

Install the structure dependencies:

```powershell
uv pip install -e ".[structure,noise,dev]"
```

The runner consumes the same noisy images and transformed GT generated by the Tesseract preparation pipeline. A first Docling run may be slow because model pipelines are initialized and model artifacts may be prepared locally. Start with one image:

```powershell
uv run python scripts\run_docling_structure_experiment.py `
  --input-dir outputs\experiments\tesseract_quality `
  --output-dir outputs\experiments\docling_structure `
  --languages en `
  --article-ids history_russia `
  --templates scientific_paper `
  --profiles medium_scan `
  --page-numbers 1 `
  --max-images 1
```

Run the full structure experiment on prepared scans:

```powershell
uv run python scripts\run_docling_structure_experiment.py `
  --input-dir outputs\experiments\tesseract_quality `
  --output-dir outputs\experiments\docling_structure `
  --reuse `
  --continue-on-error
```

Metrics:

- `detection_precision`, `detection_recall`, `detection_F1`: geometry-based element detection at the configured IoU threshold.
- `mean_iou`: mean IoU over matched GT/prediction elements.
- `type_accuracy`: share of matched elements with matching normalized structure type.
- `type_aware_F1`: detection F1 where type must also be correct.
- `structure_score`: weighted summary of detection F1, mean IoU, and type accuracy.

Results:

```text
outputs/experiments/docling_structure/
  metrics.jsonl
  summary.csv
  dashboard.html
  en/history_russia/scientific_paper/noisy/page_001/
    medium_scan_0_docling_raw.json
    medium_scan_0_docling_structure.json
    medium_scan_0_structure_matches.json
```

Rebuild the dashboard without rerunning Docling:

```powershell
uv run python scripts\run_docling_structure_experiment.py `
  --output-dir outputs\experiments\docling_structure `
  --dashboard-only
```

The GT adapter groups visible text lines by source block, keeps non-text blocks such as images, tables, and formulas, and compares them in transformed image coordinates. The Docling adapter normalizes `texts`, `tables`, and `pictures` from `DoclingDocument` exports into the same structure-element format.
