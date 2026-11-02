import copy
import hashlib
import io
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError
from reportlab.pdfgen import canvas

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
pytest.importorskip("fitz")

from polydocbench.benchmark import build_manifest
from polydocbench.noise import (
    NOISE_PROFILES, NoiseGeneration, pdf_to_noisy_dataset, pdf_to_noisy_images,
    render_pdf_page, replay_noise, scan_image_path,
)
from polydocbench.noise.provenance import pixel_sha256
from polydocbench.noise.scans import apply_pipeline_with_transform, jpeg_artifacts, reduce_resolution
from scripts.run_tesseract_ocr_experiment import _can_reuse_noise_page, _run_template_case, build_parser, ArticleCase


@pytest.fixture
def document(tmp_path):
    root = tmp_path / "corpus"
    case = root / "en/history_russia"
    template = case / "scientific_paper"
    template.mkdir(parents=True)
    pdf_path = template / "document.pdf"
    pdf = canvas.Canvas(str(pdf_path), pagesize=(120, 80), invariant=1)
    for page in (1, 2):
        pdf.setFillColorRGB(0.8, 0.1, 0.2)
        pdf.rect(65, 10, 40, 25, fill=1)
        pdf.setFillColorRGB(0, 0, 0)
        pdf.drawString(10, 45, f"Page {page}")
        pdf.showPage()
    pdf.save()
    elements = [{"id": f"line_{page}", "type": "text_line", "content": f"Page {page}",
                 "bbox": {"x": 10, "y": 40, "width": 45, "height": 12, "page": page}}
                for page in (1, 2)]
    gt_path = template / "document_gt.json"
    gt_path.write_text(json.dumps({
        "schema_version": "0.1", "elements": elements,
        "reading_order": {"blocks": [], "lines": [element["id"] for element in elements]},
        "pages": [{"page_number": page, "width": 120, "height": 80,
                   "containers": [{"id": f"container_{page}", "elements": [elements[page - 1]]}]} for page in (1, 2)],
    }), encoding="utf-8")
    (case / "source.json").write_text(json.dumps({
        "schema_version": "0.1", "url": "https://en.wikipedia.org/wiki/Test",
        "content": [{"type": "paragraph", "text": "Test source"}],
    }), encoding="utf-8")
    return root, pdf_path, gt_path


def _generate(document, directory, **kwargs):
    _, pdf_path, gt_path = document
    return pdf_to_noisy_dataset(pdf_path, gt_path, directory, dpi=72, **kwargs)


def _by_name(result):
    return {(artifact["profile"], artifact["variant"]): artifact for artifact in result["artifacts"]}


def test_profiles_filter_order_and_variant_count_do_not_change_existing_samples(document, tmp_path):
    all_profiles = _generate(document, tmp_path / "all", profiles=["clean", "light_scan", "medium_scan", "heavy_scan"],
                             n_variants=3, seed=123)
    subset = _generate(document, tmp_path / "subset", profiles=["heavy_scan", "medium_scan"], n_variants=1, seed=123)
    original = _by_name(all_profiles)
    assert len(all_profiles["artifacts"]) == 10
    for key, artifact in _by_name(subset).items():
        assert Path(artifact["image_path"]).read_bytes() == Path(original[key]["image_path"]).read_bytes()
        assert artifact["noise_generation"] == original[key]["noise_generation"]


def test_clean_control_is_lossless_and_has_pixel_gt(document, tmp_path):
    result = _generate(document, tmp_path / "clean", profiles=["clean"], n_variants=3)
    assert len(result["artifacts"]) == 1
    artifact = result["artifacts"][0]
    base, _ = render_pdf_page(document[1], dpi=72)
    with Image.open(artifact["image_path"]) as image:
        assert image.format == "PNG"
        assert np.array_equal(np.array(image), base)
    assert artifact["transform_matrix"] == [[1, 0, 0], [0, 1, 0]]
    gt = json.loads(Path(artifact["gt_path"]).read_text())
    line = gt["pages"][0]["containers"][0]["elements"][0]
    assert line["bbox"] == {"x": 10, "y": 28, "width": 45, "height": 12, "page": 1}
    assert gt["metadata"]["coordinate_system"]["unit"] == "pixels"
    assert artifact["noise_generation"]["operations"] == []


@pytest.mark.parametrize("profile", ["clean", "light_scan", "medium_scan", "heavy_scan"])
def test_trace_replays_pixels_matrix_and_encoded_file(document, tmp_path, profile):
    artifact = _generate(document, tmp_path / profile, profiles=[profile], n_variants=1)["artifacts"][0]
    trace = NoiseGeneration.model_validate(artifact["noise_generation"])
    base, _ = render_pdf_page(document[1], dpi=72)
    replay = replay_noise(base, trace)
    assert pixel_sha256(replay.image) == trace.processed_pixels_sha256
    assert replay.transform_matrix == trace.transform_matrix == artifact["transform_matrix"]
    buffer = io.BytesIO()
    if profile == "clean":
        Image.fromarray(replay.image).save(buffer, "PNG")
    else:
        Image.fromarray(replay.image).save(buffer, "JPEG", quality=95)
    assert hashlib.sha256(buffer.getvalue()).hexdigest() == trace.image_sha256


def test_generation_preserves_python_and_numpy_global_rng(document, tmp_path):
    random.seed(123)
    np.random.seed(321)
    before_python, before_numpy = random.getstate(), np.random.get_state()
    _generate(document, tmp_path / "rng", profiles=["heavy_scan"])
    assert random.getstate() == before_python
    after_numpy = np.random.get_state()
    assert before_numpy[0] == after_numpy[0]
    assert np.array_equal(before_numpy[1], after_numpy[1])
    assert before_numpy[2:] == after_numpy[2:]


def test_concurrent_generation_is_identical(document, tmp_path):
    def generate(index):
        return _generate(document, tmp_path / str(index), profiles=["medium_scan"], n_variants=1)["artifacts"][0]

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(generate, (1, 2)))
    assert first["noise_generation"] == second["noise_generation"]
    assert Path(first["image_path"]).read_bytes() == Path(second["image_path"]).read_bytes()


def test_artifact_seeds_distinguish_pages_variants_and_master_seed(document, tmp_path):
    first = _generate(document, tmp_path / "first", profiles=["medium_scan"], n_variants=2, seed=10)
    second = _generate(document, tmp_path / "second", profiles=["medium_scan"], n_variants=1, seed=11)
    page_two = _generate(document, tmp_path / "page2", profiles=["medium_scan"], n_variants=1, seed=10, page_index=1)
    seeds = [artifact["noise_generation"]["artifact_seed"] for run in (first, second, page_two) for artifact in run["artifacts"]]
    assert len(set(seeds)) == 4
    gt = json.loads(Path(page_two["artifacts"][0]["gt_path"]).read_text())
    assert gt["pages"][0]["page_number"] == 1
    assert gt["metadata"]["noise_generation"]["source_page_number"] == 2


def test_operation_stream_is_not_shifted_by_another_operation(document):
    base, _ = render_pdf_page(document[1], dpi=72)
    from polydocbench.noise.scans import random_affine, illumination_gradient

    short = apply_pipeline_with_transform(base, [random_affine], seed=15)
    long = apply_pipeline_with_transform(base, [illumination_gradient, random_affine], seed=15)
    assert short.operations[0] == long.operations[1]
    assert short.transform_matrix == long.transform_matrix


def test_images_only_mode_saves_trace_sidecars_and_keeps_three_default_profiles(document, tmp_path):
    result = pdf_to_noisy_images(document[1], tmp_path / "images", dpi=72, n_variants=1)
    assert result["profiles"] == ["light_scan", "medium_scan", "heavy_scan"]
    assert len(result["images"]) == 3
    for artifact in result["artifacts"]:
        trace = NoiseGeneration.model_validate_json(Path(artifact["trace_path"]).read_text())
        assert trace.source_gt_sha256 is None
        assert trace.image_sha256 == artifact["noise_generation"]["image_sha256"]


def test_paired_and_images_only_modes_produce_identical_scan_pixels(document, tmp_path):
    paired = _generate(document, tmp_path / "paired", profiles=["medium_scan"], n_variants=1)
    plain = pdf_to_noisy_images(document[1], tmp_path / "plain", profiles=["medium_scan"], n_variants=1, dpi=72)
    assert Path(paired["artifacts"][0]["image_path"]).read_bytes() == Path(plain["images"][0]).read_bytes()


@pytest.mark.parametrize("kwargs", [
    {"seed": -1}, {"seed": True}, {"n_variants": 0}, {"n_variants": True}, {"dpi": 0},
    {"profiles": []}, {"profiles": ["unknown"]}, {"profiles": ["clean", "clean"]}, {"page_index": -1},
])
def test_invalid_generation_arguments_fail_before_writing(document, tmp_path, kwargs):
    target = tmp_path / "invalid"
    with pytest.raises(ValueError):
        pdf_to_noisy_dataset(document[1], document[2], target, **kwargs)
    assert not target.exists()


def test_one_pixel_resolution_and_rgb_jpeg_handling():
    tiny = np.array([[[250, 5, 2]]], dtype=np.uint8)
    assert reduce_resolution(tiny, rng=random.Random(1)).shape == (1, 1, 3)
    red = np.full((10, 10, 3), [240, 10, 5], dtype=np.uint8)
    decoded = jpeg_artifacts(red, quality_range=(100, 100))
    assert decoded[:, :, 0].mean() > 200 and decoded[:, :, 2].mean() < 20


def test_custom_callables_are_not_claimed_as_replayable(document, tmp_path, monkeypatch):
    base, _ = render_pdf_page(document[1], dpi=72)
    custom = lambda image: image.copy()
    assert not apply_pipeline_with_transform(base, [custom], seed=42).trace_complete
    monkeypatch.setitem(NOISE_PROFILES, "light_scan", [custom])
    with pytest.raises(ValueError, match="versioned built-in"):
        _generate(document, tmp_path / "untracked", profiles=["light_scan"])


@pytest.mark.parametrize("mutate", [
    lambda trace: trace.update(artifact_seed="0" * 64),
    lambda trace: trace.update(noise_pipeline_version="99"),
    lambda trace: trace["operations"][0].update(seed="0" * 64),
    lambda trace: trace["operations"][0]["parameters"].update(scale=float("nan")),
    lambda trace: trace["operations"][-1]["parameters"].update(quality=200),
])
def test_invalid_generation_trace_is_rejected(document, tmp_path, mutate):
    artifact = _generate(document, tmp_path / "trace", profiles=["medium_scan"], n_variants=1)["artifacts"][0]
    trace = copy.deepcopy(artifact["noise_generation"])
    mutate(trace)
    with pytest.raises(ValidationError):
        NoiseGeneration.model_validate(trace)


def test_replay_rejects_wrong_raster_or_pixel_hash(document, tmp_path):
    artifact = _generate(document, tmp_path / "trace", profiles=["medium_scan"], n_variants=1)["artifacts"][0]
    base, _ = render_pdf_page(document[1], dpi=72)
    wrong = base.copy()
    wrong[0, 0, 0] ^= 1
    with pytest.raises(ValueError, match="raster"):
        replay_noise(wrong, artifact["noise_generation"])
    trace = {**artifact["noise_generation"], "processed_pixels_sha256": "0" * 64}
    with pytest.raises(ValueError, match="Replay pixels"):
        replay_noise(base, trace)


def test_manifest_accepts_traced_png_and_jpeg_without_claiming_full_reproducibility(document):
    root, pdf, _ = document
    target = pdf.parent / "noisy/page_001"
    _generate(document, target, profiles=["clean", "medium_scan"], n_variants=1)
    manifest = build_manifest(root)
    assert not manifest.issues and len(manifest.records) == 2
    for record in manifest.records:
        assert record.noise_generation is not None
        assert "generation_seed_not_recorded" not in record.provenance_gaps
        assert "sampled_noise_parameters_not_recorded" not in record.provenance_gaps
        assert "render_configuration_not_snapshotted" in record.provenance_gaps
    assert manifest.generation_reproducibility == "not_established"


@pytest.mark.parametrize("corruption", ["image", "pdf", "matrix"])
def test_manifest_rejects_trace_file_or_matrix_mismatch(document, corruption):
    root, pdf, _ = document
    artifact = _generate(document, pdf.parent / "noisy/page_001", profiles=["medium_scan"], n_variants=1)["artifacts"][0]
    if corruption == "matrix":
        gt_path = Path(artifact["gt_path"])
        data = json.loads(gt_path.read_text())
        data["metadata"]["transform"]["matrix"][0][2] += 1
        gt_path.write_text(json.dumps(data), encoding="utf-8")
    else:
        path = pdf if corruption == "pdf" else Path(artifact["image_path"])
        with path.open("ab") as file:
            file.write(b"tampered")
    manifest = build_manifest(root)
    assert len(manifest.issues) == 1 and not manifest.records


def test_reuse_checks_requested_configuration_and_missing_variants(document):
    _, pdf, gt = document
    page = pdf.parent / "noisy/page_001"
    args = build_parser().parse_args(["--profiles", "clean", "medium_scan", "--variants", "1", "--dpi", "72"])
    _generate(document, page, profiles=args.profiles, n_variants=1)
    assert _can_reuse_noise_page(page, pdf, gt, 0, args)
    args.variants = 2
    assert not _can_reuse_noise_page(page, pdf, gt, 0, args)
    args.seed += 1
    with pytest.raises(ValueError, match="configuration"):
        _can_reuse_noise_page(page, pdf, gt, 0, args)


def test_reuse_refuses_legacy_trace_without_modifying_files(document):
    _, pdf, gt = document
    page = pdf.parent / "noisy/page_001"
    artifact = _generate(document, page, profiles=["medium_scan"], n_variants=1)["artifacts"][0]
    path = Path(artifact["gt_path"])
    data = json.loads(path.read_text())
    del data["metadata"]["noise_generation"]
    path.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_bytes()
    args = build_parser().parse_args(["--profiles", "medium_scan", "--variants", "1", "--dpi", "72"])
    with pytest.raises(ValueError, match="legacy"):
        _can_reuse_noise_page(page, pdf, gt, 0, args)
    assert path.read_bytes() == before


def test_reuse_rejects_gt_matrix_different_from_recorded_operations(document):
    _, pdf, gt = document
    page = pdf.parent / "noisy/page_001"
    artifact = _generate(document, page, profiles=["medium_scan"], n_variants=1)["artifacts"][0]
    path = Path(artifact["gt_path"])
    data = json.loads(path.read_text())
    data["metadata"]["transform"]["matrix"][0][2] += 1
    path.write_text(json.dumps(data), encoding="utf-8")
    args = build_parser().parse_args(["--profiles", "medium_scan", "--dpi", "72"])
    with pytest.raises(ValueError, match="configuration"):
        _can_reuse_noise_page(page, pdf, gt, 0, args)


def test_tesseract_runner_evaluates_only_requested_profiles_and_supports_clean(document, monkeypatch):
    _, pdf, _ = document
    args = build_parser().parse_args(["--profiles", "clean", "medium_scan", "--variants", "1", "--dpi", "72", "--reuse"])
    page = pdf.parent / "noisy/page_001"
    _generate(document, page, profiles=args.profiles, n_variants=1)
    (page / "heavy_scan_0_gt.json").write_text("{}", encoding="utf-8")
    seen = []

    def predict(path, **kwargs):
        seen.append(Path(path).suffix)
        return []

    monkeypatch.setattr("scripts.run_tesseract_ocr_experiment.extract_tesseract_lines", predict)
    case = ArticleCase("en", "eng", "English", "history_russia", "Test", "https://en.wikipedia.org/wiki/Test")
    source = pdf.parent.parent / "source.json"
    rows = _run_template_case(case, args, source.parent, source, "scientific_paper")
    assert seen == [".png", ".jpg"]
    assert [row["profile"] for row in rows] == ["clean", "medium_scan"]
    assert all(row["noise_pipeline_version"] == "0.3" for row in rows)


def test_shared_scan_resolution_rejects_ambiguous_formats(tmp_path):
    gt_path = tmp_path / "clean_0_gt.json"
    (tmp_path / "clean_0.png").write_bytes(b"image")
    assert scan_image_path(gt_path).suffix == ".png"
    (tmp_path / "clean_0.jpg").write_bytes(b"stale")
    with pytest.raises(ValueError, match="Ambiguous"):
        scan_image_path(gt_path)
