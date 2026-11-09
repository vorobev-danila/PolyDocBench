# Reviewed Development Corpus

This workflow prepares an evidence-bound **development candidate**, not a final
test set or an automatically approved dataset. Human source/rights/GT/protocol
and severity decisions remain explicit. Do not count noisy variants or different
layouts of one source as independent source documents.

## Candidate Design

The checked-in [specification](../configs/development_corpus.json) requests:

- Six languages: EN, RU, FR, DE, ES and IT.
- Two proposed source families, history of Russia and linear algebra, in each
  language: 12 Wikipedia revision snapshots.
- Six templates per source: simple article, scientific paper, magazine,
  technical report, illustrated research and financial report.
- One deterministically selected page per rendered document: **72 base pages**.
- Clean/light/medium/heavy: **288 images**, not 288 independent documents.

Sources are **controlled compositions**, not complete Wikipedia articles. The
recipe retains the first 12 accepted normalized paragraph/heading items, prefix-limits
each to 1,200 characters at a word boundary, and inserts a synthetic vector table
with merged cells and a local bitmap figure after the first two items. Original
remote figures/formulas/tables are omitted. Before selecting text, `prose_without_tex_or_navigation_v1` excludes whole items
containing backslashes, navigation arrows or hatnote metadata. Skipped indices and
reasons are saved; text is not silently repaired. This avoids known raw TeX
artifacts, but is a conservative prose subset, not a complete inline-math parser.
Figure/table captions are localized; table cells are controlled labels/numerals,
not claimed article facts. The figure has no embedded letters/numerals.

The selected page maximizes table/figure class presence, then text-line count,
then earliest page number. This is fixed before OCR; actual counts are recorded
in `page_selection.json`. It does not guarantee every selected page contains
both classes. The media-rich sampling is purposeful, not a representative sample
of naturally occurring documents. Different templates change more than columns.

Two families suffice for an engineering development exercise, not broad
statistical generalization. Translations are not token-aligned content controls.
Reserve **both families and all their translations/variants for development**;
never reuse them as a supposedly untouched test set. A larger reviewed family
catalog and separate test corpus remain required for the paper.

## Capture And Build

Use the repository root, `uv`, installed noise dependencies and new output roots:

```powershell
uv sync --extra noise --extra ocr --extra benchmark --extra dev
tesseract --list-langs
```

Native Tesseract must be installed with `eng`, `rus`, `fra`, `deu`, `spa` and
`ita`. Source capture needs Internet access; rendering/audit and the local OCR
runs use the preserved inputs. No dots.ocr token or Docling model is needed.

```powershell
uv run python scripts\prepare_development_corpus.py capture `
  --output-dir outputs\dev_corpus_prose_20261109
uv run python scripts\prepare_development_corpus.py build `
  --output-dir outputs\dev_corpus_prose_20261109
```

`capture` can resume verified snapshots of the same frozen specification. It
requests exact MediaWiki revisions and stores raw query/parse/HTML evidence.
`build` requires a new/empty `dataset/`; it never overwrites an earlier corpus.
It makes no model calls. Each source composition preserves its original evidence,
explicit recipe, selected text indices and asset hashes. The inventory and sealed
render bundles verify this derived chain, rather than claiming the excerpt JSON
is an unchanged Wikipedia API response. Render replay needs its captured code and
environment; do not edit generator source during generation/replay tests.

Site-wide rights receipts are captured using MediaWiki
[`siteinfo/rightsinfo`](https://www.mediawiki.org/wiki/API:Siteinfo). They are
evidence for review, **not a rights clearance for every excerpt**. Preserve article
revision URLs, contributor-history links, the nature of adaptations and required
attribution. [Wikipedia's reuse guidance](https://en.wikipedia.org/wiki/Wikipedia:Copyrights)
also distinguishes text from media. Do not assign a blanket license to all data
or assume the project's code license covers third-party text/fonts. Project-asset
and font licenses, attribution packaging and the code release license still need
the maintainer's decisions before public redistribution.

## Audit Ground Truth

```powershell
uv run python scripts\run_gt_audit.py `
  --manifest outputs\dev_corpus_prose_20261109\manifest.json `
  --input-dir outputs\dev_corpus_prose_20261109\dataset `
  --output-dir outputs\dev_corpus_prose_20261109\audit `
  --split unassigned --all-base-pages `
  --profiles clean light_scan medium_scan heavy_scan
```

`unassigned` is deliberate until the human review is complete. It does not mean
these sources may later be moved into final test. The audit checks whole PDF GT
documents automatically; manual previews cover only selected pages and scans.
Open `audit/index.html`; inspect original/GT at full resolution for text fidelity,
glyphs, clipping, table spans/cells, captions, ownership and reading order.
Record accepted/defect decisions in `audit/reviews.json` only after viewing them;
use your name, timezone-aware timestamp and useful notes. See [GT Audit](gt-audit.md).
AI-assisted observations are not a substitute for human approval and must be
labelled separately, not entered as the maintainer's accepted decisions.

## Freeze Candidate Evaluation And Recalibrate

[Evaluation settings](../configs/evaluation_publication.json) declare quality
bbox-IoU 0.3, structure bbox-IoU 0.5, semantic-order matching similarity 0.3 and
maximum contiguous GT span 3. The frozen contract also captures text normalization,
matching/aggregation rules, visibility policy, geometry engine and evaluator files.
Defaults are **candidate choices**, not a claim that these thresholds are optimal.

Normalization lowercases and collapses whitespace, preserving punctuation,
accents and Unicode form. Quality uses insertion-aware pooled counts, ordering
preserves native model order, and undefined scores remain null with coverage.
Structure uses the current implementation-bound label aliases and unique block
IDs; this is not a standard COCO evaluator. Known segmentation/matching
limitations and sensitivity experiments remain necessary.

Start with a fixed 12-page, language/template-balanced engineering calibration:

```powershell
uv run python scripts\run_noise_calibration.py `
  --manifest outputs\dev_corpus_prose_20261109\manifest.json `
  --input-dir outputs\dev_corpus_prose_20261109\dataset `
  --output-dir outputs\dev_corpus_prose_20261109\calibration `
  --split unassigned --base-pages 12 --repeats 1 `
  --evaluation-contract configs\evaluation_publication.json
```

The existing six-effect, three-level configuration gives 19 conditions including
clean, **228 requests**. It isolates blur, motion blur, sensor noise, faded ink,
local shadow and bleed-through. It does not isolate geometric effects or establish
that the three bundled light/medium/heavy scenarios have monotonic severity.
Use the same frozen contract on all models through `run_benchmark_pilot.py
--evaluation-contract configs/evaluation_publication.json`; remote/heavy runs
need their own explicit budgets. The Tesseract calibration does not approve them.

Protocol 0.3 is opt-in. Existing 0.2 calibration plan serialization and results are
preserved. New runs save the full candidate contract and reject mixed settings,
changed implementations and changed GT/prediction scope ledgers. Aggregate CSV
includes eligible/input GT, excluded units and ignored predictions. Curves use
complete page cohorts; failures remain in the ledger. No uncertainty or severity
approval is inferred automatically from the curves.

After review, use a new output root for any changed settings and then a larger
fixed development calibration, for example `--base-pages 72`. Do not adjust
noise levels or thresholds on held-out test scores. Recognition-independent
readability/realism review and cross-model validation are separate from CER curves.

Also measure the **existing bundled scenarios** on exactly those same 12 source
pages (48 scans), without selecting a new score-dependent subset:

```powershell
uv run python scripts\run_development_scenarios.py `
  --input-dir outputs\dev_corpus_prose_20261109
```

This writes `scenarios/dashboard.html`, native predictions, scope ledgers and
`scenarios/comparison.json`. Its pooled table uses the complete four-condition
page cohort, retaining failures in `scenarios/run/results.jsonl`. Since bundles
include geometry, clipping may change eligible GT denominators; report coverage
and do not interpret a CER difference as a pure photometric effect. This report
is additional exploratory evidence, not a guarantee of monotonic severity or a
replacement for the bound isolated-effect calibration approval.

## Human Approval Handoff

After the audit and calibration finish:

```powershell
uv run python scripts\review_development_corpus.py prepare `
  --input-dir outputs\dev_corpus_prose_20261109
```

Open `outputs/dev_corpus_prose_20261109/index.html`. The handoff links the GT gallery,
calibration dashboard, family catalog and frozen evaluator. `review_checklist.json`
initially contains pending decisions for every source's rights, source families,
font/project-asset rights, the evaluator and noise severity. Approval/rejection
needs a named human, timezone-aware timestamp and rationale. Keep all decision
units and evidence fingerprints. For family changes or corrected GT, generate
new bound evidence rather than editing a sealed corpus in place.

Verify the decisions and all original evidence:

```powershell
uv run python scripts\review_development_corpus.py check `
  --input-dir outputs\dev_corpus_prose_20261109
```

Exit code 1 is expected while decisions/GT previews remain pending, rejected,
or calibration has unresolved failures. Automatic passing tests cannot clear
these gates. `review_status.json` reports blockers, and never approves final test.
The tool validates integrity and explicit records, not reviewer honesty, legal
sufficiency or the scientific correctness of a claimed approval.

## Local Engineering Evidence

On 2026-11-09 the corrected candidate was created at
`outputs/dev_corpus_prose_20261109`. All 72 selected pages contain a table and
figure. Twelve original Wikipedia captures and 72 render bundles are retained;
the recipes skipped 18 contaminated/navigation text items across the source
prefixes. Sources remain controlled excerpts, not full article reconstructions.

| Check | Observed result |
| --- | --- |
| Full Python suite | 402 passing tests |
| Numerical GT audit | 72 complete documents / 152 PDF pages; 288 selected scans; zero errors |
| Clipping | 51 partial element warnings; no fully clipped elements |
| Affine oracle | 35,164 elements; maximum coordinate error about 1.36e-12 pixels |
| Isolated-effect calibration | 228/228 successful requests; 216/216 noisy-clean pairs |
| Existing bundled scenarios | 48/48 successful requests on the same 12 pages |
| Independent checks | 234 aggregate rows, 228 scope ledgers and 2,188 local links reconciled |
| Human approvals | 16 decisions and 360 GT preview units pending |

On the bundled-scenario subset, all four conditions retained the same 970 GT
lines / 37,937 characters, with no GT exclusions:

| Condition | Pooled micro CER |
| --- | --- |
| Clean | 3.73% |
| Light | 3.63% |
| Medium | 9.06% |
| Heavy | 8.01% |

These small-sample measurements do **not** establish a universal ranking. In
particular, the bundled names are not a validated monotonic severity scale, even
where observed GT denominators agree. The isolated response curves show large
CER increases for strong motion/defocus blur and shadow; sensor noise/faded ink
are nearly neutral at the tested settings. Smaller parameter grids around the
blur/shadow transition and independent model/readability review are needed before
approving a severity scale. Preserve failures and avoid tuning against final test.

The first local composition, `outputs/dev_corpus_20261109`, was superseded after
AI visual inspection found literal TeX fragments. Its calibration generation was
stopped before inference. The corrected composition reused the same revisions
and applies the explicit prose filter; it does not rewrite old artifacts or claim
the original parser now handles all inline mathematics correctly.

Read `AI_VISUAL_REVIEW.md` beside the corrected report. Six rendered examples
and two GT overlays were spot-checked; English flattened inline math and a short
Arabic quotation in German still need human judgement. Neither these spot checks
nor numeric consistency approve source fidelity/typography. Browser screenshot
QA was unavailable; direct image inspection and DOM/data checks were performed.

Source captures/render bundles retain their actual timestamps, code files and
dirty-tree state. Exact replay requires the captured code/environment, not an
assumption that a later checkout matches. The corpus and raw results are local,
ignored artifacts; a final clean tagged generator release, reviewed rights and
a distributable reconstruction package remain publication gates.

Re-run the independent checks without model calls:

```powershell
uv run python scripts\validate_development_evidence.py `
  --input-dir outputs\dev_corpus_prose_20261109
```
