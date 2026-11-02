"""Facade for text metrics and line breaking."""

from __future__ import annotations

from pathlib import Path

from polydocbench.layout.line_breaking import LineBreaker, TextLineInfo
from polydocbench.layout.text_metrics import TextMetrics
from polydocbench.document.fonts import fallback_line_metrics


class BBoxCalculator:
    """Backward-compatible facade used by the placement engine."""

    def __init__(self, font_path: str | Path | None = None, font_name: str = "DejaVuSans") -> None:
        self.metrics = TextMetrics(font_path=font_path, font_name=font_name)
        self.line_breaker = LineBreaker(self.metrics)

    @property
    def font_name(self) -> str:
        return self.metrics.font_name

    def get_font_metrics(self, font_size: float) -> dict[str, float]:
        return self.metrics.get_font_metrics(font_size)

    def split_into_lines(
        self,
        text: str,
        max_width: float,
        font_size: float,
        line_height_ratio: float = 1.2,
        first_line_indent: float = 20,
        indent_all_lines: float = 0.0,
        hyphenate: bool = True,
        hyphen_char: str = "-",
        min_word_fragment: int = 3,
        force_split_long_words: bool = True,
        max_word_length_before_split: int = 20,
        add_hyphen_on_force_split: bool = True,
    ) -> list[TextLineInfo]:
        lines = self.line_breaker.split_into_lines(
            text=text,
            max_width=max_width,
            font_size=font_size,
            line_height_ratio=line_height_ratio,
            first_line_indent=first_line_indent,
            indent_all_lines=indent_all_lines,
            hyphenate=hyphenate,
            hyphen_char=hyphen_char,
            min_word_fragment=min_word_fragment,
            force_split_long_words=force_split_long_words,
            max_word_length_before_split=max_word_length_before_split,
            add_hyphen_on_force_split=add_hyphen_on_force_split,
        )
        return self._apply_fallback_metrics(lines)

    def split_heading_into_lines(
        self,
        text: str,
        max_width: float,
        font_size: float,
        line_height_ratio: float = 1.2,
    ) -> list[TextLineInfo]:
        lines = self.line_breaker.split_heading_into_lines(
            text=text,
            max_width=max_width,
            font_size=font_size,
            line_height_ratio=line_height_ratio,
        )
        return self._apply_fallback_metrics(lines)

    def _apply_fallback_metrics(self, lines: list[TextLineInfo]) -> list[TextLineInfo]:
        for line in lines:
            metrics = fallback_line_metrics(line.text, line.font_family, line.font_size, line.height)
            if metrics is not None:
                line.height, line.ascent, line.descent = metrics
                line.line_height = line.height
        self.line_breaker._assign_y_offsets(lines)
        return lines

    def measure_text_width(self, text: str, font_size: float) -> float:
        return self.metrics.measure_text_width(text, font_size)

    def can_fit_in_width(self, text: str, max_width: float, font_size: float) -> bool:
        return self.metrics.can_fit_in_width(text, max_width, font_size)


__all__ = ["BBoxCalculator", "LineBreaker", "TextLineInfo", "TextMetrics"]
