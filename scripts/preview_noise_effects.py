"""Render three offline previews and build a local, self-contained noise gallery."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import html
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from polydocbench.document.normalize import flatten_source_content
from polydocbench.document.schema import validate_source_document
from polydocbench.layout import LayoutEngine
from polydocbench.noise import (draw_gt_overlay, load_noise_config, pdf_to_noisy_dataset,
                                render_pdf_page, replay_noise)
from polydocbench.noise.provenance import file_sha256, pixel_sha256
from polydocbench.render import PDFRenderer


CASES = [("tables_figures", "examples/complex_document.json", "technical_report", False),
         ("english_text", "examples/wiki_formulas.json", "scientific_paper", True),
         ("russian_text", "examples/wiki_formulas_ru.json", "magazine_layout", True)]
PROFILES = ["clean", "defocus_scan", "motion_scan", "sensor_noise", "faded_print", "shadow_scan",
            "duplex_scan", "camera_capture", "heavy_scan", "blur_mild", "blur_moderate", "blur_strong"]
STYLE = """
*{box-sizing:border-box}body{margin:0;font:15px system-ui,sans-serif;color:#202522;background:#f5f7f8;letter-spacing:0}
header,section{padding:24px;max-width:1500px;margin:auto}header{border-bottom:2px solid #237d66}
h1{font-size:28px;margin:0 0 12px}h2{font-size:22px}h3{font-size:16px;margin:0 0 10px;overflow-wrap:anywhere}
a{color:#126b99}nav{display:flex;gap:20px;flex-wrap:wrap}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}
figure{margin:0;background:white;border:1px solid #d3d9dc;border-radius:4px;padding:12px;min-width:0}
.page{width:100%;height:320px;object-fit:contain;background:#e8ecee}.detail{width:100%;aspect-ratio:3.1;object-fit:contain}
figcaption{display:flex;gap:16px;margin:12px 0;flex-wrap:wrap}details{font-size:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere}
.meta{color:#596660;margin:8px 0 18px}@media(max-width:1000px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:620px){.grid{grid-template-columns:1fr}header,section{padding:16px}}
"""


def _prepare_source(original: Path, case: Path, subset: bool) -> Path:
    if not subset:
        return original
    document = validate_source_document(json.loads(original.read_text(encoding="utf-8")))
    items = flatten_source_content(document.source_items()) if document.content else document.source_items()
    # Text-only subsets are previews, not replacements for the original benchmark sources.
    elements = [item for item in items if item["type"] == "paragraph" or item["type"].startswith("heading")][:18]
    prepared = {"schema_version": "0.1", "title": document.title, "url": document.url, "elements": elements,
                "metadata": {"preview_only": True, "original_source": str(original), "selection": "first_18_text_elements"}}
    target = case / "preview_source.json"
    target.write_text(json.dumps(prepared, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _crop_box(gt, size):
    lines = [element for page in gt["pages"] for container in page["containers"]
             for element in container.get("elements", []) if element["type"] == "text_line"]
    box = lines[0]["bbox"]
    x, y = max(0, int(box["x"]) - 8), max(0, int(box["y"]) - 8)
    return x, y, min(size[0], x + 1000), min(size[1], y + 320)


def build_gallery(output: Path, dpi: int = 200, seed: int = 42) -> dict:
    import numpy as np

    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Gallery directory must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    config = load_noise_config("configs/noise_recipes.json")
    sections, reports = [], []
    font = ImageFont.truetype("DejaVu Sans/DejaVuSans.ttf", 18)
    for case_id, source, template, subset in CASES:
        case = output / case_id
        case.mkdir()
        selected = _prepare_source(Path(source).resolve(), case, subset)
        with contextlib.redirect_stdout(io.StringIO()):
            layout = LayoutEngine(font_path="DejaVu Sans/DejaVuSans.ttf").layout_document(selected, template_name=template)
            rendered = PDFRenderer(debug=False).render(layout, case / "document.pdf")
        if layout.warnings:
            raise ValueError(f"Preview render contains unsupported/missing content: {layout.warnings}")
        result = pdf_to_noisy_dataset(rendered["pdf_path"], rendered["gt_path"], case / "scans",
                                      profiles=PROFILES, n_variants=1, dpi=dpi, seed=seed, config=config)
        base, _ = render_pdf_page(rendered["pdf_path"], dpi=dpi)
        clean_gt = json.loads(Path(result["artifacts"][0]["gt_path"]).read_text(encoding="utf-8"))
        crop_box = _crop_box(clean_gt, (base.shape[1], base.shape[0]))
        previews = case / "previews"
        previews.mkdir()
        sheet = Image.new("RGB", (1440, 4 * 220), "#e9eef0")
        draw = ImageDraw.Draw(sheet)
        figures = []
        for index, artifact in enumerate(result["artifacts"]):
            profile = artifact["profile"]
            image_path, gt_path = Path(artifact["image_path"]), Path(artifact["gt_path"])
            trace = artifact["noise_generation"]
            replayed = replay_noise(base, trace)
            with Image.open(image_path) as image:
                decoded = np.array(image.convert("RGB"))
                detail = image.convert("RGB").crop(crop_box)
                detail_path = previews / f"{profile}_detail.png"
                detail.save(detail_path)
                thumbnail = ImageOps.contain(image.convert("RGB"), (600, 600))
                thumbnail_path = previews / f"{profile}_page.jpg"
                thumbnail.save(thumbnail_path, quality=90)
            paired_gt = json.loads(gt_path.read_text(encoding="utf-8"))
            geometry_same = all(paired_gt[key] == clean_gt[key] for key in ("elements", "pages", "reading_order"))
            if profile != "heavy_scan" and not geometry_same:
                raise ValueError(f"Photometric effect unexpectedly changed GT: {profile}")
            if pixel_sha256(replayed.image) != trace["processed_pixels_sha256"]:
                raise ValueError("Pixel replay differs")
            if trace["encoding"] == "PNG" and not np.array_equal(decoded, replayed.image):
                raise ValueError("PNG export differs from replay")
            overlay = previews / f"{profile}_gt.jpg"
            draw_gt_overlay(image_path, gt_path, overlay, mode="polygon", polygon_color="red", line_width=2)
            replay_file = io.BytesIO()
            Image.fromarray(replayed.image).save(replay_file, "PNG" if trace["encoding"] == "PNG" else "JPEG",
                                                **({} if trace["encoding"] == "PNG" else {"quality": 95}))
            exact = hashlib.sha256(replay_file.getvalue()).hexdigest() == file_sha256(image_path)
            if not exact:
                raise ValueError("Encoded-file replay differs")
            reports.append({"case": case_id, "profile": profile, "exact_replay": exact,
                            "identity_gt_geometry": geometry_same,
                            "mean_absolute_pixel_change": float(np.abs(decoded.astype(float) - base).mean()),
                            "image": image_path.relative_to(output).as_posix(),
                            "gt": gt_path.relative_to(output).as_posix()})
            tile = ImageOps.contain(detail, (460, 170))
            x, y = (index % 3) * 480, (index // 3) * 220
            sheet.paste(tile, (x + 10, y + 35))
            draw.text((x + 10, y + 8), profile, fill="#173b40", font=font)
            relative = lambda path: html.escape(path.relative_to(output).as_posix(), quote=True)
            parameters = html.escape(json.dumps(trace["operations"], indent=2))
            figures.append(f'<figure><h3>{profile}</h3><a href="{relative(image_path)}">'
                           f'<img class="page" src="{relative(thumbnail_path)}" alt="{profile} page" loading="lazy"></a>'
                           f'<a href="{relative(detail_path)}"><img class="detail" src="{relative(detail_path)}" '
                           f'alt="{profile} text detail" loading="lazy"></a><figcaption>'
                           f'<a href="{relative(overlay)}">GT overlay</a><a href="{relative(gt_path)}">GT JSON</a>'
                           f'</figcaption><details><summary>Parameters</summary><pre>{parameters}</pre></details></figure>')
        sheet.save(case / "contact_sheet.png")
        sections.append(f'<section id="{case_id}"><h2>{case_id}</h2><div class="meta">{template} &middot; page 1 &middot; {dpi} DPI</div>'
                        f'<div class="grid">{"".join(figures)}</div></section>')
        print(f"{case_id}: {len(result['artifacts'])} pairs, exact replay OK", flush=True)
    nav = " ".join(f'<a href="#{case[0]}">{case[0]}</a>' for case in CASES)
    page = f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    page += f'<title>PolyDocBench Noise Gallery</title><style>{STYLE}</style><header><h1>PolyDocBench Noise Gallery</h1>'
    page += f'<nav>{nav}</nav></header><main>{"".join(sections)}</main></html>'
    (output / "index.html").write_text(page, encoding="utf-8")
    report = {"preview_only": True, "seed": seed, "dpi": dpi, "cases": len(CASES),
              "pairs": len(reports), "exact_replay_passed": sum(item["exact_replay"] for item in reports), "artifacts": reports}
    (output / "validation_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/noise_gallery_v03"))
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.dpi < 36 or args.seed < 0:
        parser.error("dpi must be at least 36; seed must be non-negative")
    report = build_gallery(args.output_dir, args.dpi, args.seed)
    print(f"Gallery: {args.output_dir / 'index.html'}; replay={report['exact_replay_passed']}/{report['pairs']}")


if __name__ == "__main__":
    main()
