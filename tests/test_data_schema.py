import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from polydocbench.document.schema import FORMAT_SCHEMA_VERSION, SourceDocument, validate_source_document
from polydocbench.gt.schema import GTDocument, validate_gt_document
from polydocbench.layout.content_loader import ContentLoader


def test_source_document_accepts_legacy_json_and_adds_schema_version():
    document = validate_source_document(
        {
            "title": "Example",
            "url": "https://example.test",
            "content": [
                {"type": "paragraph", "text": "Hello"},
                {"type": "heading", "level": 2, "text": "Section", "content": []},
            ],
        }
    )

    assert isinstance(document, SourceDocument)
    assert document.schema_version == FORMAT_SCHEMA_VERSION
    assert document.source_items()[0]["text"] == "Hello"


def test_source_document_rejects_missing_content_and_elements():
    with pytest.raises(ValidationError, match="non-empty 'content' or 'elements'"):
        validate_source_document({"title": "Broken"})


def test_content_loader_validates_input_before_layout():
    input_path = Path("outputs/test_runs/invalid_source_schema.json")
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(
        json.dumps({"schema_version": FORMAT_SCHEMA_VERSION, "title": "Broken", "content": []}),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        ContentLoader.load_json(input_path)


def test_gt_document_schema_validates_export_shape():
    gt = validate_gt_document(
        {
            "schema_version": FORMAT_SCHEMA_VERSION,
            "metadata": {"generator": "PolyDocBench"},
            "reading_order": {"blocks": ["paragraph_0001"], "lines": ["paragraph_0001_line_0001"]},
            "pages": [
                {
                    "page_number": 1,
                    "width": 100,
                    "height": 100,
                    "containers": [
                        {
                            "id": "main",
                            "type": "single_column",
                            "bbox": {"x": 0, "y": 0, "width": 100, "height": 100, "page": 1},
                            "elements": [
                                {
                                    "id": "paragraph_0001_line_0001",
                                    "type": "text_line",
                                    "content": "Hello",
                                    "bbox": {"x": 0, "y": 80, "width": 40, "height": 10, "page": 1},
                                }
                            ],
                        }
                    ],
                }
            ],
            "elements": [
                {
                    "id": "paragraph_0001",
                    "type": "paragraph",
                    "content": "Hello",
                    "bbox": {"x": 0, "y": 80, "width": 40, "height": 10, "page": 1},
                }
            ],
        }
    )

    assert isinstance(gt, GTDocument)
    assert gt.schema_version == FORMAT_SCHEMA_VERSION
    assert gt.pages[0].containers[0].elements[0].content == "Hello"
