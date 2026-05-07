from polydocbench.document.normalize import flatten_source_content


def test_flatten_source_content_converts_wikipedia_notes_and_lists():
    result = flatten_source_content(
        [
            {"type": "hatnote", "text": "For other uses, see Example."},
            {
                "type": "list",
                "list_type": "ordered",
                "items": [{"text": "First point"}, {"text": "Second point"}],
            },
        ]
    )

    assert result == [
        {
            "type": "paragraph",
            "content": "For other uses, see Example.",
            "metadata": {"source_type": "hatnote"},
        },
        {
            "type": "paragraph",
            "content": "1. First point",
            "metadata": {"source_type": "list", "list_type": "ordered", "list_index": 1},
        },
        {
            "type": "paragraph",
            "content": "2. Second point",
            "metadata": {"source_type": "list", "list_type": "ordered", "list_index": 2},
        },
    ]
