"""Frozen one-factor noise sweeps with page-paired controls and complete cohorts."""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, model_serializer

from polydocbench.eval.quality import aggregate_ocr_counts
from polydocbench.eval.contract import FrozenEvaluation
from polydocbench.noise import NoiseRecipeConfig, NoiseStep
from polydocbench.noise.provenance import PARAMETER_MODELS, derive_seed
from polydocbench.provenance import json_sha256
from .manifest import DatasetManifest
from .pilot import base_page_key


SWEEP_PARAMETERS = {"defocus_blur": "sigma_pixels", "motion_blur": "length_pixels", "sensor_noise": "sigma",
                    "faded_ink": "retained_contrast", "local_shadow": "strength", "bleed_through": "opacity"}


class CalibrationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class NoiseSweep(CalibrationModel):
    operation: Literal["defocus_blur", "motion_blur", "sensor_noise", "faded_ink", "local_shadow", "bleed_through"]
    parameter: str
    levels: list[float | int] = Field(min_length=2, max_length=7)
    fixed_parameters: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_sweep(self) -> "NoiseSweep":
        if self.parameter != SWEEP_PARAMETERS[self.operation]:
            raise ValueError("Unsupported parameter for this controlled noise sweep")
        model = PARAMETER_MODELS[self.operation]
        expected = set(model.model_fields) - {self.parameter}
        if self.operation == "sensor_noise":
            expected.remove("noise_seed")
        if set(self.fixed_parameters) != expected:
            raise ValueError("Fix every non-swept parameter; sensor noise_seed is assigned per page/repeat")
        ordered = sorted(set(self.levels), reverse=self.operation == "faded_ink")
        if self.levels != ordered:
            raise ValueError("Levels must be unique and ordered by increasing nominal impairment")
        for level in self.levels:
            values = {**self.fixed_parameters, self.parameter: level}
            if self.operation == "sensor_noise":
                values["noise_seed"] = "0" * 64
            model.model_validate(values)
        return self


class CalibrationSpec(CalibrationModel):
    schema_version: Literal["0.1"] = "0.1"
    noise_pipeline_version: Literal["0.3"] = "0.3"
    evaluation_protocol_version: Literal["0.2", "0.3"] = "0.2"
    evaluation_contract: FrozenEvaluation | None = None
    dpi: int = Field(default=200, ge=36, le=600, strict=True)
    repeats: int = Field(default=3, ge=1, le=20, strict=True)
    seed: int = Field(default=42, ge=0, strict=True)
    sweeps: list[NoiseSweep] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_operations(self) -> "CalibrationSpec":
        if (self.evaluation_protocol_version == "0.3") != (self.evaluation_contract is not None):
            raise ValueError("Protocol 0.3 requires a frozen evaluation contract; legacy 0.2 must not declare one")
        names = [sweep.operation for sweep in self.sweeps]
        if len(names) != len(set(names)):
            raise ValueError("Each operation may have only one sweep")
        return self

    @model_serializer(mode="wrap")
    def preserve_legacy_serialization(self, handler):
        result = handler(self)
        if self.evaluation_contract is None:
            result.pop("evaluation_contract", None)
        return result

    def conditions(self) -> list[dict]:
        return [{"profile": f"cal_{sweep.operation}_l{level_index}_r{repeat}",
                 "operation": sweep.operation, "parameter": sweep.parameter, "value": value,
                 "level": level_index, "repeat": repeat}
                for sweep in self.sweeps for level_index, value in enumerate(sweep.levels, 1)
                for repeat in range(self.repeats if sweep.operation == "sensor_noise" else 1)]

    def recipes(self, page_id: str) -> NoiseRecipeConfig:
        sweeps = {sweep.operation: sweep for sweep in self.sweeps}
        profiles = {}
        for condition in self.conditions():
            values = {**sweeps[condition["operation"]].fixed_parameters,
                      condition["parameter"]: condition["value"]}
            if condition["operation"] == "sensor_noise":
                # Same standard-normal field at every sigma; independent across pages/repeats.
                values["noise_seed"] = derive_seed(self.seed, "calibration-sensor-v1", page_id, condition["repeat"])
            profiles[condition["profile"]] = [NoiseStep(name=condition["operation"], parameters=values)]
        return NoiseRecipeConfig(profiles=profiles)


class CalibrationPlan(CalibrationModel):
    schema_version: Literal["0.1"] = "0.1"
    plan_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_algorithm: Literal["language_template_cycle_v1"] = "language_template_cycle_v1"
    inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    split: Literal["dev", "unassigned"]
    spec: CalibrationSpec
    selection: DatasetManifest

    @model_validator(mode="after")
    def validate_plan(self) -> "CalibrationPlan":
        if self.plan_id != json_sha256(self.model_dump(exclude={"plan_id"})):
            raise ValueError("Calibration plan seal differs from its settings/selection")
        records = self.selection.records
        if not records or self.selection.issues or any(r.split != self.split for r in records):
            raise ValueError("Calibration needs a nonempty, issue-free dev/unassigned selection")
        keys = [base_page_key(record) for record in records]
        if len(keys) != len(set(keys)):
            raise ValueError("Calibration selection must contain one representative per base page")
        return self


def calibration_page_id(record) -> str:
    return json_sha256({"source": record.source.sha256, "pdf": record.pdf.sha256, "pdf_gt": record.pdf_gt.sha256,
                        "language": record.language, "article": record.article_id,
                        "template": record.template, "page": record.source_page_number})


def prepare_calibration(manifest: DatasetManifest, spec: CalibrationSpec, *, base_pages: int = 12,
                        split: Literal["dev", "unassigned"] = "dev", languages: list[str] | None = None) -> CalibrationPlan:
    if manifest.issues or base_pages < 1:
        raise ValueError("Resolve inventory issues and request a positive number of base pages")
    candidates = {}
    for record in sorted(manifest.records, key=lambda r: r.artifact_id):
        if record.split == split and (languages is None or record.language in languages):
            candidates.setdefault(base_page_key(record), record)
    observed_languages = {record.language for record in candidates.values()}
    if languages and set(languages) - observed_languages:
        raise ValueError("Requested languages have no eligible source pages in this split")
    if len(candidates) < base_pages:
        raise ValueError(f"Requested {base_pages} pages; only {len(candidates)} eligible for split={split}")
    grouped = defaultdict(lambda: defaultdict(list))
    for record in candidates.values():
        grouped[record.language][record.template].append(record)
    for templates in grouped.values():
        for records in templates.values():
            records.sort(key=lambda r: json_sha256({"seed": spec.seed, "page": calibration_page_id(r)}))
    chosen = []
    cursors = {language: index for index, language in enumerate(sorted(grouped))}
    while len(chosen) < base_pages:
        for language in sorted(grouped):
            templates = sorted(grouped[language])
            for _ in templates:
                template = templates[cursors[language] % len(templates)]
                cursors[language] += 1
                if grouped[language][template]:
                    chosen.append(grouped[language][template].pop(0))
                    break
            if len(chosen) == base_pages:
                break
    selection = DatasetManifest(discovered_count=len(chosen), records=chosen, issues=[], split_plan=manifest.split_plan)
    inventory = manifest.model_dump()
    inventory["records"] = sorted(inventory["records"], key=lambda row: row["artifact_id"])
    payload = {"schema_version": "0.1", "selection_algorithm": "language_template_cycle_v1",
               "inventory_sha256": json_sha256(inventory), "split": split,
               "spec": spec.model_dump(), "selection": selection.model_dump()}
    return CalibrationPlan(plan_id=json_sha256(payload), **payload)


def summarize_calibration(plan: CalibrationPlan, rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Curves use the same complete page cohort across all levels/repeats of an effect."""
    page_records = {calibration_page_id(record): record for record in plan.selection.records}
    profiles = {condition["profile"]: condition for condition in plan.spec.conditions()}
    indexed = {}
    for row in rows:
        key = (row["base_page_id"], row["profile"])
        if key in indexed or key[0] not in page_records or (key[1] != "clean" and key[1] not in profiles):
            raise ValueError("Duplicate or foreign calibration result")
        if row.get("status") == "success":
            metrics = row.get("metrics") or {}
            if metrics.get("evaluation_protocol_version") != plan.spec.evaluation_protocol_version or metrics.get("gt_char_count", 0) < 1:
                raise ValueError("Successful calibration rows require the declared protocol and nonempty GT")
            contract = plan.spec.evaluation_contract
            if contract and (metrics.get("evaluation_contract_id") != contract.contract_id
                             or metrics.get("scope_policy_id") != contract.visibility_policy_id
                             or metrics.get("scope_task") != "quality"
                             or metrics.get("matching_iou_threshold") != contract.settings.quality_iou):
                raise ValueError("Calibration metrics differ from the frozen evaluation contract")
        indexed[key] = row
    pairs = []
    for page_id, record in page_records.items():
        clean = indexed.get((page_id, "clean"), {"status": "not_run", "metrics": None})
        for profile, condition in profiles.items():
            noisy = indexed.get((page_id, profile), {"status": "not_run", "metrics": None})
            valid = clean["status"] == noisy["status"] == "success"
            if valid and any(clean["metrics"][key] != noisy["metrics"][key]
                             for key in ("gt_char_count", "gt_word_count", "num_gt_lines")):
                raise ValueError("Noisy and clean rows do not use the same GT denominator")
            pair = {"base_page_id": page_id, "language": record.language, "source_family": record.source_family,
                    "article_id": record.article_id, "template": record.template, **condition,
                    "clean_status": clean["status"], "noisy_status": noisy["status"], "paired": valid,
                    "clean_metrics": clean.get("metrics"), "noisy_metrics": noisy.get("metrics")}
            pairs.append(pair)
    summaries = []
    scopes = [("overall", "all"), *[("language", v) for v in sorted({r.language for r in page_records.values()})],
              *[("template", v) for v in sorted({r.template for r in page_records.values()})]]
    for dimension, group in scopes:
        for sweep in plan.spec.sweeps:
            scoped = [pair for pair in pairs if pair["operation"] == sweep.operation
                      and (dimension == "overall" or pair[dimension] == group)]
            complete = {page_id for page_id in {p["base_page_id"] for p in scoped}
                        if all(p["paired"] for p in scoped if p["base_page_id"] == page_id)}
            for level, value in enumerate(sweep.levels, 1):
                attempted = [p for p in scoped if p["level"] == level]
                valid = [p for p in attempted if p["base_page_id"] in complete]
                clean = aggregate_ocr_counts([p["clean_metrics"] for p in valid])
                noisy = aggregate_ocr_counts([p["noisy_metrics"] for p in valid])
                summary = {"dimension": dimension, "group": group, "operation": sweep.operation,
                           "parameter": sweep.parameter, "level": level, "value": value,
                           "expected_pairs": len(attempted), "available_pairs": sum(p["paired"] for p in attempted),
                           "curve_pairs": len(valid), "complete_base_pages": len(complete),
                           "selected_base_pages": len({p["base_page_id"] for p in scoped}),
                           "source_families": len({p["source_family"] for p in valid})}
                if plan.spec.evaluation_contract:
                    from polydocbench.eval.scoped import scope_summary

                    summary.update(evaluation_protocol_version="0.3", evaluation_contract_id=plan.spec.evaluation_contract.contract_id)
                    for label in ("clean", "noisy"):
                        summary.update({f"{label}_{key}": value for key, value in
                                        scope_summary([p[f"{label}_metrics"] for p in valid]).items()})
                for key in ("char_errors", "word_errors", "gt_char_count", "gt_word_count",
                            "num_gt_lines", "num_predicted_lines", "num_matched_lines"):
                    summary[f"clean_{key}"] = clean.get(key)
                    summary[f"noisy_{key}"] = noisy.get(key)
                for metric in ("micro_CER", "micro_WER", "line_precision", "line_recall", "line_F1"):
                    summary[f"clean_{metric}"] = clean[metric]
                    summary[f"noisy_{metric}"] = noisy[metric]
                    summary[f"delta_{metric}"] = (noisy[metric] - clean[metric]
                                                    if noisy[metric] is not None and clean[metric] is not None else None)
                summaries.append(summary)
    return summaries, pairs
