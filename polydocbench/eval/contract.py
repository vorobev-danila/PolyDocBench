"""Content-addressed evaluation choices; freezing is not scientific approval."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from polydocbench.gt.visibility import geometry_engine
from polydocbench.provenance import FileFingerprint, fingerprint_file, json_sha256
from .scope import VisibilityPolicy

ROOT = Path(__file__).resolve().parents[2]


class EvaluationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)
    schema_version: Literal["0.1"] = "0.1"
    evaluation_protocol_version: Literal["0.3"] = "0.3"
    normalization: Literal["lowercase_collapse_whitespace_preserve_punctuation_accents"] = "lowercase_collapse_whitespace_preserve_punctuation_accents"
    quality_matching: Literal["greedy_one_to_one_bbox_iou"] = "greedy_one_to_one_bbox_iou"
    quality_iou: float = Field(default=0.3, gt=0, le=1)
    structure_matching: Literal["greedy_one_to_one_bbox_iou_with_class_reporting"] = "greedy_one_to_one_bbox_iou_with_class_reporting"
    structure_iou: float = Field(default=0.5, gt=0, le=1)
    ordering_matching: Literal["native_sequence_text_first_contiguous_gt_spans"] = "native_sequence_text_first_contiguous_gt_spans"
    min_similarity: float = Field(default=0.3, gt=0, le=1)
    max_gt_span: int = Field(default=3, ge=1, le=10, strict=True)
    quality_aggregation: Literal["pooled_counts_including_unmatched_insertions"] = "pooled_counts_including_unmatched_insertions"
    undefined_scores: Literal["null_with_coverage_and_failure_counts"] = "null_with_coverage_and_failure_counts"
    visibility_policy: VisibilityPolicy = Field(default_factory=VisibilityPolicy)


class FrozenEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    settings: EvaluationSettings
    implementation_files: list[FileFingerprint]
    geometry_engine: str
    visibility_policy_id: str
    approval_status: Literal["candidate_pending_human_approval"] = "candidate_pending_human_approval"

    @model_validator(mode="after")
    def validate_identity(self):
        if self.contract_id != json_sha256(self.model_dump(exclude={"contract_id"})):
            raise ValueError("Evaluation contract seal differs from its settings/implementation")
        paths = [f.path for f in self.implementation_files]
        if not paths or len(paths) != len(set(paths)):
            raise ValueError("Evaluation contract needs unique implementation files")
        return self

    def verify_runtime(self):
        current = _implementation_files()
        if current != self.implementation_files or self.geometry_engine != geometry_engine():
            raise ValueError("Evaluation implementation/geometry engine differs from the frozen contract")
        if self.visibility_policy_id != self.settings.visibility_policy.policy_id:
            raise ValueError("Visibility identity differs from the frozen evaluation contract")

    def model_config_values(self):
        self.verify_runtime()
        return {key: getattr(self.settings, key) for key in
                ("quality_iou", "structure_iou", "min_similarity", "max_gt_span")} | {
                    "visibility_policy": self.settings.visibility_policy.model_dump(),
                    "evaluation_contract": self.model_dump()}


def _implementation_files():
    paths = sorted([*(ROOT / "polydocbench/eval").glob("*.py"),
                    ROOT / "polydocbench/gt/visibility.py", ROOT / "polydocbench/gt/audit.py"])
    return [fingerprint_file(ROOT, path) for path in paths]


def freeze_evaluation(settings: EvaluationSettings) -> FrozenEvaluation:
    payload = {"settings": settings.model_dump(),
               "implementation_files": [file.model_dump() for file in _implementation_files()],
               "geometry_engine": geometry_engine(), "visibility_policy_id": settings.visibility_policy.policy_id,
               "approval_status": "candidate_pending_human_approval"}
    return FrozenEvaluation(contract_id=json_sha256(payload), **payload)


def load_evaluation_settings(path: str | Path) -> FrozenEvaluation:
    return freeze_evaluation(EvaluationSettings.model_validate_json(Path(path).read_text(encoding="utf-8")))
