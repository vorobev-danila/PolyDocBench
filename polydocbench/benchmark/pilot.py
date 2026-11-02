"""Freeze paired pilot samples before inspecting model scores."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from polydocbench.provenance import json_sha256
from .manifest import DatasetManifest, ManifestRecord


def base_page_key(record: ManifestRecord) -> tuple:
    return (record.language, record.article_id, record.source.sha256,
            record.template, record.source_page_number)


class PilotPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    schema_version: Literal["0.1"] = "0.1"
    plan_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_algorithm: Literal["paired_strata_round_robin_v1"] = "paired_strata_round_robin_v1"
    inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: int = Field(ge=0, strict=True)
    split: Literal["dev", "unassigned"]
    profiles: list[str] = Field(min_length=1)
    variant: int = Field(ge=0, strict=True)
    requested_base_pages: int = Field(gt=0, strict=True)
    eligible_base_pages: int = Field(gt=0)
    incomplete_base_pages: int = Field(ge=0)
    selection: DatasetManifest

    @model_validator(mode="after")
    def validate_plan(self) -> "PilotPlan":
        if self.plan_id != json_sha256(self.model_dump(exclude={"plan_id"})):
            raise ValueError("Pilot plan seal differs from its selection/settings")
        if self.selection.issues or not self.selection.records:
            raise ValueError("Pilot selection must be nonempty and contain no rejected records")
        if self.profiles != sorted(set(self.profiles)):
            raise ValueError("Pilot profiles must be unique and sorted")
        groups = defaultdict(list)
        for record in self.selection.records:
            if record.split != self.split or record.variant != self.variant:
                raise ValueError("Pilot artifact split/variant differs from selection settings")
            groups[base_page_key(record)].append(record.profile)
        if len(groups) != self.requested_base_pages or self.eligible_base_pages < len(groups):
            raise ValueError("Pilot page counts differ from the paired selection")
        if any(sorted(profiles) != self.profiles for profiles in groups.values()):
            raise ValueError("Every selected base page must contain exactly the requested profiles")
        return self

    def summary(self) -> dict:
        records = self.selection.records
        return {
            "plan_id": self.plan_id, "split": self.split,
            "base_pages": self.requested_base_pages, "images": len(records),
            "source_documents": len({(r.language, r.article_id, r.source.sha256) for r in records}),
            "source_families": len({r.source_family for r in records}),
            "eligible_base_pages": self.eligible_base_pages,
            "incomplete_base_pages": self.incomplete_base_pages,
            "languages": dict(sorted(Counter(r.language for r in records).items())),
            "templates": dict(sorted(Counter(r.template for r in records).items())),
            "profiles": dict(sorted(Counter(r.profile for r in records).items())),
            "provenance_gaps": dict(sorted(Counter(g for r in records for g in r.provenance_gaps).items())),
        }


def prepare_pilot(manifest: DatasetManifest, *, base_pages: int = 18, seed: int = 42,
                  profiles: list[str] | None = None, variant: int = 0,
                  split: Literal["dev", "unassigned"] = "dev") -> PilotPlan:
    """Balance language/template strata, retaining complete noise-condition pairs."""
    if manifest.issues:
        raise ValueError("Resolve rejected inventory records before preparing a pilot")
    if base_pages < 1 or seed < 0 or variant < 0:
        raise ValueError("base_pages must be positive; seed and variant must be non-negative")
    profiles = sorted(set(profiles if profiles is not None else ["clean", "light_scan", "medium_scan", "heavy_scan"]))
    if not profiles or any(not profile for profile in profiles):
        raise ValueError("Select at least one nonempty profile")
    groups = defaultdict(list)
    for record in manifest.records:
        if record.split == split and record.variant == variant and record.profile in profiles:
            groups[base_page_key(record)].append(record)
    complete = {key: items for key, items in groups.items() if sorted(r.profile for r in items) == profiles}
    if len(complete) < base_pages:
        raise ValueError(f"Requested {base_pages} paired base pages; only {len(complete)} available "
                         f"for split={split}, profiles={profiles}. Missing conditions are never silently dropped.")

    strata = defaultdict(list)
    for key in complete:
        strata[(key[0], key[3])].append(key)
    for keys in strata.values():
        keys.sort(key=lambda key: json_sha256({"seed": seed, "base_page": key}))
    chosen = []
    while len(chosen) < base_pages:
        for stratum in sorted(strata):
            if strata[stratum] and len(chosen) < base_pages:
                chosen.append(strata[stratum].pop(0))
    records = [record for key in chosen for record in sorted(complete[key], key=lambda r: r.profile)]
    selection = DatasetManifest(discovered_count=len(records), records=records, issues=[], split_plan=manifest.split_plan)
    inventory = manifest.model_dump()
    inventory["records"] = sorted(inventory["records"], key=lambda item: item["artifact_id"])
    payload = {
        "schema_version": "0.1", "selection_algorithm": "paired_strata_round_robin_v1",
        "inventory_sha256": json_sha256(inventory), "seed": seed, "split": split,
        "profiles": profiles, "variant": variant, "requested_base_pages": base_pages,
        "eligible_base_pages": len(complete), "incomplete_base_pages": len(groups) - len(complete),
        "selection": selection.model_dump(),
    }
    return PilotPlan(plan_id=json_sha256(payload), **payload)
