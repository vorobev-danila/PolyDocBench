# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN python -m pip install "uv==0.11.8" \
    && uv sync --frozen --no-dev --no-install-project \
        --extra api --extra noise --extra formula

COPY polydocbench ./polydocbench
RUN uv sync --frozen --no-dev --no-editable \
        --extra api --extra noise --extra formula

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY configs ./configs
COPY examples ./examples
COPY ["DejaVu Sans", "./DejaVu Sans"]

RUN mkdir -p outputs

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

CMD ["python", "-m", "uvicorn", "polydocbench.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
