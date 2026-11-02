# Configs

Canonical configuration files live here and are used by the `polydocbench`
package.

Current files:

- `layout_templates.yaml` - page and typography templates for layout.
- `render_config.yaml` - renderer configuration defaults.
- `benchmark_icdar2027.json` - draft publication benchmark targets, not executable generation settings.

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
