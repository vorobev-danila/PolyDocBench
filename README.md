# PolyDocBench

**Synthetic Benchmark for OCR & Document Layout Research**

---

## Motivation & Problem Statement

Modern document analysis and OCR systems require large-scale, diverse, and **well-annotated datasets** for evaluation and training. Extracting layout and reading order from documents is challenging due to:

- Multi-column layouts (articles, magazines, scientific papers)
- Complex elements (headings, formulas, images, tables)
- Varying typographies and fonts

**PolyDocBench** addresses this need by providing a **synthetic document generation framework** that produces:

1. PDF documents with realistic layout
2. Detailed **ground truth annotations** (characters, words, lines, blocks)
3. Full control over layout templates and typography

This enables researchers to benchmark OCR engines, layout analysis algorithms, and reading order models in a controlled environment.

---

## Architecture Overview

PolyDocBench is built as a **hybrid layout engine + renderer** system:

1. **Wiki Parser (`wiki_parser.py`)**  
   Converts Wikipedia JSON dumps into structured content (sections, text, formulas, images).

2. **Layout Engine (`layout_engine/`)**  
   - Generates `LayoutResult` with **bounding boxes** for each document element
   - Supports **single-, two-, and three-column layouts**
   - Applies typography, spacing, and reading order rules

3. **PDF Renderer (`render/pdf_renderer.py`)**  
   - Line-based, modular rendering (TextRenderer, HeadingRenderer, etc.)
   - Integrates **FontManager** for font embedding
   - Supports **debug rendering** with bounding boxes
   - Outputs PDF + ground truth in JSON or COCO formats

4. **Ground Truth Exporter**  
   - Serializes layout and content into machine-readable format for OCR/ML tasks

---

## Repository Structure

```
PolyDocBench/
├── core/
│   ├── __init__.py
│   ├── renderer.py           # Json → PDF (уже есть)
│   ├── layout_engine.py      # движок верстки
│   ├── primitives.py         # базовые элементы (Bbox, DocumentElement и т.д.)
│   └── containers.py         # контейнеры и страницы
├── utils/
│   ├── __init__.py
│   ├── wiki_parser.py        # парсер для статей Wikipedia
│   └── bbox_calculator.py    # расчет bounding boxes
├── examples/		              # Примеры json
│   ├── wiki_ru.json
│   └── wiki_eng.json
├── configs/
│   ├── render_config.yaml    # конфигурации: язык, шрифты, DPI, стиль
│   └── layout_templates.yaml # шаблоны макетов
├── output/                   # папка для результатов
│   ├── pdfs/                 # сгенерированные PDF
│   └── ground_truth/         # JSON с координатами
├── run_render.py             # точка входа
└── requirements.txt          # зависимости
└─ README.md
```

---

## Input Data Format

PolyDocBench accepts **Wikipedia JSON dumps** structured as:

```json
{
  "title": "Physics",
  "sections": [
    {
      "heading": "Classical Mechanics",
      "content": [
        {"type": "paragraph", "text": "Newton's laws ..."},
        {"type": "formula", "latex": "F=ma"},
        {"type": "image", "url": "..."}
      ]
    }
  ]
}
```

The parser (`wiki_parser.py`) converts this into a normalized internal representation for the layout engine.

---

## Ground Truth Format

Ground truth is exported as JSON (and optionally COCO/page-XML) with:

- `metadata` (generator, export time, coordinate system)
- `pages` (dimensions, page number)
- `elements`:
  - `id`, `type`, `bbox` (x, y, width, height)
  - `content` or `lines`
  - `font_name`, `font_size`
  - `reading_order` (optional)

Example snippet:

```json
{
  "metadata": {
    "generator": "PolyDocBench",
    "export_time": "2026-01-21T12:34:56",
    "coordinate_system": "points",
    "origin": "bottom-left"
  },
  "pages": [
    {"page_number": 1, "width": 595, "height": 842}
  ],
  "elements": [
    {
      "id": "text_1",
      "type": "text_line",
      "bbox": {"x":50, "y":700, "width":495, "height":12, "page":1},
      "content": "Newton's laws of motion ...",
      "font_name": "DejaVuSans",
      "font_size": 12
    }
  ]
}
```

---

## Quick Start / Example

```bash
# Clone repository
git clone https://github.com/vorobev-danila/PolyDocBench.git
cd PolyDocBench

# Install dependencies
pip install -r requirements.txt

# Run a simple PDF generation
python examples/run_render.py
```

Example in Python:

```python
from render.pdf_renderer import create_simple_pdf

create_simple_pdf(
    text="Hello, PolyDocBench!",
    output_path="output/simple_test.pdf"
)
```

---

## Configurations & Templates

- **Render config:** `render/configs/render_config.yaml`
  - Fonts, colors, debug options, export formats
- **Layout templates:** `render/configs/layout_templates.yaml`
  - Single-column (`simple_article`), two-column (`scientific_paper`), three-column (`magazine_layout`)
  - Margins, columns, typography, and element placement rules

Example usage:

```python
from render.pdf_renderer import PDFRenderer

renderer = PDFRenderer(config_path="render/configs/render_config.yaml")
renderer.render(layout_result, output_pdf="output/document.pdf")
```

---

## Research Use Cases

PolyDocBench can be used for:

1. **OCR Evaluation**
   - Synthetic PDFs with known ground truth
   - Multi-font, multi-column, multi-language tests

2. **Layout Analysis**
   - Benchmarking document segmentation, reading order prediction
   - Testing column and header detection algorithms

3. **Machine Learning Training**
   - Generate large-scale datasets with character/word/line-level annotations
   - Fine-tuning layout-aware OCR models

4. **Document Rendering Experiments**
   - Explore typography, spacing, and readability effects on OCR
   - Debug bounding box visualization for research papers

---

## License

MIT License – see [LICENSE](LICENSE)

---

## Citation

If you use PolyDocBench in research, please cite:

```
@misc{PolyDocBench2026,
  title={PolyDocBench: Synthetic Benchmark for OCR and Layout Research},
  author={Danila Vorobev},
  year={2026},
  howpublished={\url{https://github.com/vorobev-danila/PolyDocBench}}
}
```

