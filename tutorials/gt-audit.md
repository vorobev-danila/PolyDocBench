# Ground-Truth Audit

Audit version **0.1** checks semantic consistency beyond the permissive GT
interchange schema. It freezes a paired selection, audits complete PDF GT
documents and selected scan GT, and creates an offline visual review report.
It does not run OCR, change input files, or grant human/rights approval.

## Setup And Offline Fixtures

Run from the repository root:

```powershell
uv pip install -e ".[noise,dev]"
uv run python scripts\prepare_gt_audit_fixture.py `
  --output-dir outputs\validation\gt_audit_fixtures
```

The fixture uses the local `examples/complex_document.json` and bitmap asset.
It renders `technical_report`, `research_illustrated`, `magazine_feature`, and
landscape `reference_sheet` without debug boxes. All resulting pages are kept,
including table continuations with repeated headers. No web request is needed.

For every page it generates clean, medium/heavy scan scenarios, rotations of
+3/-3 degrees, and shear 0.08. The controlled affine recipes are in
[gt_audit_noise.json](../configs/gt_audit_noise.json); they are audit stress
conditions, not calibrated OCR severity levels. All generation uses 200 DPI
and master seed 42 by default. Use new/empty output directories.

Audit every fixture page and require all six conditions:

```powershell
uv run python scripts\run_gt_audit.py `
  --manifest outputs\validation\gt_audit_fixtures\manifest.json `
  --input-dir outputs\validation\gt_audit_fixtures `
  --output-dir outputs\validation\gt_audit_report `
  --split unassigned --all-base-pages `
  --profiles clean medium_scan heavy_scan audit_rotate_positive audit_rotate_negative audit_shear
```

Open `outputs/validation/gt_audit_report/index.html`. It includes language,
template, condition, error and human-review filters. Red denotes text-line GT;
blue denotes block/cell GT. Click the full-resolution input and GT links when
reviewing fine alignment: displayed previews are downscaled. Previews remain
inside the report; full-resolution links require the original dataset root.

## Multilingual Text Fixtures

If the historical experiment inventory exists locally, add **fresh renders**
of six text blocks per language, cycling through one-, two-, and three-column
templates. Keep the original source fingerprint and explicit excerpt metadata:

```powershell
uv run python scripts\prepare_gt_audit_fixture.py `
  --output-dir outputs\validation\gt_audit_multilingual_fixtures `
  --text-sources-manifest outputs\experiments\tesseract_quality\benchmark_inventory\manifest.json `
  --text-input-dir outputs\experiments\tesseract_quality
```

The extra sources are the first six normalized paragraph/heading items from
one deterministically selected source per observed language. They exclude
remote images and are **text-only audit excerpts**, not full-source replicas,
newly verified Wikipedia revisions, or a publication corpus. Run the same
`run_gt_audit.py --all-base-pages` command with this new manifest/input root.

## Audit Existing Experiments

On a reviewed corpus, use its inventory, `--split dev` (the default), and a
fixed page budget. The selector reuses [Pilot Plans](benchmark-pilot.md):
paired language/template strata, source hashes, master seed, variant zero and
exactly the requested profiles. Small budgets need not include every language.
`--all-base-pages` instead requires every eligible page to have every requested
condition; it does not silently discard incomplete pairs.

For the existing historical inventory, which has no clean controls:

```powershell
uv run python scripts\run_gt_audit.py `
  --manifest outputs\experiments\tesseract_quality\benchmark_inventory\manifest.json `
  --input-dir outputs\experiments\tesseract_quality `
  --output-dir outputs\validation\gt_audit_historical `
  --split unassigned --base-pages 18 --profiles light_scan medium_scan heavy_scan
```

Alternatively pass `--pilot-plan path\to\pilot_plan.json` and `--input-dir`
instead of a manifest to audit exactly an existing model pilot. This makes no
model call and does not add missing clean controls or reassign source families.

## What Is Checked

- **Document structure:** finite positive page sizes, bbox extents/bounds,
  explicit page references, unique IDs, container membership and allocations.
  Flat/container copies of one element are expected, not duplicate annotations;
  their content/type/geometry must agree. Text blocks may be flat-only.
- **Relations:** parent existence, containment, page ownership and cycles;
  caption owners; complete reading-order membership, unique IDs, page progression
  and PDF metadata indices. No reading order is reconstructed from model output.
- **Content:** nonempty text allocations need line annotations. Their lines
  must reconstruct the declared text; normalized source items must be represented.
  Text comparison ignores whitespace and **all hyphens**, including literal ones,
  but preserves case, accents and other punctuation. This is a layout-loss
  diagnostic, not a character-perfect OCR metric.
- **Tables:** logical cell spans and overlaps, source-cell text/span coverage,
  original versus repeated-header occurrences and flags, stable source-cell IDs,
  caption ownership and page-local fragments. Page-only image GT may legitimately
  contain repeated headers without their originals from earlier pages.
- **PDF evidence:** actual PDF page count/dimensions versus GT; extracted
  character inventories as a warning-only diagnostic. Extraction can differ
  because of glyph encoding. Neither text extraction nor allocation boxes prove
  pixel-accurate ink alignment.
- **Affine oracle:** source PDF corners are converted independently to pixels,
  then multiplied by the recorded transform. All IDs, text, references and the
  source-page reading-order subsequence must be preserved. Polygon corners and
  their canvas-clipped axis-aligned envelopes are compared numerically.
- **Trace/pixels:** recorded angle/shear are independently converted into a
  matrix and composed. When a trace exists, actual image bytes are replayed and
  checked against the selected image hash. `--no-pixel-replay` explicitly disables
  that part; legacy missing traces remain unavailable, not passed.

The affine oracle does **not** call the production GT transformation helpers.
Known-answer tests include identity, rotation, shear/translation, deliberately
corrupted GT, and a raster landmark. Point tolerance defaults to **0.01 pt**;
pixel-coordinate tolerance is **0.05 px**. These are numerical-consistency
tolerances, not acceptable errors for optical glyph boundaries.

Clipping uses convex polygon area after canvas intersection, not the enclosing
bbox area. Partial/fully clipped elements stay in GT and are reported as warnings.
The area concerns annotation allocations, not visible ink or readability. Counts
include overlapping block/cell/line annotations and are not independent samples.
The audit does not introduce a visibility mask or silently exclude text from scoring.

Task-specific scoring exclusions are a separate, opt-in workflow:
[Evaluation Visibility](evaluation-visibility.md). Passing this audit does not
approve its candidate policy or change historical metrics.

## Human Review

Every selected PDF-page preview and scan gets a separate review unit. Initial
`reviews.json` entries are all `pending`, regardless of automatic results.
After viewing a unit, edit its entry, for example:

```json
{
  "unit_id": "copy the existing unit_id unchanged",
  "status": "defect",
  "reviewer": "Reviewer name",
  "reviewed_at": "2026-11-09T15:00:00+03:00",
  "notes": "The caption overlaps the table grid."
}
```

Use `accepted` for an explicitly reviewed unit without a discovered defect.
Decisions need a named reviewer and timezone-aware timestamp; `defect` also
requires notes. Keep every unit, including pending ones. Reviews must match the
frozen audit plan and contain every unit exactly once; IDs are bound to selected
artifact hashes. The tool validates the record, not the truth of a reviewer claim.

Rebuild the report using saved evidence (no generation or new numerical audit):

```powershell
uv run python scripts\run_gt_audit.py `
  --input-dir outputs\validation\gt_audit_fixtures `
  --output-dir outputs\validation\gt_audit_report --report-only
```

Use `--review-file path\to\reviews.json` with `--report-only` for a separate
review file. `applied_reviews.json` preserves the applied version; its content
hash is exported in the summary. Altered input, result or preview hashes fail
verification. Rerun a numerical audit into a new directory after source/code
fixes; report-only is not a substitute for rerunning changed checks.

Human defect rate is `defect / (accepted + defect)` over preview units. It is
null when no units have been reviewed. PDF and scan units are separate review
observations, not independent source documents. Numerical checks cover complete
GT documents; manual review covers only the selected previews, not unshown pages.
Exit code 1 denotes automatic errors; code 0 does not imply human approval.

## Outputs And Limits

```text
audit_plan.json          # Sealed selection, tolerances and replay setting
audit_evidence.json      # Input-plan binding, code identity and output hashes
document_results.jsonl   # One row per distinct complete source/PDF/GT document
image_results.jsonl      # One row for every selected scan
review_units.json       # Selected PDF-page/scan preview units
reviews.json            # Editable human-review template, initially pending
applied_reviews.json    # Last applied review records
summary.json            # Counts, coordinate errors, clipping and review coverage
previews/               # Original/overlay thumbnails
index.html              # Offline gallery and findings
```

Local engineering evidence on **2026-11-09**:

| Audit | Complete GT documents / pages | Selected scans | Automatic results |
| --- | --- | --- | --- |
| Fresh complex + multilingual fixtures | 10 / 13 | 78 | 0 errors; 122 partial-clipping warnings |
| Historical selection | 18 / 316 | 54 | All 18 document GTs have errors; 45/54 image GTs have errors |

The fresh run covered six languages, seven templates, 7,476 transformed elements,
and all 78 image replays. Maximum coordinate error was approximately `9.1e-13`
pixels. The 91 human-review units remain pending. Local reports:
`outputs/validation/gt_audit_current_20261109_final/index.html` and
`outputs/validation/gt_audit_historical_20261109_final/index.html`.

Historical findings include later-page lines stored in first-page containers,
cross-page parents, missing caption/cell annotations, incomplete scan reading
order, and PDF/GT size mismatches. Numerical affine coordinates still matched
the recorded transforms in checked scans. A structural defect does not by itself
quantify bias in every past OCR quality score: assess task-specific impact and
regenerate affected inputs before paper experiments. Old files were not rewritten.

Legacy headings can also lack annotations of the `text_line` type consumed by
the current quality evaluator, even if other heading elements are present.

This workflow is a standalone CLI/library, not a new FastAPI endpoint or an
automatic gate inside historical experiment scripts. For model comparisons,
prepare a pilot once, audit it with `--pilot-plan`, resolve findings, and run
models on that same frozen selection.

These are engineering fixtures/diagnostics, not approved data, a rights audit,
real-scanner validation, or final paper results. Reviewed source families,
source revisions, licenses, stratified human GT checks and clipping/visibility
policy remain release gates in the [publication plan](icdar-2027-plan.md).

Text embedded inside bitmap figures/formula images is not automatically covered
by vector text-line GT. This audit does not OCR or annotate such pixels. Define
quality-evaluation regions and treatment of figure text before publication;
do not mistake source/geometry consistency for exhaustive page-text annotation.
