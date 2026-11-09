# Frozen Pilot And Runtime Measurements

Use a small, fixed pilot to measure feasibility **before** expanding the corpus.
The pilot runner evaluates Tesseract quality, dots.ocr semantic reading order,
or Docling structure on the same selected image/GT pairs. It does not regenerate
the dataset or replace the task-specific dashboards.

Audit that same frozen plan with [GT Audit](gt-audit.md) before interpreting
publication results. File hashes alone do not establish valid GT semantics.
The historical set has known container/page, heading-line and reading-order
defects; auditing does not rewrite its inputs or retrospectively approve scores.

## Install

```powershell
uv sync --extra benchmark --extra noise --extra ocr --extra dotsocr --extra structure
```

Tesseract and its six language packs must be installed separately. Docling may
download its model files on first use; allow time and disk space for that setup.
For dots.ocr, configure the API key in the root `.env` as described in
[Experiments](experiments.md). No API key value belongs in a plan or run JSON.

## Select A Paired Pilot

For a reviewed, revision-bound development inventory:

```powershell
uv run python scripts/prepare_benchmark_pilot.py --manifest outputs/experiments/tesseract_pinned/benchmark_release/manifest.json --input-dir outputs/experiments/tesseract_pinned --output outputs/planning/pilot_dev.json --base-pages 18 --split dev --profiles clean light_scan medium_scan heavy_scan
```

This selects 18 distinct `(language, article, source hash, template, PDF page)`
groups, retaining all four requested conditions: 72 images, not 72 independent
pages. Selection cycles through sorted language/template strata; seeded hashes
choose pages inside each stratum. It is independent of manifest record order
and uses no model scores. It is not a guarantee of balanced table/figure content
or independent families. Inspect the reported coverage before approving it.

Selection refuses incomplete inventories, insufficient complete page groups,
and missing requested noise conditions. It verifies all selected file hashes,
embeds the selected manifest and split plan, and seals the plan with SHA-256.
Outputs are exclusive: use a new filename instead of overwriting a frozen plan.
The pilot deliberately does not select `test` samples for configuration tuning.

For an **engineering-only** run on historical data without clean controls:

```powershell
uv run python scripts/prepare_benchmark_pilot.py --manifest outputs/experiments/tesseract_quality/benchmark_inventory/manifest.json --input-dir outputs/experiments/tesseract_quality --output outputs/planning/pilot_historical_54.json --split unassigned --base-pages 18 --profiles light_scan medium_scan heavy_scan
```

This explicit alternative retains the old provenance gaps and unreviewed family
status. It must not be presented as the paper's final dev/test corpus.

## Run Each Engine

Use the **same plan and input root** for all engines, but a new output directory
for each run. The examples below refer to the engineering pilot above:

```powershell
uv run python scripts/run_benchmark_pilot.py --plan outputs/planning/pilot_historical_54.json --input-dir outputs/experiments/tesseract_quality --output-dir outputs/experiments/pilot/tesseract --engine tesseract --timeout-per-image 120
uv run python scripts/run_benchmark_pilot.py --plan outputs/planning/pilot_historical_54.json --input-dir outputs/experiments/tesseract_quality --output-dir outputs/experiments/pilot/docling --engine docling --timeout-per-image 900
uv run python scripts/run_benchmark_pilot.py --plan outputs/planning/pilot_historical_54.json --input-dir outputs/experiments/tesseract_quality --output-dir outputs/experiments/pilot/dotsocr --engine dotsocr --timeout-per-image 240 --request-timeout 180 --max-retries 0
```

These are real inference commands, not dry runs. Remote calls may incur charges.
The runner does not automatically call all three engines. To check plumbing
cheaply, prepare a separate one-base-page smoke plan; do not silently reduce an
already frozen pilot. `--tesseract-cmd`, `--base-url`, `--model`, and
`--api-key-env` override public model connection settings.

One model session persists across the run; Docling reuses its converter and
dots.ocr reuses its API client. Inference and evaluation wall times are recorded
separately. The first image is labelled `first_call`; later images are labelled
`subsequent_call`. This is an operational distinction, **not** proof of a fully
cold start or constant warm-cache conditions. OS/model caches are not cleared.
Tesseract still starts its native OCR process for each image through pytesseract.

## Outputs And Failures

```text
run/
  job.json             # fixed selection and public adapter configuration
  run.json             # host/packages/code identity and run settings
  events.jsonl         # flushed artifact start/result events
  results.jsonl        # one row for every selected image, including failures
  summary.json         # runtime, throughput, statuses and local RSS
  worker.log           # native/model logs; inspect locally before sharing
  predictions/         # normalized predictions and available raw outputs
```

All tasks use the scan's transformed, top-left pixel-coordinate GT with local
image page `1`, independently of the source PDF page number. Metrics use the
existing project evaluators; task semantics are unchanged. Model outputs are
never reused as newly timed inference. Configuration identity includes the
model/prompt/settings, installed package versions, and package-code hash.
Model weights, remote server revision, and font/media rights are not thereby
verified. Review local logs and bundles before publishing them.

Ordinary per-image errors are recorded and processing continues. A hard timeout
or worker crash stops that model session; the in-progress sample is labelled
`timeout`/`worker_failed`, and the remaining selected samples are `not_run`.
The timeout includes inference and evaluation, plus worker setup for the first
image. The supervisor terminates the local worker process tree. A killed client
does **not** guarantee that a remote server cancelled computation or billing.
No selected sample disappears from the denominator. The command exits `1` unless
every selected image succeeds. An interrupted supervisor run may be incomplete;
do not interpret a missing summary as a successful run.

## Interpret The Budget

`summary.json` reports the first-call inference time, mean/median of successful
subsequent calls, successful images per total elapsed minute, success rate, and
sampled peak RSS of the local worker and descendants. Successful-only latency is
subject to censoring when slow samples time out; always show status counts and
the full selected count alongside it. Use `results.jsonl` to inspect per-language,
template, and noise-condition times before extrapolating.

RSS is sampled every 0.1 seconds by default, may miss short peaks, and can count
shared pages more than once. It is not GPU VRAM. For remote dots.ocr it measures
the client tree only, not server memory. GPU memory, server memory, and monetary
cost remain `null` until measured independently; no unverified price is assumed.
Collect provider usage/billing and local accelerator telemetry separately.

As a rough sequential planning estimate, multiply successful subsequent-call
latency by the target image count, add model setup, evaluation and observed
failure/retry allowance. Do not interpret that estimate as a measured full-run
duration, extrapolate CPU measurements to GPU hardware, or choose the final test
set using scores from this pilot. Human family/rights review and an approved
per-model compute budget remain roadmap gates.
