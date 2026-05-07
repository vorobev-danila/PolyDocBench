# Package Structure

This package is organized around the research pipeline:

1. `sources`: parse external sources such as Wikipedia into normalized source JSON.
2. `document`: shared document-level data structures.
3. `layout`: convert normalized content into placed elements and pages.
4. `render`: render layout results into PDFs/images.
5. `gt`: validate and export ground-truth annotations.
6. `degradation`: generate synthetic scans from clean rendered documents.
7. `eval`: evaluate OCR quality, geometry matching, and reading order.

Canonical project-level directories:

- `configs`: layout and render configuration files.
- `examples`: bundled source fixtures used for smoke tests and demos.
- `notebooks`: exploratory research notebooks; reusable logic should move into
  `polydocbench`.
- `outputs`: generated PDFs, GT JSON, scans, and temporary experiment outputs.
- `render`: legacy compatibility layer for old imports and scripts.
- `scripts`: small manual examples built on the public `polydocbench` API.
- `tests`: pytest coverage for parser, layout, rendering, GT, evaluation, and CLI.

The migration is incremental but the public implementation now lives in
`polydocbench`. Legacy modules in `render/core`, `render/layout_engine`,
`render/render`, and `render/utils` should only re-export canonical classes or
provide thin compatibility entry points.

Ground-truth data now includes stable block/line identifiers and explicit
reading-order lists. Layout ids are generated in `polydocbench.layout.ids`;
reading-order metadata is assigned in `polydocbench.gt.reading_order`.

New code should prefer:

```python
from polydocbench.sources import WikipediaParser
from polydocbench.layout import LayoutEngine
from polydocbench.render import PDFRenderer
from polydocbench.gt import GroundTruthExporter
```
