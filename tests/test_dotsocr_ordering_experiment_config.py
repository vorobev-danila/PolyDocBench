from pathlib import Path
import csv
import json

from scripts.run_dotsocr_ordering_experiment import _evaluate_artifact, discover_scan_artifacts, main


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


def test_discover_ordering_clean_png(tmp_path: Path):
    page = tmp_path / "en/article/simple_article/noisy/page_002"
    page.mkdir(parents=True)
    (page / "clean_0_gt.json").write_text("{}", encoding="utf-8")
    (page / "clean_0.png").write_bytes(b"image")
    artifact = discover_scan_artifacts(tmp_path, profiles=["clean"])[0]
    assert artifact.image_path.suffix == ".png"
    assert artifact.profile == "clean" and artifact.page_number == 2


def test_reuse_parses_saved_plain_text_response_without_remote_request(tmp_path: Path, monkeypatch, capsys):
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
    assert result["pairwise_accuracy"] is None

    monkeypatch.setattr("sys.argv", ["run_dotsocr_ordering_experiment.py", "--input-dir", str(input_root),
                                     "--output-dir", str(output_root), "--reuse", "--no-dashboard"])
    assert main() == 0
    assert "pairwise=N/A" in capsys.readouterr().out
    row = json.loads((output_root / "metrics.jsonl").read_text(encoding="utf-8"))
    assert row["pairwise_accuracy"] is None
    assert row["evaluation_protocol_version"] == "0.2"
    with (output_root / "summary.csv").open(encoding="utf-8", newline="") as file:
        summary = next(csv.DictReader(file))
    assert summary["valid_order_count"] == "0"
    assert summary["mean_pairwise_accuracy"] == ""
