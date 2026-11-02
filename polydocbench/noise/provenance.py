"""Path-independent seed derivation and validated scan-generation evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator


NOISE_PIPELINE_VERSION = "0.2"
HexDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PROFILE_OPERATIONS = {
    "clean": [],
    "light_scan": ["reduce_resolution", "illumination_gradient", "jpeg_artifacts"],
    "medium_scan": ["reduce_resolution", "random_affine", "illumination_gradient", "jpeg_artifacts"],
    "heavy_scan": ["reduce_resolution", "random_affine", "illumination_gradient", "ink_morphology", "jpeg_artifacts"],
}


def derive_seed(seed: int | str, *identity: Any) -> str:
    payload = json.dumps(["polydocbench-noise-sha256-v1", seed, *identity],
                         sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pixel_sha256(image) -> str:
    header = json.dumps([list(image.shape), str(image.dtype)], separators=(",", ":")).encode("ascii")
    return hashlib.sha256(header + b"\0" + image.tobytes(order="C")).hexdigest()


class _Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class _Resolution(_Parameters):
    scale: float = Field(gt=0, le=1)


class _Illumination(_Parameters):
    left_factor: float = Field(ge=0, le=1)
    right_factor: float = Field(ge=0, le=1)


class _Affine(_Parameters):
    angle_degrees: float
    shear: float
    matrix: list[list[float]]

    @field_validator("matrix")
    @classmethod
    def validate_matrix(cls, matrix):
        import math

        if len(matrix) != 2 or any(len(row) != 3 for row in matrix):
            raise ValueError("Expected a 2x3 affine matrix")
        if not all(math.isfinite(number) for row in matrix for number in row):
            raise ValueError("Affine matrix must be finite")
        return matrix


class _Morphology(_Parameters):
    mode: Literal["erode", "dilate"]


class _Jpeg(_Parameters):
    quality: int = Field(ge=1, le=100, strict=True)


PARAMETER_MODELS = {"reduce_resolution": _Resolution, "illumination_gradient": _Illumination,
                    "random_affine": _Affine, "ink_morphology": _Morphology, "jpeg_artifacts": _Jpeg}


class NoiseOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    name: Literal["reduce_resolution", "random_affine", "illumination_gradient", "ink_morphology", "jpeg_artifacts"]
    seed: HexDigest
    parameters: dict[str, Any]

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: dict, info: ValidationInfo) -> dict:
        if name := info.data.get("name"):
            return PARAMETER_MODELS[name].model_validate(value).model_dump()
        return value


class NoiseGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    trace_schema_version: Literal["0.1"]
    noise_pipeline_version: Literal["0.2"]
    seed_derivation: Literal["sha256-json-v1"]
    master_seed: int = Field(ge=0, strict=True)
    artifact_seed: HexDigest
    source_page_number: int = Field(gt=0)
    dpi: int = Field(gt=0)
    profile: Literal["clean", "light_scan", "medium_scan", "heavy_scan"]
    variant: int = Field(ge=0)
    source_pdf_sha256: HexDigest
    source_gt_sha256: HexDigest | None
    raster_sha256: HexDigest
    processed_pixels_sha256: HexDigest
    image_sha256: HexDigest
    operations: list[NoiseOperation]
    encoding: Literal["PNG", "JPEG-quality-95"]
    environment: dict[str, str]

    @property
    def transform_matrix(self) -> list[list[float]]:
        import numpy as np

        cumulative = np.eye(3, dtype=float)
        for operation in self.operations:
            if operation.name == "random_affine":
                matrix = np.eye(3, dtype=float)
                matrix[:2] = operation.parameters["matrix"]
                cumulative = matrix @ cumulative
        return cumulative[:2].tolist()

    @model_validator(mode="after")
    def validate_seed_and_profile(self) -> "NoiseGeneration":
        expected = derive_seed(self.master_seed, NOISE_PIPELINE_VERSION, self.raster_sha256,
                               self.source_page_number, self.dpi, self.profile, self.variant)
        if expected != self.artifact_seed:
            raise ValueError("Artifact seed does not match its recorded identity")
        if [operation.name for operation in self.operations] != PROFILE_OPERATIONS[self.profile]:
            raise ValueError("Recorded operations do not match the versioned noise profile")
        occurrences: dict[str, int] = {}
        for operation in self.operations:
            occurrence = occurrences.get(operation.name, 0)
            occurrences[operation.name] = occurrence + 1
            if operation.seed != derive_seed(self.artifact_seed, operation.name, occurrence):
                raise ValueError("Operation seed does not match its recorded identity")
        if self.profile == "clean":
            if self.variant != 0 or self.encoding != "PNG" or self.processed_pixels_sha256 != self.raster_sha256:
                raise ValueError("Clean control must be a single lossless, unmodified raster")
        elif self.encoding != "JPEG-quality-95":
            raise ValueError("Noisy scans must record their final JPEG encoding")
        return self


def scan_image_path(gt_path: str | Path) -> Path:
    """Resolve the paired PNG/JPEG without guessing between stale duplicates."""
    gt_path = Path(gt_path)
    stem = gt_path.name.removesuffix("_gt.json")
    candidates = [gt_path.with_name(stem + suffix) for suffix in (".jpg", ".png")]
    existing = [path for path in candidates if path.is_file()]
    if not existing:
        raise FileNotFoundError(f"Paired scan is missing for {gt_path}")
    if len(existing) != 1:
        raise ValueError(f"Ambiguous PNG/JPEG scan pair for {gt_path}")
    return existing[0]
