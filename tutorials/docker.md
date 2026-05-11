# Docker

PolyDocBench can run as a containerized FastAPI service or as a CLI tool inside the same image.

## Build the Image

```powershell
docker build -t polydocbench:local .
```

The image installs these optional dependency groups:

- `api`
- `degradation`
- `formula`

This supports the main pipeline:

```text
parse -> render -> degrade -> evaluate
```

## Run the API

```powershell
docker compose up --build
```

Open:

```text
http://127.0.0.1:8000/docs
```

The compose file mounts local `outputs/` into `/app/outputs`, so generated PDFs, GT JSON files, image caches, and noisy scans remain available on the host machine.

## Run CLI Commands

List templates:

```powershell
docker compose run --rm polydocbench-api python -m polydocbench list-templates
```

Render a bundled example:

```powershell
docker compose run --rm polydocbench-api python -m polydocbench render examples/wiki_formulas_isl.json -o outputs/wiki_formulas_isl.pdf --template simple_article
```

## Run Degradation from the Container

```powershell
docker compose run --rm polydocbench-api python -c "from polydocbench.degradation import pdf_to_noisy_images; print(pdf_to_noisy_images('outputs/wiki_formulas_isl.pdf', 'outputs/wiki_formulas_isl_scans', n_variants=1, profiles=['light_scan']))"
```

## Stop the API

```powershell
docker compose down
```

## Notes

- The container exposes port `8000`.
- `outputs/` is mounted as a writable volume.
- The image includes the bundled DejaVu font files used by the default renderer.
- OCR engine binaries are not installed in the image. Add them later if containerized OCR extraction becomes part of the workflow.
