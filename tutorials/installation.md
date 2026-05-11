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
uv pip install -e ".[degradation]"
uv pip install -e ".[formula]"
uv pip install -e ".[dev]"
```

For the full research stack:

```powershell
uv pip install -e ".[api,degradation,formula,dev]"
```

## Verify Installation

```powershell
uv run python -m polydocbench list-templates
uv run python -m pytest -q -p no:cacheprovider
```

## Docker Note

Docker packaging is not included yet. A future production Dockerfile should install the package with the required extras, expose port `8000`, and run:

```dockerfile
CMD ["python", "-m", "uvicorn", "polydocbench.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```
