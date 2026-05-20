import sys
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from polydocbench.eval.ocr import extract_tesseract_lines


def test_tesseract_adapter_can_return_image_coordinates(monkeypatch):
    image_path = Path("outputs/test_runs/ocr_adapter_input.jpg")
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (100, 80), "white").save(image_path)

    fake_tsv = {
        "level": [5],
        "text": ["word"],
        "block_num": [1],
        "par_num": [1],
        "line_num": [1],
        "left": [10],
        "top": [20],
        "width": [30],
        "height": [8],
        "conf": [90],
    }
    fake_pytesseract = SimpleNamespace(
        Output=SimpleNamespace(DICT="dict"),
        image_to_data=lambda image, output_type, **kwargs: fake_tsv,
    )
    monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)

    lines = extract_tesseract_lines(image_path, lang="eng", coordinate_system="image")

    assert lines[0]["text"] == "word"
    assert lines[0]["bbox"] == {"x": 10.0, "y": 20.0, "width": 30.0, "height": 8.0}


def test_tesseract_adapter_keeps_pdf_coordinate_mode(monkeypatch):
    image_path = Path("outputs/test_runs/ocr_adapter_pdf_input.jpg")
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (100, 80), "white").save(image_path)

    fake_tsv = {
        "level": [5],
        "text": ["word"],
        "block_num": [1],
        "par_num": [1],
        "line_num": [1],
        "left": [10],
        "top": [20],
        "width": [30],
        "height": [8],
        "conf": [90],
    }
    fake_pytesseract = SimpleNamespace(
        Output=SimpleNamespace(DICT="dict"),
        image_to_data=lambda image, output_type, **kwargs: fake_tsv,
    )
    monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)

    lines = extract_tesseract_lines(image_path, zoom=2.0, coordinate_system="pdf")

    assert lines[0]["bbox"] == {"x": 5.0, "y": 26.0, "width": 15.0, "height": 4.0}
