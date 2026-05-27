from pathlib import Path

from scripts.run_dotsocr_ordering_experiment import _evaluate_artifact, discover_scan_artifacts


def test_discover_scan_artifacts_uses_pipeline_hierarchy(tmp_path: Path):
    page_dir = tmp_path / "en" / "history_russia" / "scientific_paper" / "noisy" / "page_001"
    page_dir.mkdir(parents=True)
    (page_dir / "medium_scan_0_gt.json").write_text("{}", encoding="utf-8")
    (page_dir / "medium_scan_0.jpg").write_bytes(b"image")
    (page_dir / "heavy_scan_0_gt.json").write_text("{}", encoding="utf-8")
    (page_dir / "heavy_scan_0.jpg").write_bytes(b"image")

    artifacts = discover_scan_artifacts(tmp_path, templates=["scientific_paper"], profiles=["medium_scan"])

    assert len(artifacts) == 1
    assert artifacts[0].profile == "medium_scan"
    assert artifacts[0].page_number == 1


def test_reuse_parses_saved_plain_text_response_without_remote_request(tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    page_dir = input_root / "en" / "article" / "simple_article" / "noisy" / "page_001"
    page_dir.mkdir(parents=True)
    gt_path = page_dir / "light_scan_0_gt.json"
    image_path = page_dir / "light_scan_0.jpg"
    image_path.write_bytes(b"image")
    gt_path.write_text(
        '{"pages":[{"page_number":1,"width":100,"height":100,"containers":[{"id":"page_1","elements":['
        '{"id":"p_line","type":"text_line","content":"Paragraph text.","bbox":{"x":0,"y":0,"width":10,"height":5,"page":1},'
        '"metadata":{"parent_id":"p","line_index":1,"reading_order":1}}]}]}],'
        '"elements":[{"id":"p","type":"paragraph","metadata":{"role":"block","reading_order":1}}]}',
        encoding="utf-8",
    )
    artifact = discover_scan_artifacts(input_root)[0]
    raw_path = output_root / "en" / "article" / "simple_article" / "noisy" / "page_001" / "light_scan_0_dotsocr_raw.txt"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("Paragraph text.", encoding="utf-8")
    args = type(
        "Args",
        (),
        {"reuse": True, "api_key_env": "TOKEN", "base_url": "", "model": "dots", "timeout": 1, "max_retries": 0,
         "min_block_similarity": 0.3, "max_gt_span": 3},
    )()

    result = _evaluate_artifact(artifact, args, input_root, output_root, api_key=None)

    assert result["ordered_WER"] == 0.0
