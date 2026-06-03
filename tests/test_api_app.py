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
