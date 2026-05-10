from polydocbench.layout.bbox import BBoxCalculator, TextLineInfo
from polydocbench.layout.line_breaking import LineBreaker
from polydocbench.layout.text_metrics import TextMetrics


def test_text_metrics_measures_width_and_fallback_metrics():
    metrics = TextMetrics(font_name="Helvetica")

    assert metrics.measure_text_width("Hello", 10) > 0
    assert metrics.can_fit_in_width("Hello", 100, 10)
    assert metrics.get_font_metrics(10)["line_height"] == 12


def test_line_breaker_splits_paragraph_with_indent_offsets():
    breaker = LineBreaker(TextMetrics(font_name="Helvetica"))
    lines = breaker.split_into_lines(
        "This is a short paragraph that should wrap into several lines.",
        max_width=80,
        font_size=10,
        first_line_indent=12,
    )

    assert len(lines) > 1
    assert isinstance(lines[0], TextLineInfo)
    assert lines[0].indent == 12
    assert lines[1].y_offset == lines[0].height


def test_line_breaker_marks_wrapped_lines_for_justification():
    breaker = LineBreaker(TextMetrics(font_name="Helvetica"))
    lines = breaker.split_into_lines(
        "This paragraph has enough words to wrap into several justified text lines.",
        max_width=100,
        font_size=10,
        first_line_indent=0,
    )

    assert len(lines) > 1
    assert any(line.justify for line in lines[:-1])
    assert not lines[-1].justify
    for line in lines[:-1]:
        if len(line.text.split()) > 1:
            assert line.target_width == 100
            assert line.target_width > line.width


def test_bbox_calculator_remains_compatible_facade():
    calculator = BBoxCalculator(font_name="Helvetica")
    lines = calculator.split_heading_into_lines("A Very Long Heading", max_width=60, font_size=12)

    assert lines
    assert calculator.measure_text_width(lines[0].text, 12) == lines[0].width
