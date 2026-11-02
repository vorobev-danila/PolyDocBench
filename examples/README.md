# Examples

Source fixtures and bundled examples live here.

The `wiki_formulas*.json` files are parsed Wikipedia samples that can be used
for local renderer and layout smoke tests. `wiki_history_russia.json` is a
larger schema-versioned article fixture for multi-page experiments.

Large generated PDFs, scans, and ground-truth outputs should go to `outputs/`
and stay out of version control.

`complex_document.json` is an offline fixture with merged table headers, empty
cells, figure/table captions and a local bitmap in `assets/benchmark_chart.png`.
The chart is an illustration, not an experimental result. Its regeneration script
is `scripts/generate_complex_example_asset.py`.

```powershell
uv run python -m polydocbench render examples\complex_document.json -o outputs\complex_layouts\research_illustrated.pdf --template research_illustrated
```

See [Complex Layouts](../tutorials/complex-layouts.md) for the new profiles and GT fields.
