# Package Structure

This package is organized around the research pipeline:

1. `sources`: parse external sources such as Wikipedia into normalized source JSON.
2. `document`: shared document-level data structures.
3. `layout`: convert normalized content into placed elements and pages.
4. `render`: render layout results into PDFs/images.
5. `gt`: validate and export ground-truth annotations.
6. `noise`: generate synthetic scans from clean rendered documents.
   `noise.provenance` defines versioned generation traces and seed derivation;
   `noise.scans` applies/replays operations without mutating global RNG state.
7. `eval`: evaluate OCR quality, reading order, document structure, geometry
   matching, and generate experiment dashboards.
8. `benchmark`: typed draft research specifications and content-addressed
   inventories of historical experiment artifacts, with file integrity checks.
   `benchmark.files` shares portable fingerprints; `benchmark.render_snapshot`
   seals source/config/font/asset/code inputs for opt-in render verification/replay.

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
