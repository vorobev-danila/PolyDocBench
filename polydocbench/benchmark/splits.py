"""Reviewed source-family catalogs and deterministic family-level splits."""

from __future__ import annotations

import hashlib
from datetime import datetime
from math import ceil
from typing import Any, Literal
from urllib.parse import quote, unquote, urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator

from polydocbench.provenance import json_sha256


class SplitModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SourceMember(SplitModel):
    language: str
    article_id: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_url: str
    source_snapshot_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    page_id: int | None = Field(default=None, gt=0)
    wikidata_item_id: str | None = Field(default=None, pattern=r"^Q[1-9][0-9]*$")

    @property
    def source_key(self) -> tuple[str, str, str]:
        return self.language, self.article_id, self.source_sha256


class SourceFamily(SplitModel):
    family_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    members: list[SourceMember] = Field(min_length=1)


class SourceFamilyCatalog(SplitModel):
    schema_version: Literal["0.1"] = "0.1"
    review_status: Literal["draft", "reviewed"] = "draft"
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    families: list[SourceFamily] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_catalog(self) -> "SourceFamilyCatalog":
        if self.review_status == "reviewed":
            if not self.reviewed_by or not self.reviewed_at:
                raise ValueError("Reviewed catalogs require reviewed_by and reviewed_at")
            if datetime.fromisoformat(self.reviewed_at.replace("Z", "+00:00")).tzinfo is None:
                raise ValueError("reviewed_at must include a timezone")
        elif self.reviewed_by is not None or self.reviewed_at is not None:
            raise ValueError("Draft catalogs cannot claim reviewer metadata")
        family_ids = [family.family_id for family in self.families]
        if len(family_ids) != len(set(family_ids)):
            raise ValueError("Duplicate family IDs")
        ownership: dict[tuple[str, str], str] = {}
        member_keys = set()
        for family in self.families:
            for member in family.members:
                if member.source_key in member_keys:
                    raise ValueError("A source member is listed more than once")
                member_keys.add(member.source_key)
                signals = {
                    ("article_id", member.article_id),
                    ("sha256", member.source_sha256),
                    ("url", _normalise_url(member.canonical_url)),
                }
                if member.page_id is not None:
                    signals.add(("page", f"{member.language}:{member.page_id}"))
                if member.wikidata_item_id is not None:
                    signals.add(("wikidata", member.wikidata_item_id))
                for signal in signals:
                    previous = ownership.setdefault(signal, family.family_id)
                    if previous != family.family_id:
                        raise ValueError(f"Related sources cross families via {signal[0]}={signal[1]}")
        return self


class FamilyAssignment(SplitModel):
    family_id: str
    split: Literal["dev", "test"]


class SplitPlan(SplitModel):
    schema_version: Literal["0.1"] = "0.1"
    plan_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    algorithm: Literal["family_hash_v1"] = "family_hash_v1"
    seed: int = Field(ge=0, strict=True)
    development_fraction: float = Field(gt=0, lt=1)
    catalog: SourceFamilyCatalog
    assignments: list[FamilyAssignment]

    @model_validator(mode="after")
    def validate_plan(self) -> "SplitPlan":
        if self.catalog.review_status != "reviewed":
            raise ValueError("A split plan can only be frozen from a reviewed family catalog")
        expected = _assignments(self.catalog, self.seed, self.development_fraction)
        if self.assignments != expected:
            raise ValueError("Split assignments do not match the declared deterministic algorithm")
        if self.plan_id != json_sha256(self.model_dump(exclude={"plan_id"})):
            raise ValueError("Split plan ID does not match its reviewed catalog and assignments")
        return self


def draft_source_catalog(manifest: Any) -> SourceFamilyCatalog:
    """Create an explicitly unreviewed catalog candidate from an artifact inventory."""
    unique = {}
    for record in manifest.records:
        key = (record.language, record.article_id, record.source.sha256)
        unique[key] = SourceMember(
            language=record.language,
            article_id=record.article_id,
            source_sha256=record.source.sha256,
            canonical_url=record.source_url,
            source_snapshot_id=record.source_snapshot_id,
            page_id=record.source_page_id,
            wikidata_item_id=record.wikidata_item_id,
        )
    groups: dict[str, list[SourceMember]] = {}
    for member in unique.values():
        groups.setdefault(member.article_id, []).append(member)
    families = [
        SourceFamily(family_id=family_id, members=sorted(members, key=lambda item: item.source_key))
        for family_id, members in sorted(groups.items())
    ]
    return SourceFamilyCatalog(families=families)


def freeze_split_plan(catalog: SourceFamilyCatalog, *, seed: int = 42,
                      development_fraction: float = 0.2) -> SplitPlan:
    if catalog.review_status != "reviewed":
        raise ValueError("Review the source-family catalog before freezing a split")
    assignments = _assignments(catalog, seed, development_fraction)
    payload = {
        "schema_version": "0.1",
        "algorithm": "family_hash_v1",
        "seed": seed,
        "development_fraction": development_fraction,
        "catalog": catalog.model_dump(),
        "assignments": [assignment.model_dump() for assignment in assignments],
    }
    return SplitPlan(plan_id=json_sha256(payload), **payload)


def apply_split_plan(manifest: Any, plan: SplitPlan):
    """Return a copied manifest with family-level assignments; artifact IDs stay unchanged."""
    from .manifest import DatasetManifest

    by_source = {
        member.source_key: (family.family_id, assignment.split)
        for family in plan.catalog.families
        for member in family.members
        for assignment in plan.assignments
        if assignment.family_id == family.family_id
    }
    records = []
    for record in manifest.records:
        key = (record.language, record.article_id, record.source.sha256)
        if key not in by_source:
            raise ValueError(f"Split plan does not cover source {record.language}/{record.article_id}")
        family_id, split = by_source[key]
        gaps = [gap for gap in record.provenance_gaps
                if gap not in {"source_family_not_reviewed", "split_not_assigned"}]
        records.append(record.model_copy(update={
            "source_family": family_id,
            "family_assignment": "reviewed_catalog",
            "split": split,
            "provenance_gaps": gaps,
        }))
    return DatasetManifest(
        discovered_count=manifest.discovered_count,
        records=records,
        issues=manifest.issues,
        split_plan=plan,
    )


def _assignments(catalog: SourceFamilyCatalog, seed: int, fraction: float) -> list[FamilyAssignment]:
    family_ids = [family.family_id for family in catalog.families]
    if len(family_ids) < 2:
        raise ValueError("At least two reviewed source families are required for dev/test splitting")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    if not 0 < fraction < 1:
        raise ValueError("development_fraction must be between zero and one")
    ranked = sorted(family_ids, key=lambda value: hashlib.sha256(f"{seed}:{value}".encode()).hexdigest())
    dev_count = min(len(ranked) - 1, max(1, ceil(len(ranked) * fraction)))
    development = set(ranked[:dev_count])
    return [FamilyAssignment(family_id=family_id, split="dev" if family_id in development else "test")
            for family_id in sorted(family_ids)]


def _normalise_url(value: str) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    path = parsed.path
    if path.startswith("/wiki/"):
        title = unquote(path[len("/wiki/"):]).replace(" ", "_")
        path = "/wiki/" + quote(title, safe="(),_")
    return f"{parsed.scheme.lower()}://{host}{path}"


__all__ = [
    "FamilyAssignment", "SourceFamily", "SourceFamilyCatalog", "SourceMember", "SplitPlan",
    "apply_split_plan", "draft_source_catalog", "freeze_split_plan",
]
