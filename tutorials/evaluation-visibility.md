# Evaluation Visibility And Ignore Regions

Protocol **0.3** is an explicit, opt-in document-aware evaluation mode. It
separates geometric visibility facts, task eligibility and prediction masking.
It does not retroactively change historical quality/ordering protocol 0.2 or
the unversioned structure workflow. The reference policy is an engineering
candidate, **not publication approval**.

## Setup

Use the existing `uv` environment, with the extras required for your workflow:

```powershell
uv pip install -e ".[api,noise,ocr,benchmark,dev]"
```

Shapely is now a base dependency and is recorded in `uv.lock`. Polygon
intersection, union and subtraction use its GEOS geometry engine. The engine
version enters the policy identity. No additional system GEOS install is needed
when using a supported binary wheel.

## Reference Rules

The typed, frozen configuration is
[evaluation_visibility.json](../configs/evaluation_visibility.json).

| Task | GT unit | Partially clipped GT | Automatic unannotated-text regions |
| --- | --- | --- | --- |
| Quality | Text line, including table lines | Exclude whole line; never compare a visible fragment to the full source string | Image/formula interiors; captions remain separate eligible text |
| Semantic ordering | Textual parent block | Exclude whole block if any constituent line is not fully visible | Image/formula/table interiors; table-cell text is outside this block protocol |
| Structure | Unique stable layout block | Exclude by default; explicit `structure_partial: "visible"` keeps nonempty visible objects | None: images, tables and formulas are targets, not ignored backgrounds |

Fully outside GT is excluded in every task. Visibility is geometric allocation
area, not an ink mask or a readability estimate. Full visibility uses a fixed
coordinate tolerance of 0.05 pixels by default, not an OCR-score-derived cutoff.
For ordering, a parent allocation may cross the canvas while all its text lines
remain fully visible; text completeness is determined by its constituent lines.

Structure 0.3 also prevents a caption from appearing twice as a grouped text
block and a standalone object: each derived stable block ID is scored once.
The old extractor default is retained for historical reproducibility.

The geometric-line ordering API is a separate baseline: it uses explicit GT line
order and top-left image geometry for its column heuristic in protocol 0.3.
Native dots.ocr predictions are **not** sorted by geometry or GT; only spatially
ignored predictions are removed, preserving their relative model order.

## Conservative Prediction Filtering

A prediction is ignored only when its entire declared spatial geometry is
covered by the union of ignored regions **and** it has no positive-area overlap
with any eligible GT unit. This retains:

- duplicate predictions over valid text;
- wrong text or class over an eligible object;
- predictions spanning ignored and scored content;
- hallucinations wholly outside the canvas;
- unlocalized semantic blocks, which cannot be filtered spatially.

If both bbox and polygon are supplied, their union is used conservatively for
filtering; a contradictory polygon cannot hide an error over the bbox's GT.
Predictions are not clipped first or stripped of text using GT. Axis-aligned
envelopes of excluded units are declared as ignore regions, so common bbox
detectors can be filtered without pretending they returned rotated polygons.
Automatic figure/table regions retain their polygon geometry.

Overlapping masks are unioned, not counted twice. Reported effective ignored
area subtracts eligible GT protection. Its fraction describes annotation-space
area, not an independent sample count or unreadable-pixel percentage.

This conservative rule can retain a padded bbox extending beyond a mask or a
paragraph mixing figure text and a caption. No partial text is fabricated.
Unlocalized predictions remain scored and are counted explicitly; compare
models with compatible output geometry/units and inspect granularity effects.

## Inputs And New GT Metadata

This mode requires valid single-image, page-1, top-left pixel GT with original
transformed polygons. It checks semantic GT integrity and bbox/polygon
consistency before filtering. It does not infer rotated polygons from AABBs or
repair bad annotations. Run the independent [GT Audit](gt-audit.md) first; scope
validation alone does not establish source/pixel authenticity or complete text
annotation.

Newly generated scan GT includes `metadata.geometry_visibility` on each element:

```json
{
  "schema_version": "0.1",
  "coordinate_epsilon_pixels": 0.05,
  "visible_fraction": 0.75,
  "status": "partial",
  "clipped_polygon": [[0, 10], [30, 10], [30, 20], [0, 20]]
}
```

These are geometry facts, not `eligible` labels. Eligibility depends on the task
and policy. Facts are recomputed from polygons; cached status/fraction cannot
override the geometry. Existing GT without this additive metadata is supported
when its polygons/structure are valid, and is not rewritten. Source/GT schema
stays 0.1; pixel noise pipeline stays 0.3 because the pixel operations did not
change. Visibility/policy schema 0.1 and evaluation protocol 0.3 are separate.

Explicit manual regions can be stored in image GT metadata:

```json
{
  "evaluation_ignore_regions": [
    {
      "id": "stamp_1",
      "reason": "unannotated_stamp",
      "tasks": ["quality", "ordering"],
      "polygon": [[10, 10], [90, 10], [90, 40], [10, 40]]
    }
  ]
}
```

Manual overlap excludes the whole affected GT unit, expanding its declared
ignore region accordingly. Record/review these regions before test evaluation.
Changing GT changes its artifact/scope identity; do not edit a sealed dataset in
place. Invalid or duplicate regions fail validation rather than being repaired.

## Python And API

Always supply full image GT, not only an already extracted list of lines:

```python
import json
from pathlib import Path
from polydocbench.eval.scope import load_visibility_policy
from polydocbench.eval.scoped import evaluate_with_visibility

gt = json.loads(Path("outputs/my_scan_gt.json").read_text(encoding="utf-8"))
predictions = json.loads(Path("outputs/my_predictions.json").read_text(encoding="utf-8"))
policy = load_visibility_policy("configs/evaluation_visibility.json")
result = evaluate_with_visibility(gt, predictions, task="quality", policy=policy)
print(result.metrics)
Path("outputs/my_scope.json").write_text(
    json.dumps(result.scope, indent=2, ensure_ascii=False), encoding="utf-8"
)
```

Use `task="ordering"` for native semantic blocks and `task="structure"` for
layout elements. Raw cached predictions can be rescored without model calls,
but their image/model identity must be independently verified; scoring cannot
recover missing historical inference provenance.

FastAPI `/evaluate/quality`, `/evaluate/ordering` and `/evaluate/structure` accept
an optional `visibility_policy` object. Omitting it retains the previous mode.
For example, with an existing image GT file:

```json
{
  "gt_path": "outputs/my_scan_gt.json",
  "page_number": 1,
  "predicted_lines": [],
  "visibility_policy": {}
}
```

An empty object selects the reference defaults. The response includes flat
metrics/coverage plus `evaluation_scope`, with every GT/prediction decision.
The ordering endpoint remains a **geometric line-order** baseline; native
semantic ordering is available through Python, its experiment runner and pilots.

## CLI And Frozen Pilots

All three experiment runners accept:

```text
--visibility-policy configs/evaluation_visibility.json
```

Use a **new result directory**. Existing metrics cannot be overwritten by a
scoped run, and legacy runs cannot overwrite scoped results. Policy is loaded
once per run and copied to the result root. Dashboards/CSV export kept/total GT,
ignored/total predictions, exclusion reasons and empty-GT counts. Detailed
`*_scope.json` sidecars bind GT and predictions to hashes and preserve original
prediction indices. The legacy cache reuse option does not retroactively verify
image/model identity; use fresh predictions or separately verified caches.

Recommended publication-engineering path: use one frozen pilot and explicit
model budgets, rather than treating script caches as measured inference:

```powershell
uv run python scripts\run_benchmark_pilot.py `
  --plan outputs\validation\evaluation_visibility_final\pilot_plan.json `
  --input-dir outputs\validation\gt_audit_fixtures_multilingual_20261109 `
  --output-dir outputs\experiments\visibility_tesseract `
  --engine tesseract --timeout-per-image 120 `
  --visibility-policy configs/evaluation_visibility.json
```

That example plan exists after the local inspection below. A different engine
uses its own timeout/budget and the appropriate native output unit. Pilots
validate GT **before** inference, preserve all selected failures/not-run rows,
save scope ledgers, and separate successful requests from scored images with
eligible GT. Standalone script error logs still need inspection for full coverage.

## Undefined Scores And Comparability

When no eligible GT remains, scores are null, not perfect zero-error scores.
Retained spurious predictions still contribute FP/error counts. Quality micro
aggregation includes those insertions when other images supply a positive GT
denominator; an aggregate with no GT denominator stays undefined. Ordering with
fewer than two eligible GT units has undefined pair coverage/accuracy.

GT eligibility is independent of model output. Exported coverage distinguishes
the original units/pairs from eligible ones and the ordering pairs actually
observable from model groups. Excluded units, annotation area, and multiple
variants of a page are not independent source samples.

Aggregation rejects mixed legacy/0.2/0.3 protocols and differing visibility
policies/GEOS identities. Matching remains the existing task matcher, including
its bbox-IoU and segmentation limitations. Inspect model/matching configurations
as well; a common visibility policy does not make different experiments identical.
Calibration tooling still explicitly uses protocol 0.2 and is not silently
migrated to 0.3. Policy approval and a new reviewed calibration are separate work.

## Local Inspection

With the fresh multilingual fixtures from [GT Audit](gt-audit.md):

```powershell
uv run python scripts\inspect_visibility_policy.py `
  --manifest outputs\validation\gt_audit_fixtures_multilingual_20261109\manifest.json `
  --input-dir outputs\validation\gt_audit_fixtures_multilingual_20261109 `
  --output-dir outputs\validation\evaluation_visibility_final `
  --run-tesseract
```

Choose a new output path if this run exists. Without `--run-tesseract`, the
script computes scope coverage only, never model accuracy. The optional local
smoke selects clean/shear on the first text page per language plus one complex
English page, before inspecting scores. It makes no dots.ocr or Docling call.

Open `index.html`: coverage tables for each task/profile, orange ignored-area
previews, a Tesseract dashboard and a same-prediction protocol comparison.
`coverage.jsonl` explicitly contains non-model inspection rows; legacy reference
metrics remain in a separate file, never pooled with 0.3.

Policy choices affect both denominator and scores. A lower CER after excluding
clipped/unannotated regions is **not an improvement in the recognizer**. Review
regions, freeze rules on development data, and report coverage alongside metrics
before using this policy for publication.

Local engineering run on 2026-11-09: **78 scans**, **234 task-scope rows** and
**14/14 successful native Tesseract requests**. The report is
`outputs/validation/evaluation_visibility_final/index.html`. The input comprises
13 base pages, ten fixture documents, six languages and seven templates, not
78 independent documents or a rights-reviewed development corpus.

| Task | Clean eligible / input units | Shear eligible / input units |
| --- | --- | --- |
| Quality (lines) | 986 / 986 | 910 / 986 |
| Ordering (text blocks) | 82 / 82 | 75 / 82 |
| Structure (unique blocks) | 96 / 96 | 78 / 96 |

Counts sum 13 pages for each condition. Across the separate 14-image OCR smoke,
68 of 1,316 GT lines were excluded, 87 of 1,296 predictions were ignored and one
prediction was protected by eligible GT. The same-prediction protocol comparison
contains both increases and decreases in CER; it is not a recognizer improvement.
Coverage inspection rows contain no model scores. The policy remains a candidate;
human GT review, source rights and publication approval are still outstanding.
