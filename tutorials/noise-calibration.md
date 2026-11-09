# Noise Calibration

Measure how Tesseract responds to controlled, isolated noise parameters on fixed
PDF pages. This engineering workflow complements the bundled scan scenarios; it
does not automatically certify severity levels or scanner realism.

## Setup

Run from the repository root:

```powershell
uv pip install -e ".[noise,ocr,benchmark]"
tesseract --list-langs
```

Tesseract is a separate executable. Install its language packs for the selected
languages (`eng`, `rus`, `fra`, `deu`, `spa`, `ita` for the six-language corpus).
Use `--tesseract-cmd "C:\Program Files\Tesseract-OCR\tesseract.exe"` if it is not
on PATH. No remote model, paid API, or Docling installation is required.

## Controlled Matrix

The typed configuration is [noise_calibration.json](../configs/noise_calibration.json).
These parameter values are candidates for measurement, not approved severity labels.

| Effect | Swept parameter | Three levels | Fixed nuisance parameters |
| --- | --- | --- | --- |
| Defocus | `sigma_pixels` | 0.8, 1.6, 2.6 | Gaussian kernel convention from noise 0.3 |
| Motion blur | `length_pixels` | 3, 7, 13 | Angle 20 degrees |
| Sensor noise | `sigma` | 5, 12, 24 | Same standard-normal field across levels within each page/repeat |
| Faded ink | `retained_contrast` | 0.7, 0.4, 0.2 | Blend toward white |
| Local shadow | `strength` | 0.2, 0.45, 0.7 | Center (0.5, 0.5), radii (0.4, 0.4), relative coordinates |
| Bleed-through proxy | `opacity` | 0.08, 0.18, 0.30 | Mirrored self-page, sigma 1.2 pixels, shifts (12, 12) pixels |

The raster resolution is fixed at **200 DPI**. Blur and displacement values are
in raster pixels; sensor sigma is in 0-255 intensity units. Faded-ink levels
decrease because less retained contrast means greater nominal impairment.
The bleed-through example is a synthetic proxy, not a real reverse-side scan.

Each base page has one lossless PNG clean control. Deterministic effects have
one image per level. Sensor noise has three fields per page by default; the
fields differ across pages/repeats, but are shared across sigma levels. There
is no hidden JPEG encoding or geometric transformation. Generation verifies
that clean/noisy GT content and geometry are identical.

Default matrix: `1 clean + 5 effects * 3 levels + 3 sensor levels * 3 repeats = 25`
images per base page. Twelve base pages therefore produce 300 images, not 300
independent documents. `--repeats` changes only sensor-field repeats.

## Select And Run

For publication development, first create an integrity-checked inventory with
reviewed source families and a reviewed `dev`/`test` split, as described in
[Source Revisions And Splits](source-revisions-and-splits.md). Example, assuming
that reviewed inventory has been saved at the paths below:

```powershell
uv run python scripts\run_noise_calibration.py `
  --manifest outputs\reviewed_corpus\manifest.json `
  --input-dir outputs\reviewed_corpus `
  --output-dir outputs\experiments\noise_calibration_dev `
  --split dev --base-pages 12 --repeats 3
```

The output directory must be **new or empty**. Selection cycles through languages
first, then templates, with seeded hash ranking within each stratum. It is
deterministic under inventory reordering. Small selections need not cover every
language/template combination; inspect the saved selection. Unsupported
languages or insufficient eligible pages fail before generation. The input
inventory must have no unresolved issues.

An explicit engineering run on the existing historical inventory is also supported:

```powershell
uv run python scripts\run_noise_calibration.py `
  --manifest outputs\experiments\tesseract_quality\benchmark_inventory\manifest.json `
  --input-dir outputs\experiments\tesseract_quality `
  --output-dir outputs\experiments\noise_calibration_pilot_v2 `
  --split unassigned --base-pages 6 --repeats 3 --timeout-per-image 120
```

Choose another output path if that run already exists. This six-page selection
contains one page per language, spread over three templates, and produces 150
images / 144 noisy-clean pairs. It remains **unassigned historical data**:
running calibration does not approve its source revisions, families, or rights.
Only saved PDF pages are rasterized; parsing/layout are not rerun or silently
updated. Existing historical files are not modified.

The configuration/selection are frozen before inference. The supervised
[pilot runner](benchmark-pilot.md) retains every selected image with its status,
separates inference/evaluation time, and applies the per-image watchdog. A
timeout is not a completed-latency measurement and never receives a quality score.

## Metrics And Denominators

- Evaluation uses quality protocol **0.2**: insertion-aware line-aligned error
  counts and line detection precision/recall/F1, at the pilot's recorded IoU
  threshold (default 0.3).
- Micro CER/WER pool character/word errors and GT counts, rather than averaging
  per-image rates. They remain segmentation-sensitive and may exceed 1.
- Clean and noisy observations must have the same GT denominators. Deltas are
  `noisy - clean`, not relative percentage changes. Error-rate deltas are
  displayed in percentage points; F1 chart deltas use score units.
- For each effect/scope, all levels and sensor repeats use the **same complete
  page cohort**. A page with any missing/failed condition for that effect is
  excluded from all its curve points, not just the failed level.
- `expected_pairs`, `available_pairs`, `curve_pairs`, and selected/complete page
  counts are exported separately. Complete-case curves can still have selection
  bias: inspect the full failure ledger, especially under severe noise. Missing
  scores are null, not zero.
- Sensor repeats are pooled within a level with equal repeat counts per complete
  page; they are not independent source samples. No confidence intervals or
  automatic severity approvals are computed. Use reviewed family-level clusters
  and a larger development corpus before making publication claims.

Adaptation, binarization, and segmentation can make responses non-monotonic.
An apparent improvement over clean is retained; the code does not force sorted
scores or rename the levels to hide it.

## Engineering Pilot Observations

Local smoke run on 2026-11-03: Tesseract 5.5.0 completed **150/150 images**;
all **144/144 pairs** were available. The fixed selection contained six first
pages (one per language), two pages per template, and three inferred source
families. All 180 aggregate rows were checked independently against raw counts.
GT content/geometry matched clean for all 150 images; clean and the strongest
level of every effect replayed pixel-exactly on all six pages (42 replays).
Historical 162-scan file hashes still verified.

| Effect | L1 micro CER | L2 micro CER | L3 micro CER |
| --- | --- | --- | --- |
| Defocus | 0.87% | 0.83% | 72.01% |
| Motion blur | 0.84% | 36.04% | 75.31% |
| Sensor noise | 0.93% | 0.84% | 1.71% |
| Faded ink | 0.99% | 0.94% | 0.97% |
| Local shadow | 0.98% | 1.15% | 75.15% |
| Bleed-through proxy | 0.97% | 0.87% | 2.25% |

The paired clean micro CER was approximately **0.92%**. These measurements show
that nominal parameter levels are not comparable severities across effects.
They motivate denser sampling around abrupt blur/shadow transitions and further
review of readable faint-ink/duplex settings, not automatic threshold changes.

This tiny, unassigned sample does not independently cross every language,
article family, and template. Its per-language/template scopes are descriptive,
not causal estimates of language effects. No confidence intervals, severity
approval, or publication-corpus review are implied. Raw local evidence is under
`outputs/experiments/noise_calibration_pilot_v2/`; generated data are not shipped
with the repository. The first interrupted attempt remains separately preserved
under `outputs/experiments/noise_calibration_pilot/` and is not used in this report.

The subsequent [GT audit](gt-audit.md) found inherited container/parent,
heading-line and reading-order defects in historical inputs. Exact replay and
clean/noisy GT equality do not repair those source defects or certify annotation
validity. Preserve this calibration as engineering evidence; use fresh audited
inputs and reviewed development sources before approving publication severities.

## Inspect Or Rebuild Results

Open `outputs/experiments/noise_calibration_pilot_v2/dashboard.html` locally.
The self-contained Plotly report has effect, language/template scope, and metric
selectors, paired response curves, denominator tables, and illustrative clean/
noisy crops. Crops are selected after evaluation by page CER increase and are
not localized error annotations. The plots do not need an internet connection.

```text
noise_calibration_pilot_v2/
  calibration_plan.json       # Versioned settings, input hashes, fixed selection
  dataset/                    # Copied PDF/source dependencies and new PNG/GT pairs
  manifest.json               # Generated image/dependency hashes
  pilot_plan.json              # Exact model input selection
  run/run.json                # Engine, environment, configuration identity
  run/results.jsonl           # All selected images, including failures/not-run
  paired_results.jsonl        # Every planned noisy/clean pair
  calibration_metrics.jsonl   # Overall/language/template micro aggregates
  calibration_summary.csv     # Same aggregates for external analysis
  validation_report.json     # Integrity, counts, review/uncertainty limitations
  examples/                   # Illustrative paired crops
  dashboard.html              # Offline report
```

Revalidate saved hashes/plan bindings and rebuild reports without model calls:

```powershell
uv run python scripts\run_noise_calibration.py `
  --output-dir outputs\experiments\noise_calibration_pilot_v2 --report-only
```

Calibration schema 0.1, noise pipeline 0.3, and default evaluation protocol 0.2 are
separate identities. The plan, recipe parameters, model configuration, raw
counts, file hashes, and local environment support inspection/reproduction;
they do not retroactively recover missing historical provenance. See
[Noise Effects](noise-effects.md), [Evaluation Protocol](evaluation-protocol.md),
and the [publication roadmap](icdar-2027-plan.md) for the remaining review gates.

## Visibility-Aware Candidate Calibration

Opt into protocol 0.3 with `--evaluation-contract configs/evaluation_publication.json`
and a **new** output directory. The plan records matching thresholds, normalization,
implementation hashes, Shapely/GEOS identity and visibility policy. It preserves
legacy 0.2 plan serialization and does not reinterpret historical results.
Successful scoped rows require matching contract IDs and thresholds, and saved
exclusion ledgers must agree with the exact GT and native predictions. CSV coverage
includes retained/input GT and ignored predictions; the dashboard displays these
counts beside the selected curve. Neither a lower CER nor a completed sweep
automatically approves a severity level.

The complete capture/build/audit/calibration/human-review workflow is in
[Development Corpus](development-corpus.md). Before human approval use the explicit
engineering `--split unassigned`, never a fabricated reviewed split. Source
families used for calibration must remain excluded from the final test corpus.
