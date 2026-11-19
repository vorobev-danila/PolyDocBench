# Wikipedia Content GT Pilot

This pilot keeps the extracted text, photographs, captions, tables and formulas
of pinned Wikipedia articles. PolyDocBench changes the page layout, not the
theme or the source media. It does not inject control figures or tables.
Use the earlier [controlled corpus](development-corpus.md) for regression and
noise debugging, not as evidence that this pilot preserves article content.

## Generate The Gallery

Run from the repository root:

```powershell
uv sync --extra noise --extra formula --extra dev
uv run --no-sync python scripts/prepare_wikipedia_gt_pilot.py --output-dir outputs/wikipedia_gt_pilot
```

The output directory must be new or empty. The script uses the checked-in
[revision IDs](../configs/wikipedia_gt_pilot_revisions.json). It captures the
MediaWiki HTML and response evidence and stores the exact graphics used for
rendering in each render bundle. `--refresh-revisions` is an explicit exploratory
mode; it writes the resolved IDs to `revisions.json`. Capturing a fixed revision
again does not establish byte identity for mutable templates or media; preserve
the original bundle and its hashes for reproducibility.

The script renders six sources and selects up to two pages per article. Page
selection prefers uncovered media types, then distinct source media, then
text density and page number. It uses GT, not OCR scores. The variants are clean,
fixed +3 degree rotation and seeded medium noise. No OCR is run.

## Read The Evidence

- `index.html`: per-article revision links, selected PDF page numbers and a link
  to the GT gallery. `audit/index.html` shows clean and transformed overlays.
- `report.json`: raw HTML inventories, per-article preparation results and
  source-to-asset references. Raw HTML inventories include navigation and
  fallback markup and are **not** coverage denominators.
- `inputs/source_selection.json` inside each render bundle: one-based retained
  and excluded indices in the flattened source, with reasons. The original
  capture stays unchanged. The audit compares GT with the **sealed rendered
  subset**; passing it does not prove that the parser extracted every original
  element. The ordinary strict snapshot renderer does not silently omit blocks.
- `audit/reviews.json`: decisions on individual previews. Unreviewed entries
  stay `pending`; automatic checks cannot approve a source or its media rights.

## Local Run

The gallery at `outputs/wikipedia_gt_pilot_20261118_final/index.html` covers
the Pythagorean theorem, rainbows, the Eiffel Tower, SI prefixes, the Solar
System and Rialto Bridge. The source layouts yielded 144 PDF pages in total;
12 pages and their 36 scan variants were selected. Automatic GT audit reported
no errors. The 48 review units are 12 PDF previews and 36 scan previews, not
48 distinct pages.

Across the six rendered articles, 18 **parsed** blocks were excluded: 15 tables
with images inside cells, two paragraphs with missing bundled glyphs, and one
formula that the MathML renderer rejected. Skipping the whole table avoids
presenting an incomplete table as faithful source content.

The pilot uses [Ziamath](https://ziamath.readthedocs.io/en/stable/usage.html)
to render supported MathML to sealed SVG paths when no image fallback is
available. Formula annotations are not duplicated as raw prose; inline
formulas are still laid out as standalone blocks, so sentence continuity and
inline reading order are **not** preserved. The formula bbox follows the
placed graphic's aspect ratio, not an arbitrary square allocation. Some
original images are low-resolution Wikimedia thumbnails. Text inside figures
does not get a transcript merely because the figure has a box.

Start manual review with clean pages against their pinned articles, then
compare the corresponding transformed scans. Check especially multi-column
reading order, table continuations, captions and moved inline math. Do not use
this exploratory sample as a held-out benchmark or publish its assets before
reviewing source fidelity, media rights and the evaluation scope.

## Paired Tesseract Pilot

Install the OCR/benchmark extras alongside the gallery dependencies, and use
a local Tesseract installation with eng, rus, fra, deu, spa and ita.

```powershell
uv sync --extra noise --extra formula --extra ocr --extra benchmark --extra dev
uv run --no-sync python scripts/run_wikipedia_ocr_pilot.py --input-dir outputs/wikipedia_gt_pilot_20261118_final --output-dir outputs/wikipedia_ocr_pilot
```

The OCR run uses the same audit plan, including the exact scan and GT files,
without re-rendering or modifying human-review records. Use a fresh output
directory for new inference or append `--report-only` to recompute the report
from an existing run and its frozen evaluator. The report's pooled metrics use
only pages with the same eligible GT line IDs and text in all three conditions.
The pairing CSV preserves failures and incompatible pairs. See `report.md`,
`summary.csv`, `images.csv`, `paired_pages.csv` and `clean_diagnostics.json`
inside the OCR output. The model binary version, runtime and settings are in
`run/run.json` and `run/job.json`.

Local result (2026-11-19): 36/36 successful, 12/12 comparable base pages, and
477/477 eligible text lines per condition (identical IDs and text). Tesseract
5.5.0 with protocol 0.3 and line bbox IoU 0.30 yielded:

| Condition | Micro CER | Micro WER | Line F1 |
| --- | ---: | ---: | ---: |
| Clean | 8.04% | 11.91% | 86.13% |
| Fixed +3 degree rotation | 21.90% | 27.81% | 83.80% |
| Medium scan | 9.78% | 14.94% | 85.10% |

The fixed rotation increased pooled CER by 13.86 percentage points versus
clean; medium noise increased it by 1.74. These are different transformations,
not positions on a calibrated severity scale. Rotation affects OCR and spatial
matching; this run alone does not isolate how much each contributes.

On clean pages, 306/306 body/other lines matched but only 60/136 cell lines
and 6/20 headings matched at the frozen IoU threshold. For example, Eiffel
Tower page 54 groups multiple cells from one row into an OCR line. It also
contains the correctly recognized heading `Galerie`, rejected from matching
at an IoU of 0.061. Fourteen unmatched clean GT lines have an overlapping
unmatched prediction with exact normalized text below threshold. Do not
interpret a missing match as proof that text was not recognized, and do not
retune the primary score on these examples. Next check matching sensitivity
and table-vs-body performance separately before increasing the corpus size.
