import json
from pathlib import Path

from polydocbench.document import DocumentElement, Page
from polydocbench.gt import GroundTruthExporter
from polydocbench.layout import LayoutResult


def test_ground_truth_exporter_writes_layout_result():
    page = Page(number=1, width=100, height=100)
    container = page.create_single_column({"top": 10, "bottom": 10, "left": 10, "right": 10})
    element = DocumentElement(
        id="line_1",
        type="text_line",
        content="Hello",
        bbox=container.place(12),
        dimensions={"font_size": 10},
    )
    container.add_element(element)

    result = LayoutResult(pages=[page], elements=[element])
    result.prepare_ground_truth()

    output_path = Path("outputs/test_runs/gt_exporter_test.json")
    export_result = GroundTruthExporter().export(result, output_path)
    exported = json.loads(output_path.read_text(encoding="utf-8"))

    assert export_result["success"] is True
    assert exported["schema_version"] == "0.1"
    assert exported["metadata"]["format_version"] == "0.1"
    assert exported["metadata"]["generator"] == "PolyDocBench"
    assert exported["pages"][0]["containers"][0]["elements"][0]["content"] == "Hello"
