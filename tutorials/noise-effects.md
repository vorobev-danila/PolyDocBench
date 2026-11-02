# Configurable Scan Noise Effects

Pipeline **0.3** adds six photometric operations, seven built-in scenarios,
custom JSON recipes and a reproducible visual preview. No new dependency is
required beyond the existing `noise` extra. Perspective, page curl, occlusion
masks, Poisson sensor noise and printer dropouts are not implemented in this stage.

## Inspect The Examples

From the repository root:

```powershell
uv run python scripts/preview_noise_effects.py
Start-Process outputs/noise_gallery_v03/index.html
```

The gallery is a static local HTML file; no server or external JavaScript is
needed. It contains 36 image/GT pairs: three first-page previews, each with 12
conditions, including clean, six isolated effects, a camera-like combination,
the existing heavy scenario, and three fixed blur settings. It links full-size
images, enlarged crops, red GT overlays, GT JSON and actual sampled parameters.
Each case also has `contact_sheet.png`; `validation_report.json` contains exact
replay and geometry checks. Re-running requires a new/empty `--output-dir`.

The table/figure case renders `examples/complex_document.json` with
`technical_report`. The English and Russian cases use the first 18 text elements
of `wiki_formulas.json` and `wiki_formulas_ru.json`, with two/three columns.
They are explicitly marked preview subsets, not a complete benchmark corpus.
Rendering disables debug boxes; the GT overlays are separate images.

## Built-In Effects

| Profile | Operation and sampled parameters at 200 DPI | Output |
| --- | --- | --- |
| `defocus_scan` | Gaussian blur, sigma 1.2-2.2 pixels | PNG |
| `motion_scan` | Centered line-kernel blur, odd kernel length derived from 7-13 pixels; angle -60 to 60 degrees | PNG |
| `sensor_noise` | Independent additive Gaussian RGB noise, sigma 8-20 on the 0-255 intensity scale; recorded local PCG64 seed | PNG |
| `faded_print` | Retain 0.25-0.5 of contrast against white paper | PNG |
| `shadow_scan` | Smooth elliptical darkening; strength 0.35-0.65, relative center/radii recorded | PNG |
| `duplex_scan` | Blurred, shifted, mirrored self-page proxy; opacity 0.12-0.25 | PNG |
| `camera_capture` | Defocus, motion, local shadow, sensor noise, then explicit JPEG artefacts | PNG |

Default blur sizes and bleed offsets scale with DPI; trace values are the actual
pixels used. Motion lengths are rounded to odd integers. Blur sigma and motion
kernel length are capped at 12/101 respectively. Explicit recipe pixel values
are **not** automatically scaled. Contrast, opacity and relative shadow geometry
do not scale with DPI.

The duplex effect is a synthetic proxy, not a captured reverse page. It uses no
untracked cache or donor article, and mirrored background text is not added to
front-side GT. Fading affects the whole printed image, including figures; it is
not a foreground-segmented physical ink model. Sensor noise is a Gaussian proxy,
not a calibrated camera model. Scenarios are hypotheses for robustness testing,
not validated real-scanner distributions or guaranteed severity rankings.

## CLI And Python

Render an ordinary document without debug boxes, then generate new effects:

```powershell
uv run python -m polydocbench render examples/complex_document.json -o outputs/noise_demo/document.pdf --template technical_report
uv run python -m polydocbench noise outputs/noise_demo/document.pdf --gt outputs/noise_demo/document_gt.json -o outputs/noise_demo/scans --profiles clean defocus_scan motion_scan sensor_noise faded_print shadow_scan duplex_scan camera_capture --dpi 200 --variants 1 --seed 42
```

Without `--gt`, `noise` saves image files and `*_noise.json` trace sidecars.
Python entry points accept the same `profiles` and optional `config`:

```python
from polydocbench.noise import load_noise_config, pdf_to_noisy_dataset

result = pdf_to_noisy_dataset(
    "outputs/noise_demo/document.pdf", "outputs/noise_demo/document_gt.json",
    "outputs/noise_demo/sweep", profiles=["blur_mild", "blur_moderate", "blur_strong"],
    n_variants=1, seed=42, dpi=200,
    config=load_noise_config("configs/noise_recipes.json"),
)
```

## JSON Recipes

`configs/noise_recipes.json` contains a fixed sigma sweep (0.8, 1.6, 2.6 pixels)
and a `faded_camera` combination. Configuration schema is `0.1`:

```json
{
  "schema_version": "0.1",
  "profiles": {
    "my_camera": [
      {"name": "motion_blur", "parameters": {"length_pixels": 9, "angle_degrees": 20}},
      {"name": "sensor_noise", "parameters": {"sigma": 12}}
    ]
  }
}
```

Missing parameters are sampled from operation defaults. All actual parameters,
including the sensor RNG seed, enter the trace. Custom names cannot replace
built-ins. Values and unknown keys are validated; motion lengths must be odd.
Recipes specify affine angle/shear, not a separate hand-written matrix; the
actual matrix is computed and applied to both pixels and GT.

```powershell
uv run python -m polydocbench noise outputs/noise_demo/document.pdf --gt outputs/noise_demo/document_gt.json -o outputs/noise_demo/custom --noise-config configs/noise_recipes.json --profiles blur_mild blur_moderate blur_strong faded_camera --variants 1
```

The Tesseract runner accepts `--noise-config` with these custom names in
`--profiles`. Use a new experiment root. `--reuse` checks both the noise version
and the recipe definition, in addition to existing input/settings/hash checks.
Docling/dots.ocr and inventory readers already discover the exported PNG pairs.

FastAPI `/noise/pdf` and `/noise/pdf-with-gt` accept `config` containing the same
JSON object, alongside `profiles`. `/noise/profiles` lists built-in profiles;
request-local custom recipes do not alter the global list.

## GT, Replay And Compatibility

All six new operations preserve spatial coordinates; image size, text content,
reading order and polygons remain unchanged relative to clean pixel GT.
Combinations containing affine steps still compose the geometry and transform
GT normally. This does **not** prove readability or pixel-accurate ink masks.
Very faint/blurred text may be unrecoverable; audit severity on development data
before fixing the evaluation protocol. Occlusion/visibility rules are future work.

New profiles and custom recipes use PNG so isolated sweeps have no hidden final
JPEG loss. The camera scenario explicitly includes a JPEG encode/decode step.
Existing light/medium/heavy scenarios retain their original operation bundles
and final JPEG quality 95. Default generation still selects only these three.

New generation uses noise version `0.3`; source/GT/trace schema remains `0.1`.
The version is part of seed identity, so the same master seed produces a new
realization compared with `0.2`. Existing `0.2` traces still validate and replay
using their stored operations; they are not silently reused as `0.3` runs.
Preserve old datasets/results and keep versions separate. Custom recipe steps
and their overrides enter seed derivation, so changing a recipe changes its
artifact identity. Global Python/NumPy RNG state remains untouched.

```powershell
uv run python -m pytest tests/test_noise_effects.py tests/test_noise_reproducibility.py tests/test_api_app.py -q -p no:cacheprovider
```
