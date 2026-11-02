"""Synthetic scans with artifact-local randomness and replayable operations."""

from __future__ import annotations

import json
import platform
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from typing import Any

from polydocbench.gt.schema import validate_gt_document
from polydocbench.noise.geometry import transform_gt_to_image_gt
from polydocbench.noise.provenance import (
    NOISE_PIPELINE_VERSION, PARAMETER_MODELS, PROFILE_OPERATIONS, NoiseGeneration, NoiseOperation,
    derive_seed, file_sha256, pixel_sha256,
)


ImageArray = Any
NoiseFn = Callable[[ImageArray], ImageArray]
DEFAULT_NOISE_PROFILES = ("light_scan", "medium_scan", "heavy_scan")


@dataclass(frozen=True)
class NoiseResult:
    image: ImageArray
    transform_matrix: list[list[float]]
    operations: list[NoiseOperation] = field(default_factory=list)
    trace_complete: bool = True


def _require_cv2():
    import cv2

    return cv2


def _require_numpy():
    import numpy as np

    return np


def render_pdf_page(pdf_path: str | Path, page_index: int = 0, dpi: int = 200) -> tuple[ImageArray, float]:
    """Rasterize a PDF page to RGB; page_index is zero-based."""
    import fitz
    from PIL import Image

    if page_index < 0 or dpi <= 0:
        raise ValueError("page_index must be nonnegative and dpi must be positive")
    with fitz.open(pdf_path) as document:
        if page_index >= len(document):
            raise ValueError(f"page_index {page_index} is outside the PDF")
        zoom = dpi / 72
        pixmap = document[page_index].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
        return _require_numpy().array(image), zoom


def _sample_parameters(name: str, image: ImageArray, rng: random.Random, **overrides) -> dict:
    if name == "reduce_resolution":
        return {"scale": rng.uniform(*overrides.get("scale_range", (0.4, 0.8)))}
    if name == "illumination_gradient":
        return {"left_factor": rng.uniform(0.8, 1.0), "right_factor": rng.uniform(0.8, 1.0)}
    if name == "random_affine":
        height, width = image.shape[:2]
        angle, shear = rng.uniform(-2, 2), rng.uniform(-0.05, 0.05)
        matrix = _require_cv2().getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
        matrix[0, 1] += shear
        return {"angle_degrees": angle, "shear": shear, "matrix": _matrix_to_list(matrix)}
    if name == "ink_morphology":
        return {"mode": overrides.get("mode") or rng.choice(["erode", "dilate"])}
    if name == "jpeg_artifacts":
        return {"quality": rng.randint(*overrides.get("quality_range", (30, 70)))}
    raise ValueError(f"Unsupported noise operation: {name}")


def _apply_parameters(image: ImageArray, name: str, parameters: dict) -> NoiseResult:
    cv2, np = _require_cv2(), _require_numpy()
    values = PARAMETER_MODELS[name].model_validate(parameters).model_dump()
    matrix = np.eye(3, dtype=float)[:2]
    height, width = image.shape[:2]
    if name == "reduce_resolution":
        small = cv2.resize(image, (max(1, int(width * values["scale"])), max(1, int(height * values["scale"]))),
                           interpolation=cv2.INTER_AREA)
        output = cv2.resize(small, (width, height), interpolation=cv2.INTER_CUBIC)
    elif name == "illumination_gradient":
        gradient = np.linspace(values["left_factor"], values["right_factor"], width)
        output = np.clip(image.astype(np.float32) * gradient[None, :, None], 0, 255).astype(np.uint8)
    elif name == "random_affine":
        matrix = np.asarray(values["matrix"], dtype=float)
        output = cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_REPLICATE)
    elif name == "ink_morphology":
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        kernel = np.ones((2, 2), np.uint8)
        function = cv2.erode if values["mode"] == "erode" else cv2.dilate
        output = cv2.cvtColor(function(binary, kernel, iterations=1), cv2.COLOR_GRAY2RGB)
    else:
        success, encoded = cv2.imencode(".jpg", cv2.cvtColor(image, cv2.COLOR_RGB2BGR),
                                       [int(cv2.IMWRITE_JPEG_QUALITY), values["quality"]])
        if not success:
            raise RuntimeError("JPEG encoding failed")
        output = cv2.cvtColor(cv2.imdecode(encoded, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    return NoiseResult(image=output, transform_matrix=_matrix_to_list(matrix))


def _single(image, name, rng=None, **overrides):
    return _apply_parameters(image, name, _sample_parameters(name, image, rng or random.Random(), **overrides))


def reduce_resolution(image: ImageArray, scale_range=(0.4, 0.8), *, rng=None) -> ImageArray:
    return _single(image, "reduce_resolution", rng, scale_range=scale_range).image


def illumination_gradient(image: ImageArray, *, rng=None) -> ImageArray:
    return _single(image, "illumination_gradient", rng).image


def ink_morphology(image: ImageArray, mode="erode") -> ImageArray:
    return _single(image, "ink_morphology", mode=mode).image


def random_affine(image: ImageArray, *, rng=None) -> ImageArray:
    return random_affine_with_transform(image, rng=rng).image


def random_affine_with_transform(image: ImageArray, *, rng=None) -> NoiseResult:
    return _single(image, "random_affine", rng)


def jpeg_artifacts(image: ImageArray, quality_range=(30, 70), *, rng=None) -> ImageArray:
    return _single(image, "jpeg_artifacts", rng, quality_range=quality_range).image


NOISE_PROFILES: dict[str, list[NoiseFn]] = {
    "clean": [],
    "light_scan": [reduce_resolution, illumination_gradient, jpeg_artifacts],
    "medium_scan": [reduce_resolution, random_affine, illumination_gradient, jpeg_artifacts],
    "heavy_scan": [reduce_resolution, random_affine, illumination_gradient, ink_morphology, jpeg_artifacts],
}
_BUILTINS = {function: name for name, function in (
    ("reduce_resolution", reduce_resolution), ("random_affine", random_affine),
    ("illumination_gradient", illumination_gradient), ("ink_morphology", ink_morphology),
    ("jpeg_artifacts", jpeg_artifacts),
)}


def apply_pipeline(image: ImageArray, pipeline: list[NoiseFn], *, seed: int | str | None = None) -> ImageArray:
    return apply_pipeline_with_transform(image, pipeline, seed=seed).image


def apply_pipeline_with_transform(
    image: ImageArray, pipeline: list[NoiseFn], *, seed: int | str | None = None,
) -> NoiseResult:
    """Use local operation streams; unknown custom callables are explicitly untracked."""
    np = _require_numpy()
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3 or min(image.shape[:2]) < 1:
        raise ValueError("Noise input must be a nonempty uint8 RGB array")
    local_seed = random.SystemRandom().getrandbits(256) if seed is None else seed
    output, cumulative = image.copy(), np.eye(3, dtype=float)
    operations, occurrences, complete = [], {}, True
    for function in pipeline:
        name = _BUILTINS.get(function)
        if name is None:
            output, complete = function(output), False
            continue
        occurrence = occurrences.get(name, 0)
        occurrences[name] = occurrence + 1
        operation_seed = derive_seed(local_seed, name, occurrence)
        parameters = _sample_parameters(name, output, random.Random(int(operation_seed, 16)))
        result = _apply_parameters(output, name, parameters)
        output = result.image
        cumulative = _to_homogeneous(result.transform_matrix) @ cumulative
        operations.append(NoiseOperation(name=name, seed=operation_seed, parameters=parameters))
    return NoiseResult(output, _matrix_to_list(cumulative[:2]), operations, complete)


def replay_noise(image: ImageArray, generation: NoiseGeneration | dict) -> NoiseResult:
    """Replay recorded operations on the original RGB raster, before final file encoding."""
    generation = NoiseGeneration.model_validate(generation)
    if pixel_sha256(image) != generation.raster_sha256:
        raise ValueError("Replay raster does not match the generation trace")
    output, cumulative = image.copy(), _require_numpy().eye(3, dtype=float)
    for operation in generation.operations:
        result = _apply_parameters(output, operation.name, operation.parameters)
        output = result.image
        cumulative = _to_homogeneous(result.transform_matrix) @ cumulative
    if pixel_sha256(output) != generation.processed_pixels_sha256:
        raise ValueError("Replay pixels differ; check trace parameters and library versions")
    return NoiseResult(output, _matrix_to_list(cumulative[:2]), generation.operations)


def _validate_generation_args(n_variants, seed, dpi, profiles):
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    if isinstance(n_variants, bool) or not isinstance(n_variants, int) or n_variants < 1:
        raise ValueError("n_variants must be a positive integer")
    if isinstance(dpi, bool) or not isinstance(dpi, int) or dpi < 1:
        raise ValueError("dpi must be a positive integer")
    selected = list(DEFAULT_NOISE_PROFILES) if profiles is None else list(profiles)
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("profiles must be nonempty and unique")
    unknown = sorted(set(selected) - set(NOISE_PROFILES))
    if unknown:
        raise ValueError(f"Unknown noise profiles: {', '.join(unknown)}")
    for profile in selected:
        if profile not in PROFILE_OPERATIONS or [
            _BUILTINS.get(function) for function in NOISE_PROFILES[profile]
        ] != PROFILE_OPERATIONS[profile]:
            raise ValueError(f"Exported profile differs from the versioned built-in definition: {profile}")
    return selected


def _generate_scans(pdf_path, gt_path, output_dir, page_index, n_variants, seed, dpi, profiles):
    from PIL import Image

    selected = _validate_generation_args(n_variants, seed, dpi, profiles)
    source_gt = None if gt_path is None else json.loads(Path(gt_path).read_text(encoding="utf-8"))
    if source_gt is not None:
        validated = validate_gt_document(source_gt)
        if page_index + 1 not in {page.page_number for page in validated.pages}:
            raise ValueError("Selected PDF page is absent from source GT")
    base_image, zoom = render_pdf_page(pdf_path, page_index=page_index, dpi=dpi)
    raster_hash = pixel_sha256(base_image)
    pdf_hash = file_sha256(pdf_path)
    gt_hash = None if gt_path is None else file_sha256(gt_path)
    environment = {"python": platform.python_version(), "numpy": version("numpy"),
                   "pillow": version("pillow"), "opencv": _require_cv2().__version__, "pymupdf": version("pymupdf")}
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for profile in selected:
        for index in range(1 if profile == "clean" else n_variants):
            artifact_seed = derive_seed(seed, NOISE_PIPELINE_VERSION, raster_hash, page_index + 1, dpi, profile, index)
            result = apply_pipeline_with_transform(base_image, NOISE_PROFILES[profile], seed=artifact_seed)
            if not result.trace_complete:
                raise ValueError("Exported profiles must contain only tracked built-in noise operations")
            suffix = ".png" if profile == "clean" else ".jpg"
            image_path = output_path / f"{profile}_{index}{suffix}"
            alternative = image_path.with_suffix(".jpg" if suffix == ".png" else ".png")
            if alternative.exists():
                raise ValueError(f"Conflicting scan format exists: {alternative}")
            image = Image.fromarray(result.image)
            if profile == "clean":
                image.save(image_path, "PNG")
            else:
                image.save(image_path, "JPEG", quality=95)
            generation = NoiseGeneration(
                trace_schema_version="0.1", noise_pipeline_version=NOISE_PIPELINE_VERSION,
                seed_derivation="sha256-json-v1", master_seed=seed, artifact_seed=artifact_seed,
                source_page_number=page_index + 1, dpi=dpi, profile=profile, variant=index,
                source_pdf_sha256=pdf_hash, source_gt_sha256=gt_hash, raster_sha256=raster_hash,
                processed_pixels_sha256=pixel_sha256(result.image), image_sha256=file_sha256(image_path),
                operations=result.operations, encoding="PNG" if profile == "clean" else "JPEG-quality-95",
                environment=environment,
            )
            artifact = {"profile": profile, "variant": index, "image_path": str(image_path),
                        "transform_matrix": result.transform_matrix, "noise_generation": generation.model_dump()}
            if source_gt is None:
                trace_path = output_path / f"{profile}_{index}_noise.json"
                trace_path.write_text(generation.model_dump_json(indent=2) + "\n", encoding="utf-8")
                artifact["trace_path"] = str(trace_path)
            else:
                target_gt = output_path / f"{profile}_{index}_gt.json"
                noisy_gt = transform_gt_to_image_gt(
                    source_gt, image_path, pdf_path, gt_path, page_index + 1, zoom, base_image.shape[0],
                    result.image.shape[1], result.image.shape[0], result.transform_matrix, profile, index, dpi,
                )
                noisy_gt["metadata"]["noise_generation"] = generation.model_dump()
                target_gt.write_text(json.dumps(noisy_gt, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
                artifact["gt_path"] = str(target_gt)
            artifacts.append(artifact)
    return {"zoom": zoom, "profiles": selected, "artifacts": artifacts, "noise_pipeline_version": NOISE_PIPELINE_VERSION}


def pdf_to_noisy_images(
    pdf_path: str | Path, output_dir: str | Path, page_index: int = 0, n_variants: int = 3,
    seed: int = 42, dpi: int = 200, profiles: list[str] | None = None,
) -> dict[str, object]:
    """Save scan files and noise trace sidecars; clean PNG is opt-in."""
    result = _generate_scans(pdf_path, None, output_dir, page_index, n_variants, seed, dpi, profiles)
    return {**result, "images": [artifact["image_path"] for artifact in result["artifacts"]]}


def pdf_to_noisy_dataset(
    pdf_path: str | Path, gt_path: str | Path, output_dir: str | Path, page_index: int = 0,
    n_variants: int = 3, seed: int = 42, dpi: int = 200, profiles: list[str] | None = None,
) -> dict[str, object]:
    """Save scans, pixel GT and generation traces with artifact-local randomness."""
    return _generate_scans(pdf_path, gt_path, output_dir, page_index, n_variants, seed, dpi, profiles)


def _to_homogeneous(matrix: list[list[float]]):
    homogeneous = _require_numpy().eye(3, dtype=float)
    homogeneous[:2] = matrix
    return homogeneous


def _matrix_to_list(matrix) -> list[list[float]]:
    return [[float(value) for value in row] for row in matrix]
