# Reproducible Scan Noise And Clean Controls

Noise pipeline **0.2** isolates randomness per artifact and operation. It records
actual sampled parameters and supports replay on the original raster. This is
separate from source/GT schema `0.1`, trace schema `0.1`, and evaluation protocol
`0.2`. A matching version number across these formats has no implied relationship.

## Generate A Paired Dataset

From the repository root, render an input without debug overlays:

```powershell
uv run python -m polydocbench render examples/wiki_formulas.json -o outputs/reproducible_noise/document.pdf --template simple_article
```

Then run Python in the installed environment (or a notebook using that environment):

```python
from polydocbench.noise import pdf_to_noisy_dataset

result = pdf_to_noisy_dataset(
    pdf_path="outputs/reproducible_noise/document.pdf",
    gt_path="outputs/reproducible_noise/document_gt.json",
    output_dir="outputs/reproducible_noise/scans",
    page_index=0,
    n_variants=2,
    seed=42,
    dpi=200,
    profiles=["clean", "light_scan", "medium_scan", "heavy_scan"],
)
print(result["noise_pipeline_version"])
print([(item["profile"], item["image_path"]) for item in result["artifacts"]])
```

This creates **7 pairs**: one `clean_0.png` plus six noisy JPEGs and their
`*_gt.json` files. Clean is a lossless, unmodified RGB PDF raster with an identity
noise transform; its GT still converts PDF points/bottom-left origin to image
pixels/top-left origin. `n_variants` applies only to noisy conditions.

Omitting `profiles` retains the previous default: the three noisy scenarios,
without clean. Empty/duplicate profile lists, negative seeds, nonpositive variant
counts and invalid page indices are rejected. Existing paired PNG and JPEG files
with the same stem are ambiguous and reported instead of silently choosing one.

## Actual Operations

| Operation | Sampled values | Fixed implementation in pipeline 0.2 |
| --- | --- | --- |
| `reduce_resolution` | scale uniformly from 0.4 to 0.8 | Downsample with area interpolation, restore original size with cubic interpolation; minimum dimension 1 |
| `random_affine` | angle uniformly from -2 to 2 degrees; matrix shear perturbation from -0.05 to 0.05 | Centered OpenCV rotation, add perturbation to matrix entry [0,1], linear warp, replicated border; actual 2x3 matrix recorded |
| `illumination_gradient` | independent left/right factors uniformly from 0.8 to 1.0 | Horizontal linear brightness mask |
| `ink_morphology` | `erode` or `dilate` | Grayscale, Otsu threshold, 2x2 kernel, one iteration |
| `jpeg_artifacts` | integer quality from 30 to 70, inclusive | RGB/BGR conversions around OpenCV JPEG encode/decode |

`light_scan`: resolution, illumination, JPEG. `medium_scan`: resolution, affine,
illumination, JPEG. `heavy_scan`: resolution, affine, illumination, morphology,
JPEG. The final noisy file is additionally saved with Pillow JPEG quality 95;
this final encoding is recorded separately, not hidden in the operations list.

These are **scenario bundles**, not calibrated monotonic severity levels.
Different profiles use different random streams even for their shared operations.
Isolated parameter sweeps and paired sampled parameters across profiles remain
future experiment work. Morphology changes ink appearance; its identity geometry
does not claim pixel-perfect ink segmentation GT.

## Seeds And Recorded Evidence

Artifact seed: SHA-256 over the master seed, noise version, input raster hash,
source page number, DPI, profile, and variant. Operation seed: SHA-256 over the
artifact seed, operation name, and occurrence count for that operation. Seeds
are stored as hexadecimal strings to avoid losing integer precision in clients.

The source raster hash includes array shape, dtype and RGB pixel bytes. Output
directories, profile iteration order and total requested variants are not seed
inputs. Identical raster/page/DPI/profile/variant inputs intentionally share the
same realization, even when copied to another folder. Distinct layouts generally
have different raster hashes: this is not common-random-number pairing across
layouts. Whole-file PDF hashes separately record the exact upstream file.

Python and NumPy global RNG states are neither reset nor consumed by built-in
generation. Concurrent calls have independent local streams. Standalone helpers
accept local `random.Random` objects where applicable; `apply_pipeline` and
`apply_pipeline_with_transform` accept an explicit `seed`. Global `random.seed()`
is no longer the way to control these functions. Custom callables may still run
in standalone pipelines, but mark their result untracked and cannot be exported
as versioned built-in profiles.

For paired datasets, `metadata.noise_generation` records:

- trace/noise versions, seed derivation, master/artifact/operation seeds;
- original PDF page, DPI, profile, variant and sampled operation parameters;
- PDF and source GT hashes, original/processed pixel hashes, encoded image hash;
- final encoding and Python/NumPy/Pillow/OpenCV/PyMuPDF versions.

The original source page can be 2 or higher; the resulting scan GT always has
one local page numbered **1**. All experiment runners evaluate that local image
page and retain the original PDF page number in their result rows.

`pdf_to_noisy_images` keeps the `images` return field and additionally returns
artifact traces; each image gets a `*_noise.json` sidecar instead of paired GT.
Source revision, renderer configuration, generator commit, asset/font provenance,
licenses and reviewed splits are **not** established by a noise trace. The
[inventory](benchmark-manifest.md) still reports those gaps.

## Replay

```python
import hashlib
import json
from pathlib import Path
from PIL import Image
from polydocbench.noise import render_pdf_page, replay_noise

paired_gt = json.loads(
    Path("outputs/reproducible_noise/scans/medium_scan_0_gt.json").read_text(encoding="utf-8")
)
trace = paired_gt["metadata"]["noise_generation"]
base, _ = render_pdf_page(
    "outputs/reproducible_noise/document.pdf",
    page_index=trace["source_page_number"] - 1,
    dpi=trace["dpi"],
)
replayed = replay_noise(base, trace)
target = Path("outputs/reproducible_noise/medium_scan_0_replayed.jpg")
Image.fromarray(replayed.image).save(target, "JPEG", quality=95)
assert hashlib.sha256(target.read_bytes()).hexdigest() == trace["image_sha256"]
assert replayed.transform_matrix == paired_gt["metadata"]["transform"]["matrix"]
```

Replay validates the input and processed pixel hashes. It returns pixels before
final file encoding; use PNG for clean and JPEG quality 95 for noisy scans.
Byte-identical results are tested in the same software environment, not promised
across arbitrary OpenCV/Pillow/PyMuPDF versions or hardware. Differences raise a
hash error; use the recorded environment to investigate them.

## Experiment Runner And API

Use a **new output directory** for the new noise version:

```powershell
uv run python scripts/run_tesseract_ocr_experiment.py --output-dir outputs/experiments/tesseract_noise_v02 --languages en --article-ids history_russia --templates scientific_paper --page-scope first --profiles clean light_scan medium_scan heavy_scan --variants 1 --seed 42
```

The runner evaluates only requested profile/variant pairs, not every stale file
in the directory. `--reuse` checks recorded seeds, page, DPI and parent/image
hashes. Missing requested variants trigger generation; incompatible or historical
untraced samples cause an explicit error. Omitting `--reuse` regenerates files,
so keep historical experiments in separate directories. Existing predictions in
other model-runner caches are not automatically invalidated: use separate output
directories for those runners too. Full inference-cache identity is later work.

dots.ocr and Docling discover both paired PNG and JPEG scans. Their
`--profiles clean` filter selects controls. Their inference still requires configured remote
credentials or installed Docling models, respectively. Historical Docling results
for source pages beyond page 1 must be recomputed: the old runner used the source
page number to filter one-page image GT and model output. Saved raw Docling
responses can be reparsed with `--reuse`; stale normalized-only multi-page caches
are refused. Rebuilding a dashboard alone does not repair old metrics.

For `POST /noise/pdf-with-gt`, use the existing request fields and include clean:

```json
{
  "pdf_path": "outputs/reproducible_noise/document.pdf",
  "gt_path": "outputs/reproducible_noise/document_gt.json",
  "output_dir": "outputs/reproducible_noise/api_scans",
  "page_index": 0,
  "variants": 1,
  "seed": 42,
  "dpi": 200,
  "profiles": ["clean", "light_scan", "medium_scan", "heavy_scan"]
}
```

The API returns `noise_pipeline_version` and per-artifact `noise_generation`.
`GET /noise/profiles` includes clean. No new dependencies are required beyond
the existing noise/API extras. See [FastAPI Workflow](fastapi-workflow.md).

## Migration And Tests

The same integer seed does **not** recreate historical unversioned noisy scans.
Pipeline 0.2 changes seed streams and corrects RGB/BGR handling in JPEG noise.
Preserve old artifacts/results, label them legacy, and do not pool releases as
if they were the same conditions. Noise version is included in new metric rows.

```powershell
uv run python -m pytest tests/test_noise.py tests/test_noise_reproducibility.py tests/test_benchmark_manifest.py -q -p no:cacheprovider
```

Tests cover profile/order/variant stability, global RNG isolation, concurrent
calls, exact clean pixels, trace validation, pixel/file replay, local image GT,
manifest linkage, partial reuse and legacy cache refusal.
