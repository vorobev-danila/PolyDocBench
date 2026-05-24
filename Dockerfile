# syntax=docker/dockerfile:1

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY polydocbench ./polydocbench
COPY configs ./configs
COPY examples ./examples
COPY ["DejaVu Sans", "./DejaVu Sans"]

RUN python -m pip install --upgrade pip \
    && python -m pip install ".[api,noise,formula]" \
    && mkdir -p outputs

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "polydocbench.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
