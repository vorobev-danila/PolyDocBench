# Development

Real Wikipedia integration checks are opt-in and separate from offline pytest:
see [Live Wikipedia Checks](live-wikipedia-check.md). The cached snapshots and
PDF/GT diagnostics go under ignored `outputs/validation/wiki_tables/`.

This guide covers local development, tests, CI, and contribution flow.

## Install Development Dependencies

```powershell
uv pip install -e ".[api,noise,ocr,dotsocr,structure,formula,dev]"
```

## Run Tests

```powershell
uv run python -m pytest -q -p no:cacheprovider
```

Run a focused test file:

```powershell
uv run python -m pytest tests\test_noise.py -q -p no:cacheprovider
```

## Run API Locally

```powershell
uv run python -m uvicorn polydocbench.api.app:app --reload --host 127.0.0.1 --port 8000
```

## CI

CI runs on every push and pull request to `main` using GitHub Actions:

```text
.github/workflows/tests.yml
```

## Project Structure

```text
polydocbench/
  api/           # FastAPI application and workflow services
  noise/         # PDF-to-scan rendering and noise profiles
  document/      # Shared document model and normalization
  eval/          # OCR quality, ordering, structure, matching, and dashboards
  gt/            # Ground-truth export, schema, validation, reading order
  layout/        # Layout engine, line breaking, placement, templates
  render/        # PDF rendering, debug overlays, element renderers
  sources/       # Source adapters, currently Wikipedia
  cli.py         # Command-line interface

configs/         # Layout and render configuration
examples/        # Example source JSON files
notebooks/       # Research notebooks and experiments
scripts/         # Reproducible Tesseract, dots.ocr, and Docling experiment runners
tests/           # Pytest suite
tutorials/       # Extended user and developer guides
outputs/         # Generated artifacts, ignored by git
Dockerfile       # Container image for API and CLI usage
docker-compose.yml
```

## Workspace Hygiene

The supported implementation is `polydocbench/`; runnable workflows are in
`scripts/`, and the four current research notebooks are in `notebooks/`.

- Keep source fixtures and required assets/fonts in their versioned directories.
- Keep generated data in ignored `outputs/`. In particular, retain experiment
  sources, predictions, metrics and sealed validation snapshots needed for replay.
- `outputs/archive/` holds local historical notebooks/diagrams that are not
  supported implementations. The former root `PDB/` folder was archived there,
  along with old root notebook checkpoints, instead of discarding unique notes.
- Python bytecode, pytest/Jupyter caches, `outputs/test_runs/`, old Docker smoke
  files and packaging-check wheels are disposable. Test runs can recreate them.
- Do not remove `.venv/`, `.env`, `.git/`, required font/image caches, private
  reports or research datasets as part of generic cache cleanup.
- Root `*.egg-info/` is generated build metadata. Remove it only after checking
  that the environment has valid installed distribution metadata and imports.
- Avoid `git clean -fdx`: it would include ignored credentials and research data.

After cleanup, run tests with `PYTHONDONTWRITEBYTECODE=1` and the existing
`-p no:cacheprovider` option to avoid recreating Python/pytest caches. CLI subprocesses
inherit the environment variable. Tests still generate disposable files under
`outputs/test_runs/`; these may be removed again after the suite finishes.

## Recommended Maintenance Improvements

- Add `ruff` for linting and import ordering.
- Add `ruff format` or `black` for formatting.
- Add pre-commit hooks.
- Add coverage reporting.
- Add a `LICENSE` file before public distribution.

## Contribution Flow

1. Fork the repository.
2. Create a feature branch.
3. Add or update tests.
4. Run the test suite locally.
5. Open a pull request with a concise description and example output.
