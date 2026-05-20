# Experiments

This guide describes the first OCR benchmark loop:

```text
Wikipedia pages -> synthetic PDFs -> degraded scans -> Tesseract OCR -> quality metrics
```

## Tesseract Setup

Install the Python dependencies:

```powershell
uv pip install -e ".[degradation,ocr,dev]"
```

Install the Tesseract executable and language packs separately. The default experiment uses:

| PolyDocBench code | Tesseract language | Wikipedia page |
| --- | --- | --- |
| `en` | `eng` | `https://en.wikipedia.org/wiki/History_of_Russia` |
| `ru` | `rus` | `https://ru.wikipedia.org/wiki/%D0%98%D1%81%D1%82%D0%BE%D1%80%D0%B8%D1%8F_%D0%A0%D0%BE%D1%81%D1%81%D0%B8%D0%B8` |
| `fr` | `fra` | `https://fr.wikipedia.org/wiki/Histoire_de_la_Russie` |
| `de` | `deu` | `https://de.wikipedia.org/wiki/Geschichte_Russlands` |
| `es` | `spa` | `https://es.wikipedia.org/wiki/Historia_de_Rusia` |
| `it` | `ita` | `https://it.wikipedia.org/wiki/Storia_della_Russia` |

Check installed Tesseract languages:

```powershell
tesseract --list-langs
```

If `tesseract` works in PowerShell but Python still cannot find it, pass the executable path explicitly:

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --tesseract-cmd "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

## Run The Experiment

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --output-dir outputs\experiments\tesseract_quality --variants 1 --profiles light_scan medium_scan heavy_scan
```

The script runs:

1. Wikipedia parsing for each language.
2. PDF and GT rendering.
3. Scan degradation with paired transformed GT.
4. Tesseract OCR.
5. Quality evaluation with CER, WER, IoU, and matched line ratio.

## Run A Subset

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --languages en ru fr --profiles light_scan --variants 1
```

Reuse already generated source/render/degradation artifacts:

```powershell
uv run python scripts\run_tesseract_ocr_experiment.py --reuse
```

The experiment script prints compact progress by default:

```text
== EN | English ==
[1/4] Parse Wikipedia
[2/4] Render PDF + GT
[3/4] Generate degraded scans + transformed GT
[4/4] Run Tesseract + evaluate
      medium_scan_0: CER=0.403 WER=0.412 IoU=0.479 matched=0.700 lines=48/50
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
    source.json
    document.pdf
    document_gt.json
    degraded/
      light_scan_0.jpg
      light_scan_0_gt.json
      medium_scan_0.jpg
      medium_scan_0_gt.json
    predictions/
      light_scan_0_tesseract.json
      medium_scan_0_tesseract.json
```

`metrics.jsonl` stores one row per language/profile/variant.

`summary.csv` stores aggregated metrics grouped by language and degradation profile.

## Metric Notes

- `CER`: character error rate, lower is better.
- `WER`: word error rate, lower is better.
- `IoU`: average matched line geometry overlap, higher is better.
- `matched_ratio`: share of GT lines matched to OCR lines by IoU, higher is better.

For degraded scans, the script runs Tesseract in image-coordinate mode, so predicted bboxes are evaluated against the transformed degraded GT rather than the original PDF GT.
