# Sealed Source And Render Inputs

This opt-in benchmark mode captures exact inputs **before** layout and rendering.
It is separate from ordinary `render`; it never adds guessed provenance to old
PDFs. Source/GT schema remains `0.1`; render-input/provenance schema is `0.1`.

## Capture, Verify And Replay

From the repository root, render the offline example into a new directory:

```powershell
uv run python -m polydocbench render-snapshot examples/complex_document.json -o outputs/snapshots/technical_report --template technical_report
```

Verify the saved input and output bytes without rendering:

```powershell
uv run python -m polydocbench verify-render-snapshot outputs/snapshots/technical_report
```

Replay only from the sealed inputs, with the same generator code and environment:

```powershell
uv run python -m polydocbench replay-render-snapshot outputs/snapshots/technical_report -o outputs/snapshots/technical_report_replay
```

Successful replay compares the PDF and GT hashes with the captured originals.
Both capture and replay require a new/empty output directory and refuse to
overwrite existing artifacts. An interrupted/failed capture can leave a partial
directory; it is not complete without a valid `document_provenance.json`. Review
the failure and choose another empty directory instead of treating it as valid.

```text
technical_report/
  document.pdf
  document_gt.json
  document_provenance.json
  render_inputs.json
  inputs/
    source.original.json
    source.json
    source_evidence/           # only for a revision-bound Wikipedia source
      source.json
      source_provenance.json
      query.json
      parse.json
      page.html
    layout.original.yaml
    layout.json
    render.json
    render.original.yaml       # only with --render-config
    assets/<sha256>.<format>
    fonts/<sha256>.ttf
    licenses/<sha256>.txt
  generator/
    polydocbench/**/*.py
    pyproject.toml
    uv.lock
```

## What Is Fixed

- Exact original JSON bytes and a normalized prepared copy whose graphic
  references point to local assets. The same source-items/flattening helpers
  as the normal loader choose the active content/elements branch. Original
  source files are not modified.
- When the source declares a verified Wikipedia snapshot, the complete raw
  response/HTML/source evidence package and snapshot ID are copied into the
  render bundle. A declaration without valid evidence aborts capture.
- Original layout configuration and the effective selected template, with
  strict layout enabled. Unknown template names fail instead of falling back.
- Effective render settings actually consumed by this mode, original render
  configuration when supplied, and explicit body/fallback/variant font files.
- Actual raster/SVG bytes, original references and prepared-element locations.
  Font license files are copied when present; rights are not automatically verified.
- Current Python package source files, `pyproject.toml` and `uv.lock` when present,
  Git revision/dirty status when available, platform/Python identity and installed
  package versions. This captures actual worktree code even when it is dirty.
- SHA-256/byte sizes and a content-addressed snapshot ID, stored in output GT as
  `metadata.render_snapshot_id`. The final provenance binds both output hashes.

Only the package code and named toolchain inputs are copied. `.env`, `.git`,
notebooks, reports, unrelated `PDB/` and generated outputs are not archived as
generator files. Source JSON and resource URLs may themselves contain private
content: review generated bundles before sharing them publicly.

This mode uses `--font` for the DejaVuSans layout/body family and records that
override explicitly in the effective render settings. Additional configured
embedded variants are copied. Missing or conflicting registered fonts fail;
an already running Python/Jupyter process may require a restart if it registered
a different file under the same font family. Other layout font families are
not yet supported by this mode. Ordinary renderer behavior is unchanged.

Debug overlays are disabled. ReportLab invariant output is enabled, GT generation
timestamps are normalized to the Unix epoch, and prepared resource paths in GT
are bundle-relative. Epoch values are determinism markers, not real capture dates.
These changes permit byte-identical replay in the checked environment without
recording temporary directory names in the output GT.

## Asset And Network Policy

Capture is offline by default. URL graphics require explicit permission:

```powershell
uv run python -m polydocbench render-snapshot examples/wiki_formulas.json -o outputs/snapshots/formulas --template simple_article --allow-downloads
```

Permission allows the existing resolver to use/download URL assets during
capture. The copied asset bytes, not the URL cache state, are the frozen input.
Subsequent rendering/replay uses local copies only. Download failures, missing
images, or formula-only LaTeX with no renderable graphic abort capture; they do
not silently become blank placeholders or text fallbacks.

Self-contained path-based SVGs require the existing `formula` extra to draw.
SVG text, scripts, foreign objects, external hrefs, xml:base and stylesheet URL/
font dependencies are deliberately refused; rasterize/embed them first. Actual
image format is inspected, not trusted from the filename extension.

## Integration With Experiments

Use a new experiment output root; Wikipedia capture and Tesseract still require
the usual setup from [Experiments](experiments.md):

```powershell
uv run python scripts/run_tesseract_ocr_experiment.py --output-dir outputs/experiments/tesseract_snapshots --languages en --article-ids history_russia --templates scientific_paper --page-scope first --profiles clean light_scan medium_scan heavy_scan --variants 1 --pin-source-revisions --snapshot-inputs --allow-asset-downloads
```

`--pin-source-revisions` fixes the source stage; `--snapshot-inputs` fixes the
render stage. `--allow-asset-downloads` grants graphic capture permission.
Do not combine snapshot mode with debug PDFs.

`--reuse --snapshot-inputs` requires a valid saved render bundle and matching
source/template/body-font request. It keeps the frozen configuration/resources,
not newly modified originals. Noise reuse separately checks its recorded inputs
and settings. Existing plain renders are not retrospectively upgraded.

The normal CLI/API `render` entry points do not automatically capture snapshots.
An existing API noise endpoint can consume the new PDF/GT normally. The draft
benchmark matrix is still not an executable corpus-generation recipe.

For the standard experiment tree, [Benchmark Inventory](benchmark-manifest.md)
verifies the render sidecar, original source binding, all dependency copies and
the noise-stage hashes. `verify_manifest` checks the recorded snapshot files too.
Changes to a copied font, asset, config or generator file are detected even when
the already rendered JPEG has not changed.

## Reproduction Boundaries

Verification checks sealed bytes and their recorded relationships; it is not
proof that a dataset is scientifically correct or legally redistributable.
Replay additionally requires the captured generator file set and matching
installed package versions/platform. A bundle can be moved; run replay in a
fresh process so ReportLab does not retain font registrations from a deleted
location. Do not modify installed code to match a snapshot without reviewing it.

The source-code copy is included for audit/reconstruction, not automatically
executed from the bundle. Restore the matching trusted version and environment
before replay. Hashes provide integrity against a trusted saved baseline, not
digital signatures or an attestation against a party rewriting all evidence.

Still unresolved: human source-family review, font/media/code licensing
decisions, annotation quality audit, and independent release reproduction.
Revision-bound capture and split tooling do not approve those decisions. A
render bundle therefore does not by itself close M1/M2.

## Tests

```powershell
uv run python -m pytest tests/test_render_snapshot.py tests/test_benchmark_manifest.py -q -p no:cacheprovider
```

Tests cover exact replay, relocation, removed original resources, configuration/
font variants, network opt-in, missing/unsafe graphics, tampered input/output
files, code/environment drift, pipeline reuse and manifest linkage.
