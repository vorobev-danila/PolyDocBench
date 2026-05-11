from pathlib import Path

import pytest
from reportlab.pdfgen import canvas


cv2 = pytest.importorskip("cv2")
fitz = pytest.importorskip("fitz")

from polydocbench.degradation import NOISE_PROFILES, pdf_to_noisy_images, render_pdf_page


def test_pdf_to_noisy_images_writes_selected_profile_variants():
    pdf_path = Path("outputs/test_runs/degradation_input.pdf")
    output_dir = Path("outputs/test_runs/degraded")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(pdf_path), pagesize=(120, 80))
    pdf.drawString(12, 40, "Degradation test")
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
    pdf_path = Path("outputs/test_runs/degradation_unknown_profile.pdf")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(pdf_path), pagesize=(120, 80))
    pdf.drawString(12, 40, "Profile test")
    pdf.save()

    with pytest.raises(ValueError, match="Unknown degradation profiles"):
        pdf_to_noisy_images(pdf_path, "outputs/test_runs/degraded_unknown", profiles=["unknown"])


def test_noise_profiles_are_available():
    assert {"light_scan", "medium_scan", "heavy_scan"}.issubset(NOISE_PROFILES)
