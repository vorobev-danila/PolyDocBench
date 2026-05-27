# Development

This guide covers local development, tests, CI, and contribution flow.

## Install Development Dependencies

```powershell
uv pip install -e ".[api,noise,ocr,dotsocr,formula,dev]"
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
  noise/   # PDF-to-scan rendering and noise profiles
  document/      # Shared document model and normalization
  eval/          # OCR quality, geometry, and ordering metrics
  gt/            # Ground-truth export, schema, validation, reading order
  layout/        # Layout engine, line breaking, placement, templates
  render/        # PDF rendering, debug overlays, element renderers
  sources/       # Source adapters, currently Wikipedia
  cli.py         # Command-line interface

configs/         # Layout and render configuration
examples/        # Example source JSON files
notebooks/       # Research notebooks and experiments
scripts/         # Small manual workflows
tests/           # Pytest suite
tutorials/       # Extended user and developer guides
outputs/         # Generated artifacts, ignored by git
Dockerfile       # Container image for API and CLI usage
docker-compose.yml
```

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
