# Evaluation Protocol

This guide defines OCR quality and reading-order evaluation protocol `0.2`.
The version is exported as `evaluation_protocol_version` by the Python evaluators,
API, and experiment runners. It is independent of source/GT `schema_version`
(`0.1`). Existing unversioned results are displayed as `legacy`, not reinterpreted
as protocol `0.2`. Do not directly compare ordering scores across these protocols.

## Evaluation Inputs

Evaluate one page at a time. Predictions and GT must use the same coordinate
system, scale, and page. For noisy images, use the paired transformed GT in
top-left-origin image pixels, not the original PDF-coordinate GT.

Matching uses axis-aligned bbox IoU, including for rotated scans. Stored polygons
are not currently used for IoU. Text normalization lowercases text, collapses
whitespace, and strips leading/trailing whitespace; punctuation is retained.
Words are whitespace-separated tokens, not language-specific tokenization.

## OCR Quality

Lines are matched greedily in GT input order to the unused prediction with the
highest IoU at or above the configured threshold (default `0.3`). A prediction can match
only one GT line. Precision/recall describe geometry detection, not text accuracy.

| Metric | Definition |
| --- | --- |
| `CER`, `macro_CER` | Mean normalized character edit distance over GT lines |
| `WER`, `macro_WER` | Mean normalized word edit distance over GT lines |
| `IoU` | Mean IoU over all GT lines; unmatched GT lines contribute zero |
| `matched_ratio`, `line_recall` | Matched GT lines / GT lines |
| `line_precision` | Matched predictions / predicted lines |
| `line_F1` | Harmonic mean of line precision and recall |
| `micro_CER` | Total character errors, including unmatched predictions, / GT character count |
| `micro_WER` | Total word errors, including unmatched predictions, / GT word count |

The legacy `CER` and `WER` meanings are preserved: extra predictions do not
affect these GT-line means. Use the new micro metrics and line precision to
measure the effect of extra or duplicated predictions.

For micro metrics, sum edit distances for matched lines; missing GT lines count
as deletions, and every unmatched predicted line contributes its normalized text
length as insertions. No separator characters are added between lines. Exported
`char_errors`, `word_errors`, `gt_char_count`, and `gt_word_count` are sufficient
statistics for pooling results across pages. The CSV summary and dashboard pool
these counts, rather than averaging per-page micro rates. Detection counts are
pooled in the same way for line precision, recall, and F1.

This is a geometry-aligned, insertion-aware metric, not a segmentation-invariant
full-page text metric. A line split/merge or incorrect geometry can incur both
deletion and insertion errors even if the page contains the correct text.

Denominators for text error rates are `max(1, reference_length)`, consistent with
the text metric helpers. Rates may exceed `1` and are not clipped. Empty GT and
predictions yield zero text errors and zero detection precision/recall/F1. With
empty GT but nonempty predictions, legacy CER/WER remain zero, while micro errors
count the predicted text against denominator `1`. Always inspect the counts.

## Semantic Reading Order

The dots.ocr workflow retains the model's returned sequence. Visible GT text lines
are grouped by parent block and ordered using exported reading order. Text-free
images are excluded. Text-first matching can map one predicted block to up to
`max_gt_span` adjacent GT blocks (default `3`); `min_block_similarity` defaults to
`0.3`. Both settings are recorded in the result.

| Metric | Definition |
| --- | --- |
| `ordered_CER`, `ordered_WER` | Text errors after concatenating blocks in sequence order |
| `token_F1` | Multiset token overlap without order |
| `pairwise_accuracy` | Correctly ordered comparable GT pairs / comparable pairs |
| `kendall_tau` | (Correct pairs - inverted pairs) / comparable pairs |
| `matched_block_ratio` | Matched GT blocks / GT blocks |
| `matched_prediction_ratio` | Matched predicted blocks / predicted blocks |
| `order_pair_coverage` | Comparable pairs / all GT block pairs |

Pairs inside a single predicted block are **not observable independently** and
are excluded from pairwise accuracy and tau. Their GT order must not be credited
as a model prediction. Pairs across distinct matched predicted blocks are scored.
For example, output groups `[A, B]`, `[C]` expose pairs A-C and B-C, but not A-B.

`num_order_pairs`, `num_correct_pairs`, `num_inverted_pairs`, and
`num_unresolved_pairs` expose these counts. Unresolved pairs count matched GT
blocks within one predicted block; they do not include unmatched GT blocks.
With no comparable pairs, tau and pairwise accuracy are Python `None` / JSON
`null`, never chance accuracy `0.5`. A single merged output can therefore have
full block coverage but zero pair coverage and undefined ordering scores.

HTML reports show `N/A`; CSV writes an empty metric cell. Group means omit
undefined values and include `valid_order_count`, so missing scores are not
silently treated as zero or successful predictions. Pair coverage averages still
include zero-coverage samples. Ordered CER/WER remain defined and also reflect
recognition errors; they are not pure order metrics. Tau and pairwise accuracy
are related measures, not independent evidence.

`POST /evaluate/ordering` retains the existing line-based geometric column-sorting
heuristic. It uses the same nullable pair metrics, but is not the dots.ocr semantic
ordering experiment and does not measure the model's native returned sequence.

## Reporting and Migration

- New OCR and ordering rows and summaries carry protocol `0.2`.
- Reports accept legacy files separately, but reject mixed protocol versions.
- Rebuilding a dashboard does not recompute metrics from predictions.
- Re-evaluate saved predictions to obtain new scores; changing a version label
  in an old file is not a migration.
- The dots.ocr runner's `--reuse` can recalculate metrics from cached predictions
  in its output directory without a new model request. It rewrites the metrics
  and summary for the selected run, so retain previous experiment results separately.
- OCR count-based fields cannot be reconstructed from old CER/WER averages alone.

Example of re-evaluating cached Tesseract lines without running Tesseract:

```python
import json
from pathlib import Path
from polydocbench.eval import evaluate_ocr_quality, extract_gt_lines, load_gt

root = Path("outputs/experiments/tesseract_quality/en/history_russia/scientific_paper")
gt = load_gt(root / "noisy/page_001/medium_scan_0_gt.json")
prediction = json.loads(
    (root / "predictions/page_001/medium_scan_0_tesseract.json").read_text(encoding="utf-8")
)
metrics = evaluate_ocr_quality(extract_gt_lines(gt, page_number=1), prediction)
print(json.dumps(metrics, indent=2))
```

## Current Limits

Protocol `0.2` does not introduce polygon IoU, global optimal matching,
segmentation-invariant OCR alignment, dataset splits, or confidence intervals.
Docling structure scoring is unchanged: detection at a configured bbox IoU
threshold, normalized type evaluation, and the project-specific weighted
`structure_score`. This score is not COCO mAP and should not be presented as such.
