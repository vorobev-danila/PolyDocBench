"""Shared glyph fallback for identical layout measurement and PDF drawing."""

from __future__ import annotations

from pathlib import Path
from threading import RLock

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


FALLBACK_FONT = "PolyDocBenchSymbols"
_FONT_LOCK = RLock()


def _register_fallback():
    with _FONT_LOCK:
        if FALLBACK_FONT not in pdfmetrics.getRegisteredFontNames():
            relative = Path("fonts/NotoSansSymbols2/NotoSansSymbols2-Regular.ttf")
            path = relative if relative.is_file() else Path(__file__).resolve().parents[2] / relative
            if not path.is_file():
                raise ValueError(f"Bundled symbol fallback font is missing: {relative}")
            pdfmetrics.registerFont(TTFont(FALLBACK_FONT, str(path)))
    return pdfmetrics.getFont(FALLBACK_FONT)


def font_runs(text: str, font_name: str) -> list[tuple[str, str]]:
    primary = pdfmetrics.getFont(font_name)
    mapping = getattr(primary.face, "charToGlyph", None)
    if mapping is None or all(mapping.get(ord(character)) for character in text):
        return [(font_name, text)]
    fallback = _register_fallback()
    runs: list[tuple[str, str]] = []
    current_font, characters = font_name, []
    for character in text:
        chosen = font_name
        if not mapping.get(ord(character)):
            if not fallback.face.charToGlyph.get(ord(character)):
                raise ValueError(f"No bundled font supports U+{ord(character):04X}; refusing to draw an unlabelled missing glyph")
            chosen = FALLBACK_FONT
        if chosen != current_font and characters:
            runs.append((current_font, "".join(characters)))
            characters = []
        current_font = chosen
        characters.append(character)
    if characters:
        runs.append((current_font, "".join(characters)))
    return runs


def measure_text(text: str, font_name: str, font_size: float) -> float:
    return sum(pdfmetrics.stringWidth(run, name, font_size) for name, run in font_runs(text, font_name))


def fallback_line_metrics(text: str, font_name: str, font_size: float, minimum_height: float):
    names = {name for name, _ in font_runs(text, font_name)}
    if names <= {font_name}:
        return None
    metrics = [pdfmetrics.getAscentDescent(name, font_size) for name in names]
    ascent = max(item[0] for item in metrics)
    descent = max(abs(item[1]) for item in metrics)
    height = max(minimum_height, ascent + descent)
    baseline = descent + (height - ascent - descent) / 2
    return height, baseline, descent


def draw_text(canvas, text: str, x: float, y: float, font_name: str, font_size: float) -> None:
    for name, run in font_runs(text, font_name):
        canvas.setFont(name, font_size)
        canvas.drawString(x, y, run)
        x += pdfmetrics.stringWidth(run, name, font_size)
    canvas.setFont(font_name, font_size)
