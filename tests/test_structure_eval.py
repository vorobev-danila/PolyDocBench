from polydocbench.eval import evaluate_structure, extract_gt_structure_elements, normalize_structure_type


def test_extract_gt_structure_elements_groups_text_and_keeps_non_text_blocks():
    gt = {
        "elements": [
            {"id": "p1", "type": "paragraph", "metadata": {"role": "block", "reading_order": 2}},
            {"id": "img1", "type": "image", "bbox": {"x": 50, "y": 50, "width": 20, "height": 10, "page": 1}, "metadata": {"role": "block", "reading_order": 1}},
        ],
        "pages": [
            {
                "page_number": 1,
                "containers": [
                    {
                        "elements": [
                            {
                                "id": "img1_line_001",
                                "type": "image",
                                "bbox": {"x": 50, "y": 50, "width": 20, "height": 10},
                                "metadata": {"parent_id": "img1"},
                            },
                            {
                                "id": "p1_line_002",
                                "type": "text_line",
                                "content": "world",
                                "bbox": {"x": 0, "y": 10, "width": 30, "height": 5},
                                "metadata": {"parent_id": "p1", "line_index": 2},
                            },
                            {
                                "id": "p1_line_001",
                                "type": "text_line",
                                "content": "Hello",
                                "bbox": {"x": 0, "y": 0, "width": 20, "height": 5},
                                "metadata": {"parent_id": "p1", "line_index": 1},
                            },
                        ]
                    }
                ],
            }
        ],
    }

    elements = extract_gt_structure_elements(gt)

    assert [element["id"] for element in elements] == ["img1", "p1"]
    assert elements[0]["type"] == "image"
    assert elements[1]["text"] == "Hello world"
    assert elements[1]["bbox"] == {"x": 0.0, "y": 0.0, "width": 30.0, "height": 15.0}


def test_structure_metrics_separate_detection_and_type_accuracy():
    gt = [
        {"id": "g1", "type": "paragraph", "bbox": {"x": 0, "y": 0, "width": 10, "height": 10}},
        {"id": "g2", "type": "image", "bbox": {"x": 20, "y": 0, "width": 10, "height": 10}},
    ]
    predicted = [
        {"id": "p1", "type": "paragraph", "bbox": {"x": 0, "y": 0, "width": 10, "height": 10}},
        {"id": "p2", "type": "paragraph", "bbox": {"x": 20, "y": 0, "width": 10, "height": 10}},
        {"id": "fp", "type": "table", "bbox": {"x": 100, "y": 0, "width": 10, "height": 10}},
    ]

    metrics, matches = evaluate_structure(gt, predicted)

    assert metrics["detection_recall"] == 1.0
    assert round(metrics["detection_precision"], 4) == 0.6667
    assert metrics["type_accuracy"] == 0.5
    assert metrics["false_positive_count"] == 1
    assert [match.type_correct for match in matches] == [True, False]


def test_structure_type_aliases():
    assert normalize_structure_type("Section-header") == "heading"
    assert normalize_structure_type("Picture") == "image"
    assert normalize_structure_type("Text") == "paragraph"
