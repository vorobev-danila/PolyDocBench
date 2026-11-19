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
