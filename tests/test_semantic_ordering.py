from polydocbench.eval import evaluate_semantic_ordering, extract_visible_gt_blocks
from polydocbench.eval.dotsocr import parse_dotsocr_blocks_response


def test_extract_visible_gt_blocks_groups_visible_lines_in_exported_order():
    gt = {
        "elements": [
            {"id": "p1", "type": "paragraph", "metadata": {"role": "block"}},
            {"id": "p2", "type": "paragraph", "metadata": {"role": "block"}},
        ],
        "pages": [
            {
                "page_number": 1,
                "containers": [
                    {
                        "elements": [
                            {
                                "id": "p2_line_1",
                                "type": "text_line",
                                "content": "Second.",
                                "bbox": {"x": 1, "y": 30, "width": 20, "height": 5},
                                "metadata": {"parent_id": "p2", "line_index": 1, "reading_order": 3},
                            },
                            {
                                "id": "p1_line_2",
                                "type": "text_line",
                                "content": "world.",
                                "bbox": {"x": 1, "y": 20, "width": 20, "height": 5},
                                "metadata": {"parent_id": "p1", "line_index": 2, "reading_order": 2},
                            },
                            {
                                "id": "p1_line_1",
                                "type": "text_line",
                                "content": "Hello",
                                "bbox": {"x": 1, "y": 10, "width": 20, "height": 5},
                                "metadata": {"parent_id": "p1", "line_index": 1, "reading_order": 1},
                            },
                        ]
                    }
                ],
            }
        ],
    }

    blocks = extract_visible_gt_blocks(gt)

    assert [block["id"] for block in blocks] == ["p1", "p2"]
    assert blocks[0]["text"] == "Hello world."


def test_semantic_ordering_penalizes_reversed_blocks_even_when_tokens_are_present():
    gt = [
        {"id": "first", "text": "alpha one", "bbox": {"x": 0, "y": 0, "width": 10, "height": 10}},
        {"id": "second", "text": "beta two", "bbox": {"x": 0, "y": 20, "width": 10, "height": 10}},
    ]
    prediction = [
        {"id": "p2", "text": "beta two", "bbox": {"x": 0, "y": 20, "width": 10, "height": 10}},
        {"id": "p1", "text": "alpha one", "bbox": {"x": 0, "y": 0, "width": 10, "height": 10}},
    ]

    metrics, matches = evaluate_semantic_ordering(gt, prediction)

    assert metrics["token_F1"] == 1.0
    assert metrics["ordered_WER"] > 0.0
    assert metrics["kendall_tau"] == -1.0
    assert metrics["pairwise_accuracy"] == 0.0
    assert len(matches) == 2


def test_semantic_ordering_can_match_one_model_block_to_adjacent_gt_blocks():
    gt = [{"id": "a", "text": "first"}, {"id": "b", "text": "second"}]
    prediction = [{"id": "p", "text": "first second"}]

    metrics, matches = evaluate_semantic_ordering(gt, prediction, max_gt_span=2)

    assert metrics["ordered_WER"] == 0.0
    assert metrics["matched_block_ratio"] == 1.0
    assert matches[0].gt_ids == ["a", "b"]
    assert matches[0].similarity == 1.0


def test_semantic_ordering_accepts_paragraph_level_dotsocr_response():
    gt = [
        {"id": "intro", "text": "First visible paragraph."},
        {"id": "body", "text": "Second visible paragraph."},
    ]
    predicted = parse_dotsocr_blocks_response(
        '[{"bbox": [0, 0, 100, 20], "category": "Text", "text": "First visible paragraph."},'
        '{"bbox": [0, 30, 100, 50], "category": "Text", "text": "Second visible paragraph."}]'
    )

    metrics, _ = evaluate_semantic_ordering(gt, predicted)

    assert metrics["ordered_WER"] == 0.0
    assert metrics["pairwise_accuracy"] == 1.0
