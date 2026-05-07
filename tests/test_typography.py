from polydocbench.layout.typography import TypographyStyle


def test_typography_style_normalizes_template_config():
    style = TypographyStyle.from_config(
        {
            "font_family": "ExampleFont",
            "body_size": 9,
            "line_height": 1.3,
            "first_line_indent": 18,
            "paragraph_spacing": 7,
            "heading_sizes": {"h1": 18, "h2": 14},
        }
    )

    assert style.font_family == "ExampleFont"
    assert style.body_size == 9
    assert style.line_height == 1.3
    assert style.first_line_indent == 18
    assert style.paragraph_spacing == 7
    assert style.heading_size("heading2") == 14
    assert style.heading_size("heading5") == 14


def test_typography_style_uses_defaults_for_missing_config():
    style = TypographyStyle.from_config(None)

    assert style.font_family == "DejaVuSans"
    assert style.body_size == 10
    assert style.line_height == 1.2
    assert style.first_line_indent == 20
    assert style.paragraph_spacing == 10
