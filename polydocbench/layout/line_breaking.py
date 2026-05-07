"""Line breaking for paragraphs and headings."""

from __future__ import annotations

from dataclasses import dataclass

from polydocbench.layout.text_metrics import TextMetrics


@dataclass
class TextLineInfo:
    text: str
    width: float
    height: float
    ascent: float
    descent: float
    line_height: float
    font_size: float
    font_family: str
    is_first_line: bool = False
    indent: float = 0.0
    y_offset: float = 0.0


class LineBreaker:
    def __init__(self, metrics: TextMetrics) -> None:
        self.metrics = metrics

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
        words = text.split()
        lines: list[TextLineInfo] = []
        if not words:
            return lines

        font_metrics = self.metrics.get_font_metrics(font_size)
        line_height = font_size * line_height_ratio
        space_width = self.metrics.measure_text_width(" ", font_size)

        def effective_width(is_first_line: bool) -> float:
            if is_first_line:
                return max_width - first_line_indent
            if indent_all_lines > 0:
                return max_width - indent_all_lines
            return max_width

        def finalize_line(words_list: list[str], is_first: bool) -> TextLineInfo:
            indent = first_line_indent if is_first else indent_all_lines
            actual_text = " ".join(words_list)
            actual_width = self.metrics.measure_text_width(actual_text, font_size)
            return TextLineInfo(
                text=actual_text,
                width=actual_width,
                height=line_height,
                ascent=font_metrics["ascent"],
                descent=font_metrics["descent"],
                line_height=line_height,
                font_size=font_size,
                font_family=self.metrics.font_name,
                is_first_line=is_first,
                indent=indent,
            )

        def try_hyphenate(word: str, available_width: float, current_width: float, current_words: list[str]):
            if len(word) < min_word_fragment * 2:
                return None

            for split_pos in range(len(word) - min_word_fragment, min_word_fragment - 1, -1):
                first = word[:split_pos] + hyphen_char
                second = word[split_pos:]
                first_width = self.metrics.measure_text_width(first, font_size)
                second_width = self.metrics.measure_text_width(second, font_size)

                needed = current_width
                if current_words:
                    needed += space_width
                needed += first_width

                if needed <= available_width and second_width <= available_width:
                    return first, second, first_width

            return None

        def force_split_word(word: str, available_width: float) -> list[str]:
            parts: list[str] = []
            remaining = word

            while remaining:
                best_part = ""
                best_len = 0

                for index in range(1, len(remaining) + 1):
                    part = remaining[:index]
                    test = part + hyphen_char if add_hyphen_on_force_split and index < len(remaining) else part
                    if self.metrics.measure_text_width(test, font_size) <= available_width:
                        best_part = test
                        best_len = index
                    else:
                        break

                if best_len == 0:
                    best_part = remaining[0]
                    best_len = 1

                parts.append(best_part)
                remaining = remaining[best_len:]

            return parts

        current_words: list[str] = []
        current_width = 0.0

        for word in words:
            is_first_line = len(lines) == 0
            max_line_width = effective_width(is_first_line)
            word_width = self.metrics.measure_text_width(word, font_size)
            add_space = space_width if current_words else 0.0

            if current_width + add_space + word_width <= max_line_width:
                current_words.append(word)
                current_width += add_space + word_width
                continue

            if hyphenate:
                hyphenated = try_hyphenate(word, max_line_width, current_width, current_words)
                if hyphenated:
                    first_part, second_part, first_width = hyphenated
                    if current_words:
                        current_words.append(first_part)
                        current_width += space_width + first_width
                    else:
                        current_words = [first_part]
                        current_width = first_width

                    lines.append(finalize_line(current_words, is_first_line))

                    second_width = self.metrics.measure_text_width(second_part, font_size)
                    if second_width <= max_line_width:
                        current_words = [second_part]
                        current_width = second_width
                    else:
                        for part in force_split_word(second_part, max_line_width):
                            lines.append(finalize_line([part], False))
                        current_words = []
                        current_width = 0.0
                    continue

            if force_split_long_words and (word_width > max_line_width or len(word) > max_word_length_before_split):
                if current_words:
                    lines.append(finalize_line(current_words, is_first_line))
                    current_words = []
                    current_width = 0.0

                for index, part in enumerate(force_split_word(word, max_line_width)):
                    lines.append(finalize_line([part], index == 0 and is_first_line))
                continue

            if current_words:
                lines.append(finalize_line(current_words, is_first_line))

            if word_width <= max_line_width:
                current_words = [word]
                current_width = word_width
            else:
                for index, part in enumerate(force_split_word(word, max_line_width)):
                    lines.append(finalize_line([part], index == 0 and is_first_line))
                current_words = []
                current_width = 0.0

        if current_words:
            lines.append(finalize_line(current_words, len(lines) == 0))

        self._assign_y_offsets(lines)
        return lines

    def split_heading_into_lines(
        self,
        text: str,
        max_width: float,
        font_size: float,
        line_height_ratio: float = 1.2,
    ) -> list[TextLineInfo]:
        words = text.split()
        if not words:
            return []

        font_metrics = self.metrics.get_font_metrics(font_size)
        line_height = font_size * line_height_ratio
        space_width = self.metrics.measure_text_width(" ", font_size)

        lines: list[TextLineInfo] = []
        current_words: list[str] = []
        current_width = 0.0

        def finalize_line(words_list: list[str]) -> TextLineInfo:
            actual_text = " ".join(words_list)
            actual_width = self.metrics.measure_text_width(actual_text, font_size)
            return TextLineInfo(
                text=actual_text,
                width=actual_width,
                height=line_height,
                ascent=font_metrics["ascent"],
                descent=font_metrics["descent"],
                line_height=line_height,
                font_size=font_size,
                font_family=self.metrics.font_name,
                is_first_line=False,
                indent=0.0,
            )

        for word in words:
            word_width = self.metrics.measure_text_width(word, font_size)
            add_space = space_width if current_words else 0.0

            if current_width + add_space + word_width <= max_width:
                current_words.append(word)
                current_width += add_space + word_width
                continue

            if current_words:
                lines.append(finalize_line(current_words))
                current_words = [word]
                current_width = word_width
                continue

            remaining = word
            while remaining:
                part = ""
                for index in range(1, len(remaining) + 1):
                    test = remaining[:index]
                    if self.metrics.measure_text_width(test, font_size) <= max_width:
                        part = test
                    else:
                        break

                if not part:
                    part = remaining[0]

                part_width = self.metrics.measure_text_width(part, font_size)
                lines.append(
                    TextLineInfo(
                        text=part,
                        width=part_width,
                        height=line_height,
                        ascent=font_metrics["ascent"],
                        descent=font_metrics["descent"],
                        line_height=line_height,
                        font_size=font_size,
                        font_family=self.metrics.font_name,
                    )
                )
                remaining = remaining[len(part):]

            current_words = []
            current_width = 0.0

        if current_words:
            lines.append(finalize_line(current_words))

        self._assign_y_offsets(lines)
        return lines

    @staticmethod
    def _assign_y_offsets(lines: list[TextLineInfo]) -> None:
        y_offset = 0.0
        for line in lines:
            line.y_offset = y_offset
            y_offset += line.height
