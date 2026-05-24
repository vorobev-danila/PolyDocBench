from pathlib import Path
import json

import pytest
from reportlab.pdfgen import canvas


cv2 = pytest.importorskip("cv2")
fitz = pytest.importorskip("fitz")

from polydocbench.noise import (
    NOISE_PROFILES,
    draw_gt_overlay,
    pdf_to_noisy_dataset,
    pdf_to_noisy_images,
    render_pdf_page,
)
from polydocbench.gt.schema import validate_gt_document


def test_pdf_to_noisy_images_writes_selected_profile_variants():
    pdf_path = Path("outputs/test_runs/noise_input.pdf")
    output_dir = Path("outputs/test_runs/noisy")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(pdf_path), pagesize=(120, 80))
    pdf.drawString(12, 40, "Noise test")
    pdf.save()

    base_image, zoom = render_pdf_page(pdf_path, dpi=72)
    result = pdf_to_noisy_images(
        pdf_path=pdf_path,
        output_dir=output_dir,
        page_index=0,
        n_variants=1,
        seed=7,
        dpi=72,
        profiles=["light_scan"],
    )

    images = result["images"]
    assert zoom == 1
    assert base_image.shape[0] > 0
    assert result["profiles"] == ["light_scan"]
    assert len(images) == 1
    assert Path(images[0]).exists()
    assert Path(images[0]).suffix == ".jpg"


def test_pdf_to_noisy_images_rejects_unknown_profile():
    pdf_path = Path("outputs/test_runs/noise_unknown_profile.pdf")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(pdf_path), pagesize=(120, 80))
    pdf.drawString(12, 40, "Profile test")
    pdf.save()

    with pytest.raises(ValueError, match="Unknown noise profiles"):
        pdf_to_noisy_images(pdf_path, "outputs/test_runs/noisy_unknown", profiles=["unknown"])


def test_noise_profiles_are_available():
    assert {"light_scan", "medium_scan", "heavy_scan"}.issubset(NOISE_PROFILES)


def test_draw_gt_overlay_can_draw_polygon_or_bbox():
    from PIL import Image

    output_dir = Path("outputs/test_runs")
    image_path = output_dir / "debug_overlay_input.jpg"
    gt_path = output_dir / "debug_overlay_gt.json"
    polygon_output = output_dir / "debug_overlay_polygon.jpg"
    bbox_output = output_dir / "debug_overlay_bbox.jpg"
    output_dir.mkdir(parents=True, exist_ok=True)

    Image.new("RGB", (80, 60), "white").save(image_path)
    gt_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "containers": [
                            {
                                "elements": [
                                    {
                                        "id": "line_1",
                                        "bbox": {"x": 10, "y": 10, "width": 30, "height": 12},
                                        "polygon": [[10, 10], [40, 10], [40, 22], [10, 22]],
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert draw_gt_overlay(image_path, gt_path, polygon_output, mode="polygon") == str(polygon_output)
    assert draw_gt_overlay(image_path, gt_path, bbox_output, mode="bbox") == str(bbox_output)
    assert polygon_output.exists()
    assert bbox_output.exists()


def test_pdf_to_noisy_dataset_writes_transformed_gt_for_affine_profile():
    pdf_path = Path("outputs/test_runs/noise_dataset_input.pdf")
    gt_path = Path("outputs/test_runs/noise_dataset_input_gt.json")
    output_dir = Path("outputs/test_runs/noisy_dataset")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(pdf_path), pagesize=(120, 80))
    pdf.drawString(10, 24, "Affine GT")
    pdf.save()
    gt_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "metadata": {"generator": "PolyDocBench", "format_version": "0.1"},
                "reading_order": {"blocks": [], "lines": ["line_1"]},
                "pages": [
                    {
                        "page_number": 1,
                        "width": 120,
                        "height": 80,
                        "containers": [
                            {
                                "id": "main",
                                "type": "single_column",
                                "bbox": {"x": 0, "y": 0, "width": 120, "height": 80, "page": 1},
                                "elements": [
                                    {
                                        "id": "line_1",
                                        "type": "text_line",
                                        "content": "Affine GT",
                                        "bbox": {"x": 10, "y": 20, "width": 50, "height": 10, "page": 1},
                                    }
                                ],
                            }
                        ],
                    }
                ],
                "elements": [
                    {
                        "id": "line_1",
                        "type": "text_line",
                        "content": "Affine GT",
                        "bbox": {"x": 10, "y": 20, "width": 50, "height": 10, "page": 1},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = pdf_to_noisy_dataset(
        pdf_path=pdf_path,
        gt_path=gt_path,
        output_dir=output_dir,
        page_index=0,
        n_variants=1,
        seed=11,
        dpi=72,
        profiles=["medium_scan"],
    )

    artifact = result["artifacts"][0]
    noisy_gt = json.loads(Path(artifact["gt_path"]).read_text(encoding="utf-8"))
    validate_gt_document(noisy_gt)
    transformed_line = noisy_gt["pages"][0]["containers"][0]["elements"][0]

    assert Path(artifact["image_path"]).exists()
    assert Path(artifact["gt_path"]).exists()
    assert noisy_gt["metadata"]["coordinate_system"]["unit"] == "pixels"
    assert noisy_gt["metadata"]["coordinate_system"]["origin"] == "top-left"
    assert noisy_gt["metadata"]["profile"] == "medium_scan"
    assert transformed_line["polygon"]
    assert transformed_line["metadata"]["source_bbox"]["x"] == 10
    assert transformed_line["bbox"]["page"] == 1
    assert artifact["transform_matrix"] != [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
