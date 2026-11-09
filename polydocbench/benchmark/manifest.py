"""Content-addressed inventory of the existing experiment artifact tree.

An inventory records observable evidence, not a claim of reproducible generation.
Historical settings cannot be recovered from the currently installed generator.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from polydocbench.document.schema import validate_source_document
from polydocbench.gt.schema import validate_gt_document
from polydocbench.noise.provenance import NoiseGeneration, scan_image_path
from polydocbench.sources.snapshots import PROVENANCE_NAME as SOURCE_PROVENANCE_NAME, verify_wikipedia_source
from polydocbench.sources.derived import PROVENANCE_NAME as DERIVED_PROVENANCE_NAME, verify_derived_source
from .files import FileFingerprint, fingerprint_file as _fingerprint, json_sha256 as _digest
from .render_snapshot import PROVENANCE_NAME, verify_render_snapshot
from .splits import SplitPlan


class ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ManifestRecord(ManifestModel):
    artifact_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    language: str
    article_id: str
    source_family: str
    family_assignment: Literal["inferred_from_article_id", "reviewed_catalog"] = "inferred_from_article_id"
    split: Literal["unassigned", "dev", "test"] = "unassigned"
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
    render_snapshot_id: str | None = None
    source_snapshot_id: str | None = None
    source_page_id: int | None = None
    source_revision_id: int | None = None
    wikidata_item_id: str | None = None
    provenance_files: list[FileFingerprint] = Field(default_factory=list)
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
        payload = {
            "language": self.language, "article_id": self.article_id, "template": self.template,
            "page": self.source_page_number, "profile": self.profile, "variant": self.variant,
            "files": {name: getattr(self, name).sha256 for name in FILE_FIELDS},
        }
        if self.provenance_files:
            payload["provenance_files"] = {file.path: file.sha256 for file in self.provenance_files}
        return payload

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
    split_plan: SplitPlan | None = None

    @model_validator(mode="after")
    def check_counts_and_ids(self) -> "DatasetManifest":
        if self.discovered_count != len(self.records) + len(self.issues):
            raise ValueError("Discovery count must include accepted and rejected artifacts")
        identifiers = [record.artifact_id for record in self.records]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Duplicate artifact IDs")
        if self.split_plan is None:
            if any(record.split != "unassigned" or record.family_assignment != "inferred_from_article_id"
                   for record in self.records):
                raise ValueError("Reviewed family/split assignments require an embedded split plan")
        else:
            expected = {
                (member.language, member.article_id, member.source_sha256): (family.family_id, assignment.split)
                for family in self.split_plan.catalog.families
                for member in family.members
                for assignment in self.split_plan.assignments
                if assignment.family_id == family.family_id
            }
            for record in self.records:
                actual = expected.get((record.language, record.article_id, record.source.sha256))
                if actual != (record.source_family, record.split) or record.family_assignment != "reviewed_catalog":
                    raise ValueError("Manifest records do not match the embedded split plan")
        return self

    def summary(self) -> dict:
        return {
            "kind": self.kind,
            "generation_reproducibility": self.generation_reproducibility,
            "discovered": self.discovered_count, "accepted": len(self.records), "rejected": len(self.issues),
            "sources": len({record.source.path for record in self.records}),
            "render_snapshots": len({record.render_snapshot_id for record in self.records if record.render_snapshot_id}),
            "source_snapshots": len({record.source_snapshot_id for record in self.records if record.source_snapshot_id}),
            "split_plan_id": self.split_plan.plan_id if self.split_plan else None,
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


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path.name}")
    return value


def _record(root: Path, gt_path: Path, fingerprint_cache: dict[Path, FileFingerprint], render_cache: dict) -> ManifestRecord:
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
    provenance_files, render_snapshot_id = [], None
    source_snapshot_id = source_page_id = source_revision_id = wikidata_item_id = None
    source_provenance_path = case_dir / SOURCE_PROVENANCE_NAME
    declares_source_snapshot = bool(source_data.get("metadata", {}).get("wikipedia_snapshot_id"))
    if source_provenance_path.exists() or declares_source_snapshot:
        source_evidence = verify_wikipedia_source(case_dir)
        if source_evidence.source.sha256 != files["source"].sha256:
            raise ValueError("Wikipedia provenance does not match source.json")
        source_snapshot_id = source_evidence.inputs.snapshot_id
        source_page_id = source_evidence.inputs.page_id
        source_revision_id = source_evidence.inputs.revision_id
        wikidata_item_id = source_evidence.inputs.wikidata_item_id
        source_paths = [source_provenance_path]
        source_paths.extend(case_dir / item.path for item in (
            source_evidence.inputs.query_response,
            source_evidence.inputs.parse_response,
            source_evidence.inputs.html,
        ))
        provenance_files.extend(_fingerprint(root, path) for path in source_paths)
        gaps.remove("source_revision_not_verified")
    elif (case_dir / DERIVED_PROVENANCE_NAME).exists() or source_data.get("metadata", {}).get("derived_source_id"):
        derived = verify_derived_source(case_dir)
        parent = verify_wikipedia_source(case_dir / "origin")
        source_snapshot_id = derived.parent_snapshot_id
        source_page_id, source_revision_id = parent.inputs.page_id, parent.inputs.revision_id
        wikidata_item_id = parent.inputs.wikidata_item_id
        provenance_files.extend(_fingerprint(root, case_dir / path)
                                for path in [DERIVED_PROVENANCE_NAME, *[f.path for f in derived.files]])
        gaps.remove("source_revision_not_verified")
        gaps.append("controlled_composition_not_full_article")
    if (template_dir / PROVENANCE_NAME).exists():
        if template_dir not in render_cache:
            evidence = verify_render_snapshot(template_dir)
            paths = [template_dir / PROVENANCE_NAME, template_dir / "render_inputs.json"]
            paths.extend(template_dir / file.path for file in evidence.inputs.files)
            render_cache[template_dir] = (evidence, [_fingerprint(root, path) for path in paths])
        evidence, render_files = render_cache[template_dir]
        provenance_files.extend(render_files)
        original_source = next(file for file in evidence.inputs.files if file.role == "original_source")
        if (original_source.sha256 != files["source"].sha256 or evidence.pdf.sha256 != files["pdf"].sha256
                or evidence.gt.sha256 != files["pdf_gt"].sha256):
            raise ValueError("Render provenance does not match the source/PDF/GT chain")
        render_snapshot_id = evidence.inputs.snapshot_id
        gaps.remove("render_configuration_not_snapshotted")
        gaps.remove("font_and_asset_provenance_not_recorded")
        gaps.append("font_and_asset_rights_not_verified")
        if evidence.inputs.generator_revision is not None:
            gaps.remove("generator_revision_not_recorded")
        if generation is not None:
            gaps.remove("generation_environment_not_recorded")
    elif pdf_gt.metadata.get("render_snapshot_id"):
        raise ValueError("PDF GT declares an input snapshot but its provenance file is missing")
    if not source_data.get("schema_version"):
        gaps.append("source_schema_version_not_declared")
    if not image_gt.get("schema_version"):
        gaps.append("gt_schema_version_not_declared")
    if provenance_files:
        payload["provenance_files"] = {file.path: file.sha256 for file in provenance_files}
    return ManifestRecord(
        artifact_id=_digest(payload), language=language, article_id=article_id,
        source_family=article_id, template=template, source_page_number=page_number,
        profile=profile, variant=variant, source_url=source.url,
        source_schema_version=source_data.get("schema_version"), gt_schema_version=image_gt.get("schema_version"),
        **files, width=width, height=height, dpi=metadata.get("dpi"),
        transform_matrix=transform.get("matrix"), noise_generation=generation,
        render_snapshot_id=render_snapshot_id, provenance_files=provenance_files, provenance_gaps=gaps,
        source_snapshot_id=source_snapshot_id, source_page_id=source_page_id,
        source_revision_id=source_revision_id, wikidata_item_id=wikidata_item_id,
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
    render_cache = {}
    identifiers = set()
    for gt_path in sorted(root.glob("*/*/*/noisy/page_*/*_gt.json")):
        parts = gt_path.relative_to(root).parts
        if (languages and parts[0] not in languages) or (templates and parts[2] not in templates):
            continue
        try:
            record = _record(root, gt_path, cache, render_cache)
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
        for expected in [getattr(record, name) for name in FILE_FIELDS] + record.provenance_files:
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
