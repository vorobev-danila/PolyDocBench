"""Path-independent seed derivation and validated scan-generation evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationInfo, field_validator, model_validator


NOISE_PIPELINE_VERSION = "0.3"
HexDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PROFILE_OPERATIONS = {
    "clean": [],
    "light_scan": ["reduce_resolution", "illumination_gradient", "jpeg_artifacts"],
    "medium_scan": ["reduce_resolution", "random_affine", "illumination_gradient", "jpeg_artifacts"],
    "heavy_scan": ["reduce_resolution", "random_affine", "illumination_gradient", "ink_morphology", "jpeg_artifacts"],
}
LEGACY_PROFILE_OPERATIONS = {name: list(operations) for name, operations in PROFILE_OPERATIONS.items()}
PROFILE_OPERATIONS.update({
    "defocus_scan": ["defocus_blur"], "motion_scan": ["motion_blur"],
    "sensor_noise": ["sensor_noise"], "faded_print": ["faded_ink"],
    "shadow_scan": ["local_shadow"], "duplex_scan": ["bleed_through"],
    "camera_capture": ["defocus_blur", "motion_blur", "local_shadow", "sensor_noise", "jpeg_artifacts"],
})


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


class _Defocus(_Parameters):
    sigma_pixels: float = Field(ge=0, le=12)


class _Motion(_Parameters):
    length_pixels: int = Field(ge=1, le=101, strict=True)
    angle_degrees: float = Field(ge=-180, le=180)

    @field_validator("length_pixels")
    @classmethod
    def odd_length(cls, value):
        if value % 2 == 0:
            raise ValueError("Motion kernel length must be odd")
        return value


class _Sensor(_Parameters):
    sigma: float = Field(ge=0, le=64)
    noise_seed: HexDigest


class _Faded(_Parameters):
    retained_contrast: float = Field(gt=0, le=1)


class _Shadow(_Parameters):
    strength: float = Field(ge=0, le=0.8)
    center_x: float = Field(ge=0, le=1)
    center_y: float = Field(ge=0, le=1)
    radius_x: float = Field(gt=0, le=2)
    radius_y: float = Field(gt=0, le=2)


class _Bleed(_Parameters):
    opacity: float = Field(ge=0, le=0.45)
    sigma_pixels: float = Field(ge=0, le=12)
    shift_x: int = Field(ge=-4096, le=4096, strict=True)
    shift_y: int = Field(ge=-4096, le=4096, strict=True)
    source: Literal["mirrored_self_page"]


PARAMETER_MODELS = {"reduce_resolution": _Resolution, "illumination_gradient": _Illumination,
                    "random_affine": _Affine, "ink_morphology": _Morphology, "jpeg_artifacts": _Jpeg,
                    "defocus_blur": _Defocus, "motion_blur": _Motion, "sensor_noise": _Sensor,
                    "faded_ink": _Faded, "local_shadow": _Shadow, "bleed_through": _Bleed}
NoiseName = Literal["reduce_resolution", "random_affine", "illumination_gradient", "ink_morphology", "jpeg_artifacts",
                    "defocus_blur", "motion_blur", "sensor_noise", "faded_ink", "local_shadow", "bleed_through"]


class NoiseStep(BaseModel):
    """Recipe step: omitted values are sampled; explicit values are actual units, not ranges."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    name: NoiseName
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("parameters")
    @classmethod
    def validate_overrides(cls, value, info):
        if "name" not in info.data:
            return value
        model = PARAMETER_MODELS[info.data["name"]]
        result = {}
        for name, item in value.items():
            if info.data["name"] == "random_affine" and name == "matrix":
                raise ValueError("Recipes configure affine angle_degrees/shear; the matrix is computed from them")
            if name not in model.model_fields:
                raise ValueError(f"Unknown parameter for {info.data['name']}: {name}")
            field = model.model_fields[name]
            result[name] = TypeAdapter(Annotated[field.annotation, field]).validate_python(item)
        return result


class NoiseRecipeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["0.1"] = "0.1"
    profiles: dict[str, list[NoiseStep]]

    @field_validator("profiles")
    @classmethod
    def validate_profiles(cls, value):
        import re

        if not value:
            raise ValueError("Custom profile configuration must not be empty")
        for name, steps in value.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) or name in PROFILE_OPERATIONS or not steps:
                raise ValueError("Custom profiles need a safe unique name, nonempty steps, and cannot replace built-ins")
        return value


def load_noise_config(path: str | Path) -> NoiseRecipeConfig:
    return NoiseRecipeConfig.model_validate_json(Path(path).read_text(encoding="utf-8"))


class NoiseOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    name: NoiseName
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
    noise_pipeline_version: Literal["0.2", "0.3"]
    seed_derivation: Literal["sha256-json-v1"]
    master_seed: int = Field(ge=0, strict=True)
    artifact_seed: HexDigest
    source_page_number: int = Field(gt=0)
    dpi: int = Field(gt=0)
    profile: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    profile_definition: list[NoiseStep] | None = None
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
        identity = [self.noise_pipeline_version, self.raster_sha256,
                    self.source_page_number, self.dpi, self.profile, self.variant]
        definitions = LEGACY_PROFILE_OPERATIONS if self.noise_pipeline_version == "0.2" else PROFILE_OPERATIONS
        if self.profile_definition is not None:
            if self.noise_pipeline_version != "0.3" or self.profile in PROFILE_OPERATIONS or not self.profile_definition:
                raise ValueError("Only new, named custom profiles may declare recipe steps")
            recipe = [step.model_dump() for step in self.profile_definition]
            identity.append(recipe)
            expected_names = [step.name for step in self.profile_definition]
        elif self.profile in definitions:
            expected_names = definitions[self.profile]
        else:
            raise ValueError("Unknown versioned profile or missing custom recipe definition")
        expected = derive_seed(self.master_seed, *identity)
        if expected != self.artifact_seed:
            raise ValueError("Artifact seed does not match its recorded identity")
        if [operation.name for operation in self.operations] != expected_names:
            raise ValueError("Recorded operations do not match the versioned noise profile")
        if self.profile_definition is not None:
            for step, operation in zip(self.profile_definition, self.operations):
                if any(operation.parameters.get(key) != value for key, value in step.parameters.items()):
                    raise ValueError("Recorded operation differs from its recipe overrides")
        occurrences: dict[str, int] = {}
        for operation in self.operations:
            occurrence = occurrences.get(operation.name, 0)
            occurrences[operation.name] = occurrence + 1
            if operation.seed != derive_seed(self.artifact_seed, operation.name, occurrence):
                raise ValueError("Operation seed does not match its recorded identity")
        if self.profile == "clean":
            if self.variant != 0 or self.encoding != "PNG" or self.processed_pixels_sha256 != self.raster_sha256:
                raise ValueError("Clean control must be a single lossless, unmodified raster")
        elif self.encoding != ("JPEG-quality-95" if self.profile in LEGACY_PROFILE_OPERATIONS else "PNG"):
            raise ValueError("Final encoding does not match the versioned profile")
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
