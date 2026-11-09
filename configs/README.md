# Configs

Canonical configuration files live here and are used by the `polydocbench`
package.

Current files:

- `layout_templates.yaml` - page and typography templates for layout.
- `render_config.yaml` - renderer configuration defaults.
- `benchmark_icdar2027.json` - draft publication benchmark targets, not executable generation settings.
- `noise_recipes.json` - custom blur sweeps and a faded-camera combination, loaded explicitly with `--noise-config`.
- `noise_calibration.json` - controlled six-effect sweeps with fixed nuisance parameters, used by `scripts/run_noise_calibration.py`.
- `gt_audit_noise.json` - fixed positive/negative rotations and shear for offline GT stress fixtures, not approved OCR severities.

Noise recipe schema, parameter units, replay and example gallery:
[Noise Effects](../tutorials/noise-effects.md).
Page-paired Tesseract calibration, repeats, metrics and limitations:
[Noise Calibration](../tutorials/noise-calibration.md).
GT fixture generation and semantic/geometry checks:
[Ground-Truth Audit](../tutorials/gt-audit.md).

The layout config contains the three original templates and five richer profiles.
Supported table/image/region options are documented in
[Complex Layouts](../tutorials/complex-layouts.md). New profiles use strict
placement so unsupported content is reported rather than silently skipped.

Font paths in `render_config.yaml` are repository-relative. To capture the exact
selected layout, effective rendering settings, fonts and images for a benchmark,
use [Render Snapshots](../tutorials/render-snapshots.md). Ordinary `render` does
not automatically load this YAML; its renderer uses code defaults unless a
configuration is supplied through the Python renderer or snapshot mode.

## Publication Benchmark Specification

`benchmark_icdar2027.json` is a validated draft research matrix, not a renderer or
experiment-runner configuration. Counts are planning targets, not generated data.
See [Benchmark Inventory](../tutorials/benchmark-manifest.md) and the
[ICDAR 2027 roadmap](../tutorials/icdar-2027-plan.md).
