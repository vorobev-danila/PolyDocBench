import argparse
import json
from pathlib import Path
import shutil

from scripts.run_docling_structure_experiment import _evaluate_artifact, discover_scan_artifacts


def test_discover_docling_structure_artifacts(tmp_path: Path):
    case = tmp_path / "en" / "article" / "simple_article" / "noisy" / "page_001"
    case.mkdir(parents=True)
    (case / "light_scan_0.jpg").write_bytes(b"image")
    (case / "light_scan_0_gt.json").write_text("{}", encoding="utf-8")

    artifacts = discover_scan_artifacts(tmp_path, languages=["en"], profiles=["light_scan"])

    assert len(artifacts) == 1
    assert artifacts[0].article_id == "article"
    assert artifacts[0].page_number == 1


def test_discover_structure_clean_png(tmp_path: Path):
    page = tmp_path / "en/article/simple_article/noisy/page_002"
    page.mkdir(parents=True)
    (page / "clean_0_gt.json").write_text("{}", encoding="utf-8")
    (page / "clean_0.png").write_bytes(b"image")
    artifact = discover_scan_artifacts(tmp_path, profiles=["clean"])[0]
    assert artifact.image_path.suffix == ".png"
    assert artifact.page_number == 2 and artifact.profile == "clean"


def test_docling_structure_experiment_reuses_raw_output(tmp_path: Path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    case = input_root / "en" / "article" / "simple_article" / "noisy" / "page_001"
    case.mkdir(parents=True)
    image_path = case / "light_scan_0.jpg"
    gt_path = case / "light_scan_0_gt.json"
    image_path.write_bytes(b"image")
    gt_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "pages": [
                        {
                            "page_number": 1,
                            "width": 100,
                            "height": 100,
                            "containers": [
                                {
                                    "id": "page_1",
                                    "elements": [
                                    {
                                        "id": "p1_line_001",
                                        "type": "text_line",
                                        "content": "Hello",
                                        "bbox": {"x": 0, "y": 0, "width": 50, "height": 20},
                                        "metadata": {"parent_id": "p1", "line_index": 1},
                                    }
                                ]
                            }
                        ],
                    }
                ],
                "elements": [{"id": "p1", "type": "paragraph", "metadata": {"role": "block", "reading_order": 1}}],
            }
        ),
        encoding="utf-8",
    )
    raw_path = output_root / "en" / "article" / "simple_article" / "noisy" / "page_001" / "light_scan_0_docling_raw.json"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text(
        json.dumps(
            {
                "texts": [
                    {
                        "label": "text",
                        "text": "Hello",
                        "prov": [{"page_no": 1, "bbox": {"x": 0, "y": 0, "width": 50, "height": 20}}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    artifact = discover_scan_artifacts(input_root)[0]
    args = argparse.Namespace(reuse=True, iou_threshold=0.5)

    row = _evaluate_artifact(artifact, args, input_root, output_root)

    assert row["structure_score"] == 1.0
    assert row["detection_F1"] == 1.0
    assert (raw_path.parent / "light_scan_0_docling_structure.json").exists()

    page_two = case.with_name("page_002")
    shutil.copytree(case, page_two)
    raw_two = raw_path.parent.with_name("page_002") / raw_path.name
    raw_two.parent.mkdir(parents=True)
    shutil.copyfile(raw_path, raw_two)
    # Stale normalized cache must not hide valid raw one-page output.
    (raw_two.parent / "light_scan_0_docling_structure.json").write_text("[]", encoding="utf-8")
    artifact_two = discover_scan_artifacts(input_root, page_numbers=[2])[0]
    row_two = _evaluate_artifact(artifact_two, args, input_root, output_root)
    assert row_two["page_number"] == 2 and row_two["image_page_number"] == 1
    assert row_two["detection_F1"] == 1 and row_two["num_gt_elements"] == 1
