import json
import hashlib
from pathlib import Path

import pytest
from reportlab.pdfbase import pdfmetrics

from polydocbench.document.fonts import FALLBACK_FONT, font_runs, measure_text
from polydocbench.document.tables import validate_table
from polydocbench.layout import LayoutEngine
from polydocbench.layout.bbox import BBoxCalculator
from polydocbench.layout.tables import TablePlan
from polydocbench.render import PDFRenderer
from polydocbench.sources.wikipedia import WikipediaParser
from scripts.check_wikipedia_tables import audit_tables, main, render_probe, validate_layout


ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "DejaVu Sans/DejaVuSans.ttf"


def test_empty_corner_does_not_disable_repeated_headers():
    table = validate_table({"rows": [[{"text": ""}, {"text": "Value", "is_header": True, "scope": "col"}],
                                    [{"text": "Row", "is_header": True, "scope": "row"}, {"text": "123"}]]})
    assert table.repeated_header_count() == 1


def test_row_scoped_headers_are_not_repeated_as_column_headers():
    table = validate_table({"rows": [[{"text": "A", "is_header": True, "scope": "row"}],
                                    [{"text": "B", "is_header": True, "scope": "row"}]]})
    assert table.repeated_header_count() == 0


def test_parser_preserves_thead_scope_alignment_and_infobox_kind():
    source = WikipediaParser().parse_html('''<div class="mw-parser-output"><table class="infobox">
        <thead><tr><td>Explicit header</td></tr></thead>
        <tbody><tr><th scope="row" align="right">Data</th></tr></tbody></table></div>''')
    item = source["content"][0]
    assert item["header_rows"] == 1
    assert item["rows"][0][0]["is_header"]
    assert item["rows"][1][0]["scope"] == "row"
    assert item["rows"][1][0]["align"] == "right"
    assert item["table_kind"] == "infobox"


def test_table_superscripts_and_subscripts_preserve_scientific_meaning():
    source = WikipediaParser().parse_html('''<div class="mw-parser-output"><table><tr>
        <td>10<sup>30</sup> = 1000<sup>10</sup></td><td>10<sup>\u22123</sup></td>
        <td>H<sub>2</sub>O</td><td>x<sup>ab</sup></td>
        <td>Value<sup class="reference"><a href="#cite_note-1">[1]</a></sup></td>
        <td>Quetta<sup>C)</sup></td><td>array[1]</td>
        </tr></table></div>''')
    cells = source["content"][0]["rows"][0]
    assert cells[0]["text"] == "10\u00b3\u2070 = 1000\u00b9\u2070"
    assert cells[1]["text"] == "10\u207b\u00b3"
    assert cells[2]["text"] == "H\u2082O"
    assert cells[3]["text"] == "x^(ab)"
    assert cells[4]["text"] == "Value"
    assert cells[5]["text"] == "Quetta[C]"
    assert cells[6]["text"] == "array[1]"


def test_automatic_widths_favor_descriptions_but_honor_manual_weights():
    data = validate_table({"rows": [[{"text": "Code", "is_header": True}, {"text": "Description", "is_header": True}],
        [{"text": "0x00"}, {"text": "This description contains multiple meaningful words and needs room."}]]})
    calculator = BBoxCalculator(font_path=FONT)
    automatic = TablePlan.measure(data, 300, calculator, {})
    assert automatic.widths[1] > automatic.widths[0]
    assert automatic.widths[0] >= calculator.measure_text_width("0x00", 8) + 8
    assert sum(automatic.widths) == pytest.approx(300)
    weighted = TablePlan.measure(data.model_copy(update={"column_weights": [4, 1]}), 300, calculator, {})
    assert weighted.widths == [240, 60]


def test_font_fallback_preserves_control_pictures_and_measured_width():
    BBoxCalculator(font_path=FONT)
    runs = font_runs("NUL \u2400 DEL \u2421", "DejaVuSans")
    assert FALLBACK_FONT in {name for name, _ in runs}
    expected = sum(pdfmetrics.stringWidth(text, name, 9) for name, text in runs)
    assert measure_text("NUL \u2400 DEL \u2421", "DejaVuSans", 9) == pytest.approx(expected)
    assert measure_text("ASCII", "DejaVuSans", 9) == pdfmetrics.stringWidth("ASCII", "DejaVuSans", 9)
    with pytest.raises(ValueError, match="No bundled font supports"):
        font_runs("\U0010ffff", "DejaVuSans")


def test_unicode_control_picture_pdf_and_gt_remain_consistent(tmp_path):
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "source.json"
    path.write_text(json.dumps({"elements": [{"type": "table", "rows": [
        [{"text": "\u2400"}, {"text": "NUL"}], [{"text": "\u2421"}, {"text": "DEL"}]]}]}), encoding="utf-8")
    result = LayoutEngine(font_path=FONT).layout_document(path, "technical_report")
    PDFRenderer(debug=False).render(result, tmp_path / "symbols.pdf")
    assert not validate_layout(result)
    with fitz.open(tmp_path / "symbols.pdf") as document:
        assert "\u2400" in document[0].get_text() and "\u2421" in document[0].get_text()
        assert any("NotoSansSymbols2" in str(font) for font in document[0].get_fonts())
        for symbol in ("\u2400", "\u2421"):
            line = next(element for element in result.elements if element.type == "text_line" and element.content == symbol)
            rect = document[0].search_for(symbol)[0]
            assert rect.y0 >= document[0].rect.height - line.bbox.y - line.bbox.height - 0.1
            assert rect.y1 <= document[0].rect.height - line.bbox.y + 0.1


def test_offline_real_url_probe_checks_source_cell_coverage(tmp_path):
    pytest.importorskip("fitz")
    source = {"elements": [{"type": "table", "rows": [[{"text": "A"}, {"text": "B"}],
                                                       [{"text": "1"}, {"text": "2"}]]}]}
    path = tmp_path / "source.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    report = render_probe(path, tmp_path / "probe.pdf", "technical_report", 1)
    assert report["status"] == "ok"
    assert report["source_cells"] == report["unique_gt_cells"] == 4
    assert report["missing_text_lines"] == 0


def test_audit_reports_unsupported_tables_separately():
    source = {"content": [{"type": "table", "rows": [[{"text": "Text"}]], "table_kind": "infobox",
                           "extraction_warnings": ["Images inside table cells are not rendered"]}]}
    _, audit = audit_tables(source)
    assert audit[0]["table_kind"] == "infobox"
    assert audit[0]["extraction_warnings"]


def test_cached_table_only_run_retains_explicit_exclusions(tmp_path, monkeypatch):
    pytest.importorskip("fitz")
    directory = tmp_path / "en_ascii"
    directory.mkdir()
    html = b'''<h1>Offline probe</h1><div class="mw-parser-output">
        <table class="infobox"><tr><td><img src="missing.png"></td></tr></table>
        <table><tr><th>Value</th></tr><tr><td>123</td></tr></table></div>'''
    (directory / "source.html").write_bytes(html)
    (directory / "fetch.json").write_text(json.dumps({"resolved_url": "https://en.wikipedia.org/wiki/ASCII",
        "html_sha256": hashlib.sha256(html).hexdigest()}), encoding="utf-8")

    def no_network(*args, **kwargs):
        raise AssertionError("Cached table probes must not request articles or excluded images")

    monkeypatch.setattr("requests.get", no_network)
    monkeypatch.setattr("sys.argv", ["check_wikipedia_tables.py", "--output-dir", str(tmp_path), "--cases", "en_ascii",
        "--reuse-html", "--max-tables", "0", "--tables-only", "--preview-pages", "0"])
    assert main() == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["scope"] == "tables_only"
    assert report["cases"][0]["excluded_table_indices"] == [1]
    assert report["cases"][0]["selected_table_indices"] == [2]
    assert len(report["cases"][0]["renders"]) == 2
    assert all(item["status"] == "ok" for item in report["cases"][0]["renders"])
