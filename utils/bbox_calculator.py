# utils/bbox_calculator.py

from typing import Dict, List, Tuple, Optional
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from dataclasses import dataclass


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


class BBoxCalculator:
    """
    Точный калькулятор размеров текста с построчной обработкой.
    """

    def __init__(self, font_path: str = None, font_name: str = "DejaVuSans"):
        self.font_name = font_name

        if font_path:
            if font_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(font_name, font_path))

    # -----------------------------
    # FONT METRICS
    # -----------------------------

    def get_font_metrics(self, font_size: float) -> Dict[str, float]:
        """Возвращает вертикальные метрики шрифта"""
        try:
            font = pdfmetrics.getFont(self.font_name)
            face = font.face
            
            ascent = (face.ascent / face.unitsPerEm) * font_size
            descent = abs(face.descent / face.unitsPerEm) * font_size
            line_height = font_size * 1.2  # стандартный интерлиньяж
            
            return {
                "ascent": ascent,
                "descent": descent,
                "line_height": line_height
            }
        except:
            # Fallback значения
            return {
                "ascent": font_size * 0.8,
                "descent": font_size * 0.2,
                "line_height": font_size * 1.2
            }

    # -----------------------------
    # LINE SPLITTING
    # -----------------------------

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
        add_hyphen_on_force_split: bool = True
    ) -> List["TextLineInfo"]:

        words = text.split()
        lines: List["TextLineInfo"] = []

        if not words:
            return lines

        font_metrics = self.get_font_metrics(font_size)
        line_height = font_size * line_height_ratio
        space_width = stringWidth(" ", self.font_name, font_size)

        # ---------------------------------------------------------
        # helpers
        # ---------------------------------------------------------

        def effective_width(is_first_line: bool) -> float:
            if is_first_line:
                return max_width - first_line_indent
            if indent_all_lines > 0:
                return max_width - indent_all_lines
            return max_width

        def finalize_line(words_list, width, is_first) -> "TextLineInfo":
            indent = first_line_indent if is_first else indent_all_lines
            return TextLineInfo(
                text=" ".join(words_list),
                width=width,
                height=line_height,
                ascent=font_metrics["ascent"],
                descent=font_metrics["descent"],
                line_height=line_height,
                font_size=font_size,
                font_family=self.font_name,
                is_first_line=is_first,
                indent=indent
            )

        def try_hyphenate(word, available_width, current_width):
            """
            Безопасный перенос: ОБЕ части обязаны помещаться.
            """
            if len(word) < min_word_fragment * 2:
                return None

            for split_pos in range(len(word) - min_word_fragment, min_word_fragment - 1, -1):
                first = word[:split_pos] + hyphen_char
                second = word[split_pos:]

                first_width = self.measure_text_width(first, font_size)
                second_width = self.measure_text_width(second, font_size)

                needed = current_width
                if current_words:
                    needed += space_width
                needed += first_width

                if needed <= available_width and second_width <= available_width:
                    return first, second, first_width

            return None

        def force_split_word(word, available_width, font_size):
            """
            Гарантированное посимвольное разбиение.
            """
            parts = []
            remaining = word

            while remaining:
                best_part = ""
                best_len = 0

                for i in range(1, len(remaining) + 1):
                    part = remaining[:i]
                    test = (
                        part + hyphen_char
                        if add_hyphen_on_force_split and i < len(remaining)
                        else part
                    )

                    if self.measure_text_width(test, font_size) <= available_width:
                        best_part = test
                        best_len = i
                    else:
                        break

                if best_len == 0:
                    # аварийный случай — хотя бы 1 символ
                    best_part = remaining[0]
                    best_len = 1

                parts.append(best_part)
                remaining = remaining[best_len:]

            return parts

        # ---------------------------------------------------------
        # main loop
        # ---------------------------------------------------------

        current_words = []
        current_width = 0.0

        for word in words:
            is_first_line = len(lines) == 0
            max_line_width = effective_width(is_first_line)

            word_width = self.measure_text_width(word, font_size)
            add_space = space_width if current_words else 0.0

            # 1️⃣ слово помещается целиком
            if current_width + add_space + word_width <= max_line_width:
                current_words.append(word)
                current_width += add_space + word_width
                continue

            # 2️⃣ безопасный перенос с дефисом
            if hyphenate:
                result = try_hyphenate(word, max_line_width, current_width)
                if result:
                    first_part, second_part, first_width = result

                    if current_words:
                        current_words.append(first_part)
                        current_width += space_width + first_width
                    else:
                        current_words = [first_part]
                        current_width = first_width

                    lines.append(
                        finalize_line(current_words, current_width, is_first_line)
                    )

                    second_width = self.measure_text_width(second_part, font_size)

                    if second_width <= max_line_width:
                        current_words = [second_part]
                        current_width = second_width
                    else:
                        parts = force_split_word(second_part, max_line_width, font_size)
                        for part in parts:
                            part_width = self.measure_text_width(part, font_size)
                            lines.append(
                                finalize_line([part], part_width, False)
                            )
                        current_words = []
                        current_width = 0.0

                    continue

            # 3️⃣ принудительное разбиение длинных слов
            if force_split_long_words and (
                word_width > max_line_width or len(word) > max_word_length_before_split
            ):
                if current_words:
                    lines.append(
                        finalize_line(current_words, current_width, is_first_line)
                    )
                    current_words = []
                    current_width = 0.0

                parts = force_split_word(word, max_line_width, font_size)
                for i, part in enumerate(parts):
                    part_width = self.measure_text_width(part, font_size)
                    lines.append(
                        finalize_line([part], part_width, i == 0 and is_first_line)
                    )

                continue

            # 4️⃣ обычный перенос
            if current_words:
                lines.append(
                    finalize_line(current_words, current_width, is_first_line)
                )

            if word_width <= max_line_width:
                current_words = [word]
                current_width = word_width
            else:
                parts = force_split_word(word, max_line_width, font_size)
                for i, part in enumerate(parts):
                    part_width = self.measure_text_width(part, font_size)
                    lines.append(
                        finalize_line([part], part_width, i == 0 and is_first_line)
                    )
                current_words = []
                current_width = 0.0

        # ---------------------------------------------------------
        # finalize last line
        # ---------------------------------------------------------

        if current_words:
            lines.append(
                finalize_line(current_words, current_width, len(lines) == 0)
            )

        # ---------------------------------------------------------
        # y offsets
        # ---------------------------------------------------------

        y_offset = 0.0
        for line in lines:
            line.y_offset = y_offset
            y_offset += line.height

        return lines

    # -----------------------------
    # УТИЛИТНЫЕ МЕТОДЫ
    # -----------------------------

    def measure_text_width(self, text: str, font_size: float) -> float:
        """Измеряет ширину текста"""
        return stringWidth(text, self.font_name, font_size)
    
    def can_fit_in_width(self, text: str, max_width: float, font_size: float) -> bool:
        """Проверяет, помещается ли текст в заданную ширину"""
        return self.measure_text_width(text, font_size) <= max_width