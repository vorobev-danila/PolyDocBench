# Package Structure

This package is organized around the research pipeline:

1. `sources`: parse Wikipedia into normalized JSON and capture revision-bound API/HTML evidence.
2. `document`: shared document-level data structures.
3. `layout`: convert normalized content into placed elements and pages.
4. `render`: render layout results into PDFs/images.
5. `gt`: validate and export ground-truth annotations.
   `gt.audit` checks semantic/source/table consistency beyond the exchange schema;
   `gt.audit_geometry` is an independent affine/canvas-clipping oracle.
   `gt.visibility` computes task-neutral geometric facts with Shapely/GEOS.
6. `noise`: generate synthetic scans from clean rendered documents.
   `noise.provenance` defines versioned generation traces and seed derivation;
   `noise.scans` applies/replays operations without mutating global RNG state.
   `noise.effects` implements geometry-preserving photometric effects; custom
   recipes and their validated overrides are embedded in generation traces.
7. `eval`: evaluate OCR quality, reading order, document structure, geometry
   matching, and generate experiment dashboards.
   `eval.scope` freezes eligibility/ignore-region decisions; `eval.scoped`
   applies opt-in protocol 0.3 while preserving legacy task evaluator behavior.
8. `benchmark`: typed draft research specifications and content-addressed
   inventories of historical experiment artifacts, with file integrity checks.
   `benchmark.files` shares portable fingerprints; `benchmark.render_snapshot`
   seals source/config/font/asset/code inputs for opt-in render verification/replay;
   `benchmark.splits` gates deterministic family-level splits on explicit review.
   `benchmark.pilot` freezes paired samples; `pilot_runtime` supervises model
   workers with timing, local RSS, and full failure/not-run accounting.
   `benchmark.calibration` freezes controlled noise sweeps and paired aggregation;
   `calibration_run` generates verified inputs and reuses the pilot worker;
   `calibration_report` exports offline response curves and illustrative crops.
   `benchmark.gt_audit` binds numerical checks and explicit human reviews to a
   frozen selection; `gt_audit_report` creates the offline review gallery.

Canonical project-level directories:

- `configs`: layout and render configuration files.
- `examples`: bundled source fixtures used for smoke tests and demos.
- `notebooks`: exploratory research notebooks; reusable logic should move into
  `polydocbench`.
- `outputs`: generated PDFs, GT JSON, scans, and temporary experiment outputs.
- `scripts`: reproducible Tesseract, dots.ocr, and Docling experiment runners.
- `tests`: pytest coverage for parser, layout, rendering, GT, noise, evaluation,
  API, CLI, and experiment configuration.

The public implementation lives in `polydocbench`; root-level wrappers have
been removed.

Ground-truth data now includes stable block/line identifiers and explicit
reading-order lists. Layout ids are generated in `polydocbench.layout.ids`;
reading-order metadata is assigned in `polydocbench.gt.reading_order`.

OCR/ordering protocol identity lives in `polydocbench.eval.protocol`;
nullable metric formatting lives in `polydocbench.eval.reporting`.
Metric definitions and compatibility notes are documented in
[`tutorials/evaluation-protocol.md`](../tutorials/evaluation-protocol.md).

Rich document layout uses `document.tables` for source cell validation,
`document.assets` for image preparation, `layout.tables` for ReportLab-backed
measurement/pagination, `layout.figures` for images with captions, and
`render.elements.table` for vector grids. Text, grid geometry and GT share a
single measured layout; see [Complex Layouts](../tutorials/complex-layouts.md).

`document.fonts` resolves shared font runs for text measurement and PDF drawing;
the bundled symbol fallback and its license live under `fonts/`. Opt-in live URL
checks are in `scripts/check_wikipedia_tables.py`, separately from offline tests.

New code should prefer:

```python
from polydocbench.sources import WikipediaParser
from polydocbench.layout import LayoutEngine
from polydocbench.render import PDFRenderer
from polydocbench.gt import GroundTruthExporter
```
