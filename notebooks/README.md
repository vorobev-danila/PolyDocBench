# Notebooks

Exploratory notebooks belong here. Reusable code should be imported from the
`polydocbench` package instead of being duplicated in notebook cells.

- `quality.ipynb`: manual Tesseract line-level OCR quality inspection.
- `noise.ipynb`: manual scan-noise and transformed-GT inspection.
- `dotsocr_ordering.ipynb`: manual semantic-block reading-order inspection for remote dots.ocr predictions.
- `structure.ipynb`: manual Docling structure extraction inspection.

Keep generated scans, GT, model responses and overlays under `outputs/`, not
beside the notebook files. Versioned sample images belong in `examples/assets/`.
The local image cache under `notebooks/outputs/cache/` can be created when a
kernel starts in this directory; it is generated data, not another implementation.

Historical scratch notebooks and diagrams from the former root `PDB/` folder
are preserved locally under ignored `outputs/archive/PDB/`. They are not part of
the supported notebook workflow and are not published with the repository.
