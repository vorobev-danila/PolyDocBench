import copy
import hashlib
import io
import json
import random
from pathlib import Path

import pytest
from PIL import Image
from reportlab.pdfgen import canvas

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
pytest.importorskip("fitz")

from polydocbench.noise import (NOISE_PROFILES, NoiseGeneration, NoiseStep,
                                pdf_to_noisy_dataset, render_pdf_page, replay_noise)
from polydocbench.noise.provenance import derive_seed, pixel_sha256
from polydocbench.noise.scans import apply_pipeline_with_transform


PROFILES = ["defocus_scan", "motion_scan", "sensor_noise", "faded_print", "shadow_scan", "duplex_scan", "camera_capture"]


@pytest.fixture
def source(tmp_path):
    pdf_path = tmp_path / "document.pdf"
    pdf = canvas.Canvas(str(pdf_path), pagesize=(200, 120), invariant=1)
    pdf.drawString(12, 70, "Replayable scan noise")
    pdf.save()
    element = {"id": "line_1", "type": "text_line", "content": "Replayable scan noise",
               "bbox": {"x": 12, "y": 67, "width": 150, "height": 14, "page": 1}}
    data = {"schema_version": "0.1", "elements": [element],
            "reading_order": {"lines": ["line_1"], "blocks": []},
            "pages": [{"page_number": 1, "width": 200, "height": 120,
                       "containers": [{"id": "main", "elements": [element]}]}]}
    gt_path = tmp_path / "document_gt.json"
    gt_path.write_text(json.dumps(data), encoding="utf-8")
    return pdf_path, gt_path


@pytest.mark.parametrize("profile", PROFILES)
def test_new_effects_are_lossless_export_replayable_and_preserve_gt(source, tmp_path, profile):
    result = pdf_to_noisy_dataset(*source, tmp_path / profile, dpi=120,
                                  profiles=["clean", profile], n_variants=1)
    clean, artifact = result["artifacts"]
    assert artifact["image_path"].endswith(".png")
    base, _ = render_pdf_page(source[0], dpi=120)
    trace = NoiseGeneration.model_validate(artifact["noise_generation"])
    replay = replay_noise(base, trace)
    with Image.open(artifact["image_path"]) as image:
        assert image.format == "PNG"
        assert np.array_equal(np.array(image), replay.image)
    assert not np.array_equal(base, replay.image)
    assert replay.transform_matrix == [[1, 0, 0], [0, 1, 0]]
    first = json.loads(Path(clean["gt_path"]).read_text())
    second = json.loads(Path(artifact["gt_path"]).read_text())
    for key in ("elements", "pages", "reading_order"):
        assert first[key] == second[key]


def test_custom_recipe_identity_fixed_parameters_and_order_independence(source, tmp_path):
    config = {"profiles": {"custom_blur": [{"name": "defocus_blur", "parameters": {"sigma_pixels": 0.8}}]}}
    first = pdf_to_noisy_dataset(*source, tmp_path / "a", dpi=72, profiles=["clean", "custom_blur"],
                                 config=config, n_variants=2)
    second = pdf_to_noisy_dataset(*source, tmp_path / "b", dpi=72, profiles=["custom_blur", "clean"],
                                  config=config, n_variants=1)
    a, b = first["artifacts"][1], second["artifacts"][0]
    assert a["noise_generation"] == b["noise_generation"]
    assert Path(a["image_path"]).read_bytes() == Path(b["image_path"]).read_bytes()
    assert a["noise_generation"]["operations"][0]["parameters"]["sigma_pixels"] == 0.8
    config["profiles"]["custom_blur"][0]["parameters"]["sigma_pixels"] = 1.6
    different = pdf_to_noisy_dataset(*source, tmp_path / "c", dpi=72, profiles=["custom_blur"],
                                     config=config, n_variants=1)["artifacts"][0]
    assert different["noise_generation"]["artifact_seed"] != a["noise_generation"]["artifact_seed"]
    changed = copy.deepcopy(a["noise_generation"])
    changed["operations"][0]["parameters"]["sigma_pixels"] = 3
    with pytest.raises(ValueError, match="recipe overrides"):
        NoiseGeneration.model_validate(changed)


def test_sensor_stream_is_local_and_dpi_is_recorded_as_actual_blur_parameters(source):
    base, _ = render_pdf_page(source[0], dpi=72)
    python_state, numpy_state = random.getstate(), np.random.get_state()
    first = apply_pipeline_with_transform(base, NOISE_PROFILES["camera_capture"], seed=7, dpi=100)
    again = apply_pipeline_with_transform(base, NOISE_PROFILES["camera_capture"], seed=7, dpi=100)
    larger = apply_pipeline_with_transform(base, NOISE_PROFILES["defocus_scan"], seed=7, dpi=200)
    assert np.array_equal(first.image, again.image)
    assert random.getstate() == python_state
    after = np.random.get_state()
    assert numpy_state[0] == after[0] and np.array_equal(numpy_state[1], after[1])
    assert numpy_state[2:] == after[2:]
    assert larger.operations[0].parameters["sigma_pixels"] == 2 * first.operations[0].parameters["sigma_pixels"]
    noise = next(operation for operation in first.operations if operation.name == "sensor_noise")
    assert isinstance(noise.parameters["noise_seed"], str) and len(noise.parameters["noise_seed"]) == 64


@pytest.mark.parametrize("profile", PROFILES)
def test_new_effects_handle_one_pixel_rgb(profile):
    tiny = np.array([[[210, 20, 4]]], dtype=np.uint8)
    result = apply_pipeline_with_transform(tiny, NOISE_PROFILES[profile], seed=42)
    assert result.image.shape == tiny.shape and result.image.dtype == np.uint8


@pytest.mark.parametrize("config", [
    {"profiles": {"../escape": [{"name": "defocus_blur"}]}},
    {"profiles": {"clean": [{"name": "sensor_noise"}]}},
    {"profiles": {"custom": []}},
    {"profiles": {"custom": [{"name": "unknown", "parameters": {"x": 1}}]}},
    {"profiles": {"custom": [{"name": "sensor_noise", "parameters": {"sigma": float("nan")}}]}},
    {"profiles": {"custom": [{"name": "local_shadow", "parameters": {"opacity": 0.3}}]}},
    {"profiles": {"custom": [{"name": "motion_blur", "parameters": {"length_pixels": 4}}]}},
])
def test_invalid_recipes_fail_before_writing(source, tmp_path, config):
    output = tmp_path / "invalid"
    with pytest.raises(ValueError):
        pdf_to_noisy_dataset(*source, output, profiles=["custom"], config=config)
    assert not output.exists()


def test_replay_of_v02_trace_remains_supported(source, tmp_path):
    base, _ = render_pdf_page(source[0], dpi=72)
    seed = derive_seed(42, "0.2", pixel_sha256(base), 1, 72, "light_scan", 0)
    result = apply_pipeline_with_transform(base, NOISE_PROFILES["light_scan"], seed=seed)
    encoded = io.BytesIO()
    Image.fromarray(result.image).save(encoded, "JPEG", quality=95)
    current = pdf_to_noisy_dataset(*source, tmp_path / "new", dpi=72, profiles=["light_scan"], n_variants=1)["artifacts"][0]
    trace = {**current["noise_generation"], "noise_pipeline_version": "0.2", "artifact_seed": seed,
             "operations": [op.model_dump() for op in result.operations],
             "processed_pixels_sha256": pixel_sha256(result.image),
             "image_sha256": hashlib.sha256(encoded.getvalue()).hexdigest()}
    assert np.array_equal(replay_noise(base, trace).image, result.image)


def test_custom_affine_parameters_drive_pixels_and_gt(source, tmp_path):
    config = {"profiles": {"rotated_blur": [
        {"name": "random_affine", "parameters": {"angle_degrees": 5, "shear": 0}},
        {"name": "defocus_blur", "parameters": {"sigma_pixels": 1}},
    ]}}
    artifact = pdf_to_noisy_dataset(*source, tmp_path / "affine", dpi=72, profiles=["rotated_blur"],
                                    config=config, n_variants=1)["artifacts"][0]
    import cv2

    expected = cv2.getRotationMatrix2D((100, 60), 5, 1.0)
    assert np.allclose(artifact["transform_matrix"], expected)
    gt = json.loads(Path(artifact["gt_path"]).read_text())
    assert np.allclose(gt["metadata"]["transform"]["matrix"], expected)
    trace = NoiseGeneration.model_validate(artifact["noise_generation"])
    base, _ = render_pdf_page(source[0], dpi=72)
    assert replay_noise(base, trace).transform_matrix == artifact["transform_matrix"]


def test_disabled_effects_are_exact_identity():
    image = np.arange(8 * 10 * 3, dtype=np.uint8).reshape(8, 10, 3)
    steps = [NoiseStep(name="defocus_blur", parameters={"sigma_pixels": 0}),
             NoiseStep(name="motion_blur", parameters={"length_pixels": 1}),
             NoiseStep(name="sensor_noise", parameters={"sigma": 0}),
             NoiseStep(name="faded_ink", parameters={"retained_contrast": 1}),
             NoiseStep(name="local_shadow", parameters={"strength": 0}),
             NoiseStep(name="bleed_through", parameters={"opacity": 0})]
    assert np.array_equal(apply_pipeline_with_transform(image, steps, seed=42).image, image)


def test_noise_cli_exports_custom_recipe_with_gt(source, tmp_path):
    from polydocbench.cli import main

    config = tmp_path / "recipes.json"
    config.write_text(json.dumps({"profiles": {"my_blur": [{"name": "defocus_blur"}]}}), encoding="utf-8")
    target = tmp_path / "cli"
    assert main(["noise", str(source[0]), "--gt", str(source[1]), "-o", str(target), "--dpi", "72",
                 "--profiles", "my_blur", "--noise-config", str(config)]) == 0
    assert (target / "my_blur_0.png").exists()
    assert (target / "my_blur_0_gt.json").exists()
