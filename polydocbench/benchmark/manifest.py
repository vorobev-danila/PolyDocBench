"""Content-addressed inventory of the existing experiment artifact tree.

An inventory records observable evidence, not a claim of reproducible generation.
Historical settings cannot be recovered from the currently installed generator.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from polydocbench.document.schema import validate_source_document
from polydocbench.gt.schema import validate_gt_document
from polydocbench.noise.provenance import NoiseGeneration, scan_image_path


class ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class FileFingerprint(ManifestModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if not path.parts or path.is_absolute() or ".." in path.parts or "\\" in value or ":" in value:
            raise ValueError("File paths must be relative POSIX paths inside the dataset root")
        return value


class ManifestRecord(ManifestModel):
    artifact_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    language: str
    article_id: str
    source_family: str
    family_assignment: Literal["inferred_from_article_id"] = "inferred_from_article_id"
    split: Literal["unassigned"] = "unassigned"
    template: str
    source_page_number: int = Field(gt=0)
    image_page_number: Literal[1] = 1
    profile: str
    variant: int = Field(ge=0)
    source_url: str
    source_schema_version: str | None
    gt_schema_version: str | None
    source: FileFingerprint
    pdf: FileFingerprint
    pdf_gt: FileFingerprint
    image: FileFingerprint
    image_gt: FileFingerprint
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    dpi: int = Field(gt=0)
    transform_matrix: list[list[float]]
    noise_generation: NoiseGeneration | None = None
    provenance_gaps: list[str]

    @field_validator("transform_matrix")
    @classmethod
    def validate_matrix(cls, value: list[list[float]]) -> list[list[float]]:
        if len(value) != 2 or any(len(row) != 3 for row in value):
            raise ValueError("Expected a 2x3 affine matrix")
        if not all(math.isfinite(number) for row in value for number in row):
            raise ValueError("Affine matrix must contain finite numbers")
        return value

    def identity_payload(self) -> dict:
        return {
            "language": self.language, "article_id": self.article_id, "template": self.template,
            "page": self.source_page_number, "profile": self.profile, "variant": self.variant,
            "files": {name: getattr(self, name).sha256 for name in FILE_FIELDS},
        }

    @model_validator(mode="after")
    def check_identity(self) -> "ManifestRecord":
        if self.artifact_id != _digest(self.identity_payload()):
            raise ValueError("artifact_id does not match record content")
        return self


class InventoryIssue(ManifestModel):
    path: str
    error_type: str
    message: str


class DatasetManifest(ManifestModel):
    manifest_schema_version: Literal["0.1"] = "0.1"
    kind: Literal["artifact_inventory"] = "artifact_inventory"
    generation_reproducibility: Literal["not_established"] = "not_established"
    discovered_count: int = Field(ge=0)
    records: list[ManifestRecord]
    issues: list[InventoryIssue]

    @model_validator(mode="after")
    def check_counts_and_ids(self) -> "DatasetManifest":
        if self.discovered_count != len(self.records) + len(self.issues):
            raise ValueError("Discovery count must include accepted and rejected artifacts")
        identifiers = [record.artifact_id for record in self.records]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Duplicate artifact IDs")
        return self

    def summary(self) -> dict:
        return {
            "kind": self.kind,
            "generation_reproducibility": self.generation_reproducibility,
            "discovered": self.discovered_count, "accepted": len(self.records), "rejected": len(self.issues),
            "sources": len({record.source.path for record in self.records}),
            "inferred_source_families": len({record.source_family for record in self.records}),
            "languages": dict(sorted(Counter(record.language for record in self.records).items())),
            "templates": dict(sorted(Counter(record.template for record in self.records).items())),
            "profiles": dict(sorted(Counter(record.profile for record in self.records).items())),
            "provenance_gaps": dict(sorted(Counter(
                gap for record in self.records for gap in record.provenance_gaps
            ).items())),
            "issues": [issue.model_dump() for issue in self.issues],
        }


FILE_FIELDS = ("source", "pdf", "pdf_gt", "image", "image_gt")
HISTORICAL_PROVENANCE_GAPS = [
    "source_revision_not_verified", "source_family_not_reviewed", "split_not_assigned",
    "generation_seed_not_recorded", "sampled_noise_parameters_not_recorded",
    "generator_revision_not_recorded", "generation_environment_not_recorded",
    "render_configuration_not_snapshotted", "font_and_asset_provenance_not_recorded",
]


def _digest(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _fingerprint(root: Path, path: Path) -> FileFingerprint:
    resolved = path.resolve()
    relative = resolved.relative_to(root)
    digest = hashlib.sha256()
    with resolved.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return FileFingerprint(path=relative.as_posix(), sha256=digest.hexdigest(), size_bytes=resolved.stat().st_size)


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path.name}")
    return value


def _record(root: Path, gt_path: Path, fingerprint_cache: dict[Path, FileFingerprint]) -> ManifestRecord:
    language, article_id, template, _, page_dir, filename = gt_path.relative_to(root).parts
    page_number = int(page_dir.removeprefix("page_"))
    stem = filename.removesuffix("_gt.json")
    profile, _, variant_text = stem.rpartition("_")
    variant = int(variant_text)
    if not profile:
        raise ValueError("Missing noise profile in artifact filename")

    case_dir = root / language / article_id
    template_dir = case_dir / template
    paths = {"source": case_dir / "source.json", "pdf": template_dir / "document.pdf",
             "pdf_gt": template_dir / "document_gt.json", "image_gt": gt_path,
             "image": scan_image_path(gt_path)}
    for path in paths.values():
        path.resolve().relative_to(root)
    source_data = _read_json(paths["source"])
    source = validate_source_document(source_data)
    pdf_gt = validate_gt_document(_read_json(paths["pdf_gt"]))
    if page_number not in {page.page_number for page in pdf_gt.pages}:
        raise ValueError("Source page is absent from document_gt.json")
    image_gt = _read_json(gt_path)
    gt = validate_gt_document(image_gt)
    metadata = gt.metadata
    if metadata.get("profile") != profile or metadata.get("variant") != variant:
        raise ValueError("GT profile/variant does not match the artifact filename")
    coordinates = metadata.get("coordinate_system", {})
    if coordinates.get("unit") != "pixels" or coordinates.get("origin") != "top-left":
        raise ValueError("Image GT must use top-left-origin pixel coordinates")
    with Image.open(paths["image"]) as image:
        image.load()
        width, height = image.size
    declared_sizes = [
        (coordinates.get("image_width"), coordinates.get("image_height")),
        (image_gt.get("image", {}).get("width"), image_gt.get("image", {}).get("height")),
    ]
    if len(gt.pages) != 1 or gt.pages[0].page_number != 1:
        raise ValueError("Image GT must contain exactly one page numbered 1")
    declared_sizes.append((gt.pages[0].width, gt.pages[0].height))
    if any(size != (width, height) for size in declared_sizes):
        raise ValueError("Image dimensions do not match the paired GT")
    transform = metadata.get("transform", {})
    if transform.get("type") != "affine":
        raise ValueError("Expected an explicit affine transform in image GT")

    files = {}
    for name, path in paths.items():
        if path not in fingerprint_cache:
            fingerprint_cache[path] = _fingerprint(root, path)
        files[name] = fingerprint_cache[path]
    payload = {
        "language": language, "article_id": article_id, "template": template,
        "page": page_number, "profile": profile, "variant": variant,
        "files": {name: files[name].sha256 for name in FILE_FIELDS},
    }
    gaps = HISTORICAL_PROVENANCE_GAPS.copy()
    generation = None
    if metadata.get("noise_generation") is not None:
        generation = NoiseGeneration.model_validate(metadata["noise_generation"])
        if (generation.source_pdf_sha256 != files["pdf"].sha256
                or generation.source_gt_sha256 != files["pdf_gt"].sha256
                or generation.image_sha256 != files["image"].sha256):
            raise ValueError("Noise trace fingerprints do not match its PDF/GT/image files")
        if (generation.source_page_number != page_number or generation.profile != profile
                or generation.variant != variant or generation.dpi != metadata.get("dpi")
                or generation.transform_matrix != transform.get("matrix")):
            raise ValueError("Noise trace identity/transform does not match the paired GT")
        gaps.remove("generation_seed_not_recorded")
        gaps.remove("sampled_noise_parameters_not_recorded")
    if not source_data.get("schema_version"):
        gaps.append("source_schema_version_not_declared")
    if not image_gt.get("schema_version"):
        gaps.append("gt_schema_version_not_declared")
    return ManifestRecord(
        artifact_id=_digest(payload), language=language, article_id=article_id,
        source_family=article_id, template=template, source_page_number=page_number,
        profile=profile, variant=variant, source_url=source.url,
        source_schema_version=source_data.get("schema_version"), gt_schema_version=image_gt.get("schema_version"),
        **files, width=width, height=height, dpi=metadata.get("dpi"),
        transform_matrix=transform.get("matrix"), noise_generation=generation, provenance_gaps=gaps,
    )


def build_manifest(
    input_root: str | Path, *, languages: list[str] | None = None, templates: list[str] | None = None,
) -> DatasetManifest:
    """Inventory existing scan/GT pairs without changing their files or guessing settings."""
    root = Path(input_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Dataset root must be a directory")
    records, issues = [], []
    cache: dict[Path, FileFingerprint] = {}
    identifiers = set()
    for gt_path in sorted(root.glob("*/*/*/noisy/page_*/*_gt.json")):
        parts = gt_path.relative_to(root).parts
        if (languages and parts[0] not in languages) or (templates and parts[2] not in templates):
            continue
        try:
            record = _record(root, gt_path, cache)
            if record.artifact_id in identifiers:
                raise ValueError("Duplicate artifact identity in selected inventory")
            identifiers.add(record.artifact_id)
            records.append(record)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            issues.append(InventoryIssue(path=gt_path.relative_to(root).as_posix(),
                                         error_type=type(exc).__name__, message=str(exc)))
    return DatasetManifest(discovered_count=len(records) + len(issues), records=records, issues=issues)


def verify_manifest(manifest: DatasetManifest, input_root: str | Path) -> list[InventoryIssue]:
    """Check all recorded file bytes against their saved fingerprints."""
    root = Path(input_root).resolve(strict=True)
    issues = []
    checked = set()
    for record in manifest.records:
        for name in FILE_FIELDS:
            expected = getattr(record, name)
            key = (expected.path, expected.sha256, expected.size_bytes)
            if key in checked:
                continue
            checked.add(key)
            try:
                actual = _fingerprint(root, root / expected.path)
                if actual != expected:
                    raise ValueError("File SHA-256 or size differs from the manifest")
            except (OSError, ValueError) as exc:
                issues.append(InventoryIssue(path=expected.path, error_type=type(exc).__name__, message=str(exc)))
    return issues
