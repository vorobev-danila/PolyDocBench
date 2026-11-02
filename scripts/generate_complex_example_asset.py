"""Regenerate the bundled figure without network access or plotting extras."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "examples" / "assets" / "benchmark_chart.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1200, 480), "white")
    draw = ImageDraw.Draw(image)
    font_path = root / "DejaVu Sans" / "DejaVuSans.ttf"
    font = ImageFont.truetype(str(font_path), 24)
    title = ImageFont.truetype(str(font_path), 32)
    draw.text((70, 20), "Illustrative OCR error rates", fill="#172b39", font=title)
    left, top, bottom = 90, 90, 370
    for value in range(0, 41, 10):
        y = bottom - value / 40 * (bottom - top)
        draw.line((left, y, 1130, y), fill="#dae2e8", width=2)
        draw.text((30, y - 13), str(value), fill="#52616c", font=font)
    for index, (label, value, color) in enumerate([
        ("Clean", 3, "#287e8f"), ("Light", 8, "#3b9c82"),
        ("Medium", 17, "#bc8a32"), ("Heavy", 31, "#c36063"),
    ]):
        x = left + 70 + index * 250
        y = bottom - value / 40 * (bottom - top)
        draw.rectangle((x, y, x + 130, bottom), fill=color)
        draw.text((x + 40, y - 32), str(value), fill="#172b39", font=font)
        draw.text((x + 5, bottom + 16), label, fill="#172b39", font=font)
    draw.text((70, 438), "Synthetic illustration only; values are not experimental results.", fill="#52616c", font=font)
    image.save(path)
    print(path)


if __name__ == "__main__":
    main()
