# Legacy Compatibility Layer

The implementation has moved to the top-level `polydocbench` package.

This directory is kept so older imports and scripts continue to work during the
migration. New code should import from `polydocbench` directly.

Preferred API:

```python
from polydocbench.layout import LayoutEngine
from polydocbench.render import PDFRenderer
from polydocbench.sources import WikipediaParser
```

Compatibility script:

```powershell
.\.venv\Scripts\python.exe render\run_render.py
```

Canonical project data now lives outside this directory:

- `configs/layout_templates.yaml`
- `configs/render_config.yaml`
- `examples/*.json`
- `outputs/`
