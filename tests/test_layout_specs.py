from polydocbench.layout.specs import ElementLayoutSpec


def test_element_layout_spec_reads_positive_dimensions():
    spec = ElementLayoutSpec.from_element({"type": "image", "width": "240", "height": 120})

    assert spec.element_type == "image"
    assert spec.width == 240
    assert spec.height == 120
    assert spec.width_for_container(200) == 200


def test_element_layout_spec_uses_defaults_for_invalid_dimensions():
    spec = ElementLayoutSpec.from_element({"type": "formula", "width": -1, "height": None})

    assert spec.width == 100
    assert spec.height == 100
