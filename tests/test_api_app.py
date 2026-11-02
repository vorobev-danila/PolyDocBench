import json

import pytest


fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from polydocbench.api.app import app


def test_api_health_and_templates():
    client = TestClient(app)

    assert client.get("/health").json() == {"status": "ok"}
    templates = client.get("/templates").json()["templates"]
    assert "simple_article" in templates


def test_api_noise_profiles_and_pdf_endpoint(monkeypatch):
    def fake_noise_pdf_document(**kwargs):
        return {
            "pdf_path": kwargs["pdf_path"],
            "output_dir": kwargs["output_dir"],
            "images": ["outputs/api/light_scan_0.jpg"],
            "profiles": kwargs["profiles"],
            "zoom": 2.0,
        }

    monkeypatch.setattr("polydocbench.api.app.noise_pdf_document", fake_noise_pdf_document)
    client = TestClient(app)

    profiles = client.get("/noise/profiles").json()["profiles"]
    response = client.post(
        "/noise/pdf",
        json={
            "pdf_path": "outputs/api/source.pdf",
            "output_dir": "outputs/api/scans",
            "variants": 1,
            "profiles": ["light_scan"],
        },
    )

    assert "light_scan" in profiles
    assert "clean" in profiles
    assert response.status_code == 200
    assert response.json()["images"] == ["outputs/api/light_scan_0.jpg"]


def test_api_noise_with_gt_endpoint(monkeypatch):
    def fake_noise_pdf_with_gt_document(**kwargs):
        return {
            "pdf_path": kwargs["pdf_path"],
            "gt_path": kwargs["gt_path"],
            "output_dir": kwargs["output_dir"],
            "artifacts": [{"image_path": "outputs/api/light_scan_0.jpg", "gt_path": "outputs/api/light_scan_0_gt.json"}],
            "profiles": kwargs["profiles"],
            "zoom": 2.0,
        }

    monkeypatch.setattr("polydocbench.api.app.noise_pdf_with_gt_document", fake_noise_pdf_with_gt_document)
    client = TestClient(app)
    response = client.post(
        "/noise/pdf-with-gt",
        json={
            "pdf_path": "outputs/api/source.pdf",
            "gt_path": "outputs/api/source_gt.json",
            "output_dir": "outputs/api/scans",
            "variants": 1,
            "profiles": ["light_scan"],
        },
    )

    assert response.status_code == 200
    assert response.json()["artifacts"][0]["gt_path"] == "outputs/api/light_scan_0_gt.json"


@pytest.mark.parametrize("payload", [{"seed": -1}, {"seed": True}, {"variants": 0}, {"profiles": []}, {"page_index": -1}])
def test_api_rejects_invalid_noise_settings(payload):
    response = TestClient(app).post("/noise/pdf", json={"pdf_path": "unused.pdf", **payload})
    assert response.status_code == 422


def test_api_clean_scan_uses_lossless_png_and_returns_trace(tmp_path):
    pytest.importorskip("cv2")
    pytest.importorskip("fitz")
    from reportlab.pdfgen import canvas
    from polydocbench.noise import NoiseGeneration

    pdf_path = tmp_path / "input.pdf"
    pdf = canvas.Canvas(str(pdf_path), pagesize=(120, 80))
    pdf.drawString(10, 40, "Clean control")
    pdf.save()
    response = TestClient(app).post("/noise/pdf", json={
        "pdf_path": str(pdf_path), "output_dir": str(tmp_path / "scans"), "dpi": 72,
        "variants": 3, "profiles": ["clean"],
    })
    assert response.status_code == 200
    data = response.json()
    assert data["noise_pipeline_version"] == "0.3" and len(data["images"]) == 1
    assert data["images"][0].endswith("clean_0.png")
    assert NoiseGeneration.model_validate(data["artifacts"][0]["noise_generation"]).operations == []


def test_api_structure_evaluation_endpoint(monkeypatch):
    def fake_evaluate_structure_from_gt(**kwargs):
        assert kwargs["gt_path"] == "outputs/api/source_gt.json"
        assert kwargs["predicted_elements"][0]["type"] == "paragraph"
        return {"structure_score": 1.0, "detection_F1": 1.0, "type_accuracy": 1.0, "mean_iou": 1.0}

    monkeypatch.setattr("polydocbench.api.app.evaluate_structure_from_gt", fake_evaluate_structure_from_gt)
    client = TestClient(app)
    response = client.post(
        "/evaluate/structure",
        json={
            "gt_path": "outputs/api/source_gt.json",
            "page_number": 1,
            "iou_threshold": 0.5,
            "predicted_elements": [
                {
                    "id": "pred_1",
                    "type": "paragraph",
                    "text": "recognized block",
                    "bbox": {"x": 0, "y": 0, "width": 50, "height": 20},
                    "reading_order": 1,
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["structure_score"] == 1.0


def test_api_accepts_custom_noise_recipes(tmp_path):
    pytest.importorskip("cv2")
    pytest.importorskip("fitz")
    from reportlab.pdfgen import canvas

    pdf_path = tmp_path / "custom.pdf"
    pdf = canvas.Canvas(str(pdf_path), pagesize=(120, 80))
    pdf.drawString(10, 40, "Custom recipe")
    pdf.save()
    response = TestClient(app).post("/noise/pdf", json={
        "pdf_path": str(pdf_path), "output_dir": str(tmp_path / "scans"), "dpi": 72,
        "variants": 1, "profiles": ["my_blur"],
        "config": {"profiles": {"my_blur": [{"name": "defocus_blur", "parameters": {"sigma_pixels": 1.5}}]}},
    })
    assert response.status_code == 200
    trace = response.json()["artifacts"][0]["noise_generation"]
    assert trace["profile_definition"][0]["parameters"]["sigma_pixels"] == 1.5
    assert response.json()["images"][0].endswith(".png")


def test_api_quality_and_ordering_expose_protocol_and_nullable_scores(tmp_path):
    gt_path = tmp_path / "gt.json"
    gt_path.write_text(json.dumps({"pages": []}), encoding="utf-8")
    client = TestClient(app)
    predicted = {"id": "extra", "text": "hello", "bbox": {"x": 0, "y": 0, "width": 10, "height": 10}}

    quality = client.post("/evaluate/quality", json={"gt_path": str(gt_path), "predicted_lines": [predicted]})
    assert quality.status_code == 200
    assert quality.json()["evaluation_protocol_version"] == "0.2"
    assert quality.json()["false_positive_lines"] == 1
    assert quality.json()["micro_CER"] == 5.0

    ordering = client.post("/evaluate/ordering", json={"gt_path": str(gt_path)})
    assert ordering.status_code == 200
    assert ordering.json()["evaluation_protocol_version"] == "0.2"
    assert ordering.json()["kendall_tau"] is None
    assert ordering.json()["pairwise_accuracy"] is None
    assert ordering.json()["num_order_pairs"] == 0


def test_api_renders_complex_example_with_new_profile(tmp_path):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    client = TestClient(app)
    assert "research_illustrated" in client.get("/templates").json()["templates"]
    response = client.post("/render", json={
        "json_path": str(root / "examples/complex_document.json"),
        "output_pdf": str(tmp_path / "complex.pdf"), "template": "research_illustrated",
        "font_path": str(root / "DejaVu Sans/DejaVuSans.ttf"),
    })
    assert response.status_code == 200
    result = response.json()
    assert result["layout_warnings"] == []
    gt = json.loads(Path(result["gt_path"]).read_text(encoding="utf-8"))
    assert any(element["type"] == "table_cell" for element in gt["elements"])
