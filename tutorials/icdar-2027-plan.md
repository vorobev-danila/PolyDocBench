# ICDAR 2027 Publication Plan

Updated: 2026-11-02. This is the working roadmap, not a statement that the
benchmark or the publication is complete. Update milestone status as evidence
and artifacts become available.

## Goal And Scope

Prepare an original main-track paper about controlled multilingual evaluation
of document understanding under layout variation and scan noise.

Working title: **PolyDocBench: Controlled Multilingual Evaluation of Document
Understanding under Layout and Scan Noise**.

Intended contributions:

1. A controlled, versioned corpus with paired content/layout/noise variants.
2. Validated image/GT consistency, including geometric transformations.
3. Reproducible comparative experiments and diagnostic findings across quality,
   reading order, and structure.

Coordinate transformation alone is not claimed as a new algorithm. API, Docker,
test count, and code volume support reproducibility but are not the central
scientific contribution. Do not claim multilingual universality: the initial
six European languages cover mainly Latin and Cyrillic scripts.

## Submission Constraints

- [Main-track CFP](https://icdar2027.org/call-for-papers): abstract 2027-01-31;
  full paper 2027-02-20, 23:59 AoE; Springer LNCS; 17 pages including references;
  double-blind review; no simultaneous submission of the same manuscript.
- [Important Dates](https://icdar2027.org/important-dates) currently lists
  2027-02-28 instead. Ask the organizers to resolve the discrepancy; work to the
  earlier deadline and recheck the live requirements before submission.
- Internal manuscript deadline: **2027-02-12**.
- The CFP currently lists reviews on 2027-04-20, rebuttal on 2027-04-27,
  notification on 2027-05-15, and camera-ready on 2027-06-05. Recheck these dates.
- Agree on authorship and responsibilities before submission; the CFP prohibits
  changes to the author list after submission. Budget for registration and
  in-person presentation if accepted; confirm fees when published.

## Research Questions

- RQ1: How do layout and noise affect each task when source content is paired?
- RQ2: Which language/layout/noise interactions expose different model failures?
- RQ3: How much do GT consistency and matching choices change measured scores?
- RQ4: Which observations persist on independently annotated real documents?

## Milestones And Acceptance Gates

| ID | Status | Target | Deliverable and exit gate |
| --- | --- | --- | --- |
| M0 | Complete | Nov 2 | Roadmap and explicit draft scope recorded in working files |
| M1 | In progress | Nov 15 | Dataset specification, historical inventory, rights audit, pilot budget; no inferred historical settings |
| M2 | In progress | Nov 30 | Per-artifact RNG, sampled parameter trace, clean controls, GT audit, fixed metrics and model configurations |
| M3 | Pending | Dec 20 | Reviewed corpus/splits frozen; main inference cached; Method and Dataset draft |
| M4 | Pending | Jan 15 | Ablations, confidence intervals, real-document validation and error analysis |
| M5 | Pending | Jan 30 | Complete paper, final figures/tables, related-work comparison, abstract submission |
| M6 | Pending | Feb 12 | Internal review, anonymous materials, independent reproduction, release candidate |
| M7 | Pending | Feb 20 | Submission receipt saved; no guarantee of acceptance |

M1 progress:

- [x] Store a validated draft matrix in `configs/benchmark_icdar2027.json`.
- [x] Add typed artifact inventory, SHA-256 fingerprints, verification and gap reports.
- [x] Add revision-bound Wikipedia capture, offline response verification and render-bundle linkage.
- [x] Add review-gated source-family catalogs and deterministic family-level split plans.
- [x] Add frozen paired pilot selection and supervised per-model timing/RSS/failure tooling.
- [ ] Review source families, source revisions, content/media rights and code license.
- [ ] Select the pilot subset and measure inference time, memory, failures and cost.
- [ ] Approve or reduce the main experiment matrix using the measured budget.

Do not mark M1 complete just because an inventory can be generated. The initial
inventory is not a frozen dataset, split assignment, or proof of reproducibility.

Initial local audit (2026-11-02): 162/162 discovered scans accepted by the
inventory checks, from 18 source documents, six languages, three templates and
three noise scenarios. Their saved file hashes verify successfully. They cover
only three inferred article families; all nine historical provenance categories
remain unverified. These figures are an inventory, not paper-ready experimental
results or 162 independent source documents.

M2 progress:

- [x] Local, path-independent artifact/operation seeds; profile/order/variant and concurrency tests.
- [x] Actual sampled parameter trace, input/output hashes, noise environment versions and replay checks.
- [x] Opt-in clean lossless control with pixel-coordinate GT; PNG/JPEG reader support in runners and inventory.
- [x] Requested-pair reuse validation and explicit refusal of historical untraced noise in the Tesseract generator.
- [x] Opt-in sealed source/config/font/asset/code inputs, output binding, integrity checks and exact render replay.
- [ ] Configurable isolated parameter sweeps and calibrated scenarios.
- [ ] Source revision/rights review, GT audit, fixed publication metrics and model baselines.

Noise smoke evidence: an existing scientific-paper PDF was copied into
`outputs/validation/noise_v02`, leaving historical data intact. Clean/light/
medium/heavy traces replayed successfully (4/4); reordered/subselected medium/
heavy variants retained identical encoded bytes (2/2); the new inventory accepted
all four pairs. The historical 162-scan inventory still verifies. This verifies
noise-stage mechanics, not the full corpus or the publication's GT audit.

## Corpus Specification

The draft target is 6 languages x 20 source articles x 6 templates x 3 selected
pages x 4 conditions = **8,640 images** (120 sources, 720 rendered documents,
2,160 base pages). This target includes development and test data; it is not a
count of existing artifacts. The current URL pool has 10 articles per language,
so more verified sources are required. Do not download the larger corpus yet.

Use EN/RU/FR/DE/ES/IT; three basic column layouts and three richer table/figure
layouts; clean/light/medium/heavy conditions with one noisy realization in the
main matrix. Repeat several seeds on a predefined subset. Select up to three
distinct pages deterministically using text/table/figure coverage, with a stated
fallback for short documents. Stratified page selection is planned. Clean
generation is available through the noise API; the draft specification and
inventory command still do not execute this matrix.

Group related source articles across languages into reviewed families. Keep
every page, template and noisy variant of a family in one split. Reserve about
20% of families for development, freeze test before final evaluation, and report
actual counts. Template-held-out evaluation is an optional additional split.

Record source revision/snapshot and hash, asset/font rights and hashes, source
and GT schema versions, layout configuration, source page, DPI, actual sampled
noise parameters, artifact-specific seed, transform, generator commit including
dirty-tree information, dependencies, model checkpoint/prompt and output hashes.
Source/GT schema, manifest schema, dataset release and evaluation protocol are
separate versions. Missing provenance remains unknown, never guessed from the
current environment, filesystem timestamps or filenames.

Potential pretraining overlap with public Wikipedia must be acknowledged.
Source-disjoint test data does not prove absence of pretraining contamination.

## Required Engineering Work

P0 before final data generation:

- Isolate RNG per artifact and operation; persist seed derivation and actual
  sampled values. Filtering or changing iteration order must not change a sample.
- Add clean pixel-coordinate controls. Existing profile names denote different
  operation bundles, not proven monotonically increasing severity.
- Make individual noise parameters configurable for controlled ablations.
- Test transformed geometry and visibility/clipping for text, tables, cells,
  repeated headers, images and captions, including page-spanning blocks.
- Freeze text normalization, label mapping, matching, aggregation, task scope
  and undefined-score rules. Keep historical protocol results separate.
- Cache predictions with configuration identity; retain all selected samples and
  request failures in run logs. Retry policy and evaluation denominator are explicit.
- Add approved code/data licenses, attribution, dataset card and release manifest.

P1: unified model adapters, publication-table exports and independent reproduction.
Do not expand the UI, train a new model, or add effects just to increase feature
count before these gates are met. Nested rich table cells remain a documented
limitation unless they are required by the selected corpus; unsupported content
must be explicitly excluded or fixed, never silently dropped.

## Experiments

| ID | Design | Required evidence |
| --- | --- | --- |
| E0 | Known geometric transformations and stratified manual GT audit | Coordinate error, clipping/visibility checks, defect rate and failure taxonomy |
| E1 | Same selected images across comparable models, clean + three noise scenarios | Main quality/ordering/structure tables with per-language and per-class results |
| E2 | Fixed content; columns and controlled table/figure insertions varied independently | Paired layout effects; do not interpret template changes as isolated column effects |
| E3 | Isolated angle, resolution, JPEG, illumination, morphology; then combinations | Response curves and interactions, not only three bundled profile scores |
| E4 | Corrected versus uncorrected GT; matching and IoU alternatives | Measurement bias, score/ranking sensitivity and known-answer evaluator tests |
| E5 | Independent real documents with compatible task annotations | External validity and synthetic/real limitations; no assumed transfer guarantee |

Quality baselines: Tesseract and a pinned multilingual PaddleOCR configuration.
Ordering: dots.ocr and an independent parser with its native output sequence.
Structure: Docling and an independent detector/parser, with a common reviewed
label mapping. A parser can cover several tasks only when its output supports
the task's annotation unit. Never turn grouped paragraphs into claimed line
detections by prompting, or use GT to reconstruct a model's predicted order.

Begin with a 50-100-page pilot, measured separately for every model. Record cold
start versus warm inference, hardware, timeout/retry counts, throughput and cost.
Slow models can use a fixed, stratified common subset selected before inspecting
their scores. Report the subset and coverage; compare models on paired samples.

## Metrics And Statistical Protocol

- Quality: insertion-aware micro CER/WER, line precision/recall/F1, and an
  explicit split/merge analysis. The current line-aligned score is not
  segmentation-invariant. Optional GT-crop recognition separates recognition
  from detection, without replacing end-to-end evaluation.
- Ordering: pairwise accuracy or Kendall tau plus observable-pair coverage and
  matched-block coverage; ordered CER/WER are secondary and recognition-dependent.
  Pairs inside a merged prediction are not independently observable.
- Structure: class-aware F1 and per-class results; standard COCO mAP only with
  a compliant evaluator and appropriate confidence scores. The project-specific
  `structure_score` is auxiliary, not COCO mAP or a universal metric.
- Evaluate global one-to-one matching versus greedy matching. Compare bbox and
  polygon overlap where both outputs support polygons; never fabricate polygons.
- Use paired deltas and 95% cluster-bootstrap intervals by source family, keeping
  pages/layouts/seeds within their cluster. Report cluster counts, micro/macro
  aggregation, model failures and valid-score denominators. Noise seeds are not
  additional independent source documents.
- Keep conclusions exploratory for a small pilot. Select metrics/thresholds on
  development data, then evaluate test without tuning to its outcomes.

## Paper And Release

Paper: Introduction, Related Work, Generation/GT, Dataset/Protocol, Experiments,
Limitations, Conclusion. Related work must distinguish controlled OCR/layout
evaluation from long-context document QA, including SynthDocBench; feature counts
alone do not establish superiority. Check original papers and licensing terms.

Minimum figures: pipeline, diverse rendered examples with GT, isolated noise
curves, paired layout effects and error cases. Minimum tables: related-work
positioning, corpus statistics, model configurations and main task results.

Release code/configuration, licensed data or a rights-compliant reconstruction
route, cached predictions where allowed, raw sufficient statistics and commands
for recreating paper tables. Archive a tagged release with a persistent identifier.
Review anonymization, statements, licenses, supplemental limits, bibliography and
PDF formatting against the live author instructions before submission.

After submission: prepare a factual rebuttal using cached evidence; after
acceptance, complete camera-ready, archival release, registration and presentation.

## Current Next Step

Keep the historical inventory as a baseline. Use [render snapshots](render-snapshots.md)
and [reproducible noise](reproducible-noise.md) in a separate pilot directory.
Use [revision-bound sources and reviewed splits](source-revisions-and-splits.md) for new data.
Human-review source families/media rights and measure a pilot budget. Parameter sweeps,
GT audits and publication evaluation remain open. Do not silently relabel old
artifacts as newly reproducible samples.

The [pilot tooling](benchmark-pilot.md) supports Tesseract quality, dots.ocr
ordering and Docling structure on one fixed selection. It measures local RSS
and separates inference/evaluation times, but does not infer remote memory,
GPU VRAM, billing, or a verified model checkpoint. An engineering pilot on
historical unassigned scans does not close the reviewed-corpus or all-model
budget gates.

Engineering measurement (2026-11-02): a frozen historical pilot selected 18 base
pages / 54 scan conditions, six languages, three templates, three inferred
families and 11 source documents. Tesseract 5.5.0 completed 54/54 in 131.26 s
on the recorded Windows host; subsequent successful inference mean was 2.25 s,
and sampled process-tree RSS peaked at approximately 215 MiB. The plan and
machine/configuration identity are retained locally under `outputs/planning/`
and `outputs/experiments/pilot_runtime/`. These are feasibility measurements on
unassigned historical data without clean controls, not final paper results or
an approved all-model budget.

A separate one-image Docling CPU smoke run reached the 180 s watchdog limit;
its attempt is retained as `timeout` with no quality/structure score. That is
not an estimate of completed inference latency. A longer bounded Docling run
and the paid remote dots.ocr pilot remain pending; do not expand their full
matrices or claim their budgets have been approved from the Tesseract results.

Render snapshot smoke evidence: the local complex-document fixture was rendered
with `research_illustrated`, `technical_report` and `financial_report` under
`outputs/validation/sealed_pipeline`. Each render replay matched its captured
PDF/GT hashes at the code state used for that capture. Twelve derived clean/
light/medium/heavy scan pairs passed inventory and dependency-file verification.
The final financial-report render also replayed all four noise traces. Historical
162-scan hashes still verify. These are engineering checks, not model benchmark
results; revision/family/split/rights review remains open.

After each tested engineering milestone, commit the scoped changes and push the
active project branch. Do not publish `.env`, reports, generated experiment data
or unrelated working folders; do not force-push to bypass remote changes.
