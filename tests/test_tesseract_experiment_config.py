from scripts.run_tesseract_ocr_experiment import ARTICLE_CASES, _select_cases, _select_page_indices


def test_article_pool_contains_ten_articles_per_language():
    languages = {case.code for case in ARTICLE_CASES}

    assert languages == {"en", "ru", "fr", "de", "es", "it"}
    for language in languages:
        assert len([case for case in ARTICLE_CASES if case.code == language]) == 10


def test_article_selection_supports_language_limit_and_article_ids():
    cases = _select_cases(["en", "ru"], ["linear_algebra", "ai"], limit_per_language=1)

    assert [(case.code, case.article_id) for case in cases] == [
        ("en", "linear_algebra"),
        ("ru", "linear_algebra"),
    ]


def test_page_scope_selection():
    assert _select_page_indices(10, "first") == [0]
    assert _select_page_indices(10, "half") == [0, 1, 2, 3, 4]
    assert _select_page_indices(3, "all") == [0, 1, 2]


def test_default_template_profile_matrix_has_nine_variants():
    templates = ["simple_article", "scientific_paper", "magazine_layout"]
    profiles = ["light_scan", "medium_scan", "heavy_scan"]

    assert len(templates) * len(profiles) == 9
