# Experiments

This guide describes the first OCR benchmark loop:

```text
Wikipedia pages -> synthetic PDFs -> noisy scans -> Tesseract OCR -> quality metrics
```

## Tesseract Setup

Install the Python dependencies:

```powershell
uv pip install -e ".[noise,ocr,dev]"
```

Install the Tesseract executable and language packs separately. The experiment currently uses:

| PolyDocBench code | Tesseract language |
| --- | --- |
| `en` | `eng` |
| `ru` | `rus` |
| `fr` | `fra` |
| `de` | `deu` |
| `es` | `spa` |
| `it` | `ita` |

Check installed Tesseract languages:

```powershell
tesseract --list-langs
```

If `tesseract` works in PowerShell but Python still cannot find it, pass the executable path explicitly:

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --tesseract-cmd "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

## Run The Experiment

By default, the script runs the first `3` configured articles per language, renders each article with three layout templates, and evaluates only the first rendered page:

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --output-dir outputs\experiments\tesseract_quality --variants 1 --profiles light_scan medium_scan heavy_scan
```

The default matrix is:

```text
3 layout templates x 3 noise profiles x 1 variant = 9 noisy document variants per selected page
```

Default layout templates:

| Template | Column layout |
| --- | --- |
| `simple_article` | one column |
| `scientific_paper` | two columns |
| `magazine_layout` | three columns |

The script runs:

1. Wikipedia parsing for each language.
2. PDF and GT rendering for each selected layout template.
3. Scan noise with paired transformed GT for each selected page/profile/variant.
4. Tesseract OCR.
5. Quality evaluation with CER, WER, IoU, and matched line ratio.

## Wikipedia Article Pool

The experiment contains `10` verified Wikipedia pages per language. Print the full configured URL list:

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --list-articles
```

Available article IDs:

| Article ID | Content area |
| --- | --- |
| `history_russia` | history |
| `linear_algebra` | mathematics |
| `quantum_mechanics` | physics |
| `literature` | literature / biography |
| `cell_biology` | biology |
| `organic_chemistry` | chemistry |
| `climate` | climate science |
| `ai` | computer science |
| `kant` | philosophy |
| `milky_way` | astronomy |

The configured URLs were checked for HTTP `200` responses before being added to the workflow.

## Run A Subset

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --languages en ru fr --profiles light_scan --variants 1
```

Run selected articles:

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --languages en ru --article-ids linear_algebra ai --profiles medium_scan
```

Run all configured articles:

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --article-limit-per-language 0
```

Limit to a fixed number of articles per language:

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --article-limit-per-language 5
```

Run selected layout templates only:

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --templates scientific_paper magazine_layout
```

## Page Scope

Choose how many rendered pages should be converted into noisy scans and evaluated:

```powershell
# First rendered page only
uv run python scripts\run_tesseract_ocr_experiment.py --page-scope first

# First half of rendered pages
uv run python scripts\run_tesseract_ocr_experiment.py --page-scope half

# All rendered pages
uv run python scripts\run_tesseract_ocr_experiment.py --page-scope all
```

`--page-scope all` can be slow for long Wikipedia articles because every selected page is rendered to noisy images for every selected profile and variant.

Reuse already generated source/render/noisy artifacts:

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --reuse
```

The experiment script prints compact progress by default:

```text
== EN | linear_algebra | English ==
[1/4] Parse Wikipedia
-- Template: simple_article --
[2/4] Render PDF + GT
      page_scope=first, selected_pages=[1]
[3/4] Generate noisy scans + transformed GT
[4/4] Run Tesseract + evaluate
      page=1 medium_scan_0: CER=0.403 WER=0.412 IoU=0.479 matched=0.700 lines=48/50
```

To show internal layout engine logs, add:

```powershell
--verbose-layout
```

## Outputs

```text
outputs/experiments/tesseract_quality/
  metrics.jsonl
  summary.csv
  en/
    linear_algebra/
      source.json
      simple_article/
        document.pdf
        document_gt.json
        noisy/
          page_001/
            light_scan_0.jpg
            light_scan_0_gt.json
            medium_scan_0.jpg
            medium_scan_0_gt.json
        predictions/
          page_001/
            light_scan_0_tesseract.json
            medium_scan_0_tesseract.json
      scientific_paper/
      magazine_layout/
```

`metrics.jsonl` stores one row per language/article/template/page/profile/variant.

`summary.csv` stores aggregated metrics grouped by language, layout template, and noise profile.

## Metric Notes

- `CER`: character error rate, lower is better.
- `WER`: word error rate, lower is better.
- `IoU`: average matched line geometry overlap, higher is better.
- `matched_ratio`: share of GT lines matched to OCR lines by IoU, higher is better.

For noisy scans, the script runs Tesseract in image-coordinate mode, so predicted bboxes are evaluated against the transformed noisy GT rather than the original PDF GT.
