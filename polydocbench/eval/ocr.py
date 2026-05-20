"""OCR adapters used by evaluation notebooks and scripts."""

from __future__ import annotations

from pathlib import Path

from .types import LineDict


def extract_tesseract_lines(
    image_path: str | Path,
    zoom: float = 1.0,
    page_number: int = 1,
    lang: str | None = None,
    coordinate_system: str = "pdf",
) -> list[LineDict]:
    """Extract line boxes from Tesseract TSV word output.

    Tesseract image coordinates use a top-left origin. With
    ``coordinate_system="pdf"``, returned bboxes use the PolyDocBench PDF
    bottom-left convention and are divided by ``zoom``. With
    ``coordinate_system="image"``, returned bboxes stay in top-left image
    pixels, matching degraded image GT.
    """

    import pytesseract
    from PIL import Image

    if coordinate_system not in {"pdf", "image"}:
        raise ValueError("coordinate_system must be one of: pdf, image")

    image = Image.open(image_path)
    _, image_height = image.size
    kwargs = {"lang": lang} if lang else {}
    tsv = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT, **kwargs)

    grouped: dict[tuple[int, int, int], dict[str, object]] = {}
    for index, raw_word in enumerate(tsv["text"]):
        if int(tsv["level"][index]) != 5:
            continue

        word = raw_word.strip()
        if not word:
            continue

        key = (
            int(tsv["block_num"][index]),
            int(tsv["par_num"][index]),
            int(tsv["line_num"][index]),
        )
        left = float(tsv["left"][index])
        top = float(tsv["top"][index])
        width = float(tsv["width"][index])
        height = float(tsv["height"][index])

        if coordinate_system == "image":
            x = left
            y = top
        else:
            x = left / zoom
            y = (image_height - (top + height)) / zoom
            width /= zoom
            height /= zoom

        if key not in grouped:
            grouped[key] = {
                "words": [],
                "conf_sum": 0.0,
                "conf_count": 0,
                "bbox": [x, y, width, height],
            }

        grouped[key]["words"].append(word)
        confidence = float(tsv["conf"][index])
        if confidence > 0:
            grouped[key]["conf_sum"] += confidence
            grouped[key]["conf_count"] += 1

        bx, by, bw, bh = grouped[key]["bbox"]
        x1 = max(float(bx) + float(bw), x + width)
        y1 = max(float(by) + float(bh), y + height)
        grouped[key]["bbox"] = [min(float(bx), x), min(float(by), y), x1 - min(float(bx), x), y1 - min(float(by), y)]

    lines: list[LineDict] = []
    for line_id, line in enumerate(grouped.values()):
        words = line["words"]
        text = " ".join(words)
        conf_count = int(line["conf_count"])
        confidence = float(line["conf_sum"]) / conf_count if conf_count else 0.0
        x, y, width, height = line["bbox"]
        lines.append(
            {
                "id": f"ocr_line_{line_id}",
                "type": "text_line",
                "text": text,
                "bbox": {
                    "x": round(float(x), 2),
                    "y": round(float(y), 2),
                    "width": round(float(width), 2),
                    "height": round(float(height), 2),
                },
                "confidence": round(confidence, 2),
                "page_number": page_number,
            }
        )

    return lines
