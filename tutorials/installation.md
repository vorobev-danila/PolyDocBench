# Installation

PolyDocBench uses a `uv`-first workflow.

## Prerequisites

- Python `3.10+`
- `uv`
- Windows, Linux, or macOS
- Optional: Tesseract OCR for OCR extraction experiments

Install `uv` if it is not available:

```powershell
pip install uv
```

## Local Setup

```powershell
git clone https://github.com/vorobev-danila/PolyDocBench.git
cd PolyDocBench
uv sync
uv pip install -e .
```

## Optional Dependency Groups

```powershell
uv pip install -e ".[api]"
uv pip install -e ".[noise]"
uv pip install -e ".[formula]"
uv pip install -e ".[dev]"
```

For the full research stack:

```powershell
uv pip install -e ".[api,noise,formula,dev]"
```

## Verify Installation

```powershell
uv run python -m polydocbench list-templates
uv run python -m pytest -q -p no:cacheprovider
```

## Docker Setup

Build and run the API:

```powershell
docker compose up --build
```

Open:

```text
http://127.0.0.1:8000/docs
```

More Docker examples are available in [Docker](docker.md).
