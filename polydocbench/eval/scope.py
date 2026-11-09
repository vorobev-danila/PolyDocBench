"""Explicit, versioned GT eligibility and conservative ignored-region planning."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from shapely.geometry import GeometryCollection, box
from shapely.ops import unary_union

from polydocbench.gt.audit import audit_gt_document
from polydocbench.gt.visibility import bbox_geometry, geometry_engine, polygon_geometry, visibility_facts
from polydocbench.provenance import json_sha256
from .block_matching import extract_visible_gt_blocks
from .gt import extract_gt_lines
from .structure import extract_gt_structure_elements

Task = Literal["quality", "ordering", "structure", "line_ordering"]


class VisibilityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    schema_version: Literal["0.1"] = "0.1"
    policy_name: str = Field(default="conservative_visibility", pattern=r"^[a-z][a-z0-9_]{0,63}$")
    coordinate_epsilon_pixels: float = Field(default=0.05, ge=0, le=1)
    quality_partial: Literal["exclude"] = "exclude"
    ordering_partial: Literal["exclude_incomplete_blocks"] = "exclude_incomplete_blocks"
    structure_partial: Literal["exclude", "visible"] = "exclude"
    prediction_ignore: Literal["fully_contained_unprotected"] = "fully_contained_unprotected"

    @property
    def policy_id(self):
        return json_sha256({"policy": self.model_dump(), "geometry_engine": geometry_engine()})


class IgnoreRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    tasks: list[Literal["quality", "ordering", "structure"]] = Field(min_length=1)
    polygon: list[list[float]]

    @field_validator("polygon", mode="before")
    @classmethod
    def valid_polygon(cls, value):
        polygon_geometry(value)
        return value


def load_visibility_policy(path: str | Path) -> VisibilityPolicy:
    return VisibilityPolicy.model_validate_json(Path(path).read_text(encoding="utf-8"))


@dataclass
class PreparedScope:
    task: str
    policy: VisibilityPolicy
    gt: list[dict]
    gt_decisions: list[dict]
    regions: list[dict]
    eligible_geometry: object
    ignored_geometry: object
    canvas_area: float
    gt_sha256: str

    def filter_predictions(self, predictions):
        kept, decisions = [], []
        for index, prediction in enumerate(predictions):
            page = prediction.get("page_number")
            if page is not None and page != 1:
                raise ValueError("Visibility scoring expects single-image predictions on page 1")
            geometry = None
            if prediction.get("polygon") is not None:
                geometry = polygon_geometry(prediction["polygon"])
            if prediction.get("bbox") is not None:
                bbox = bbox_geometry(prediction["bbox"])
                geometry = bbox if geometry is None else geometry.union(bbox)
            if geometry is None and self.task != "ordering":
                raise ValueError("Quality/structure predictions require spatial geometry")
            ignored = False
            reason = "no_geometry" if geometry is None else "scorable"
            coverage = 0.0
            if geometry is not None:
                covered = geometry.intersection(self.ignored_geometry).area
                coverage = min(1.0, max(0.0, covered / geometry.area))
                protected = geometry.intersection(self.eligible_geometry).area > 0
                # Do not clip predictions first: off-canvas hallucinations are not free exclusions.
                contained = self.ignored_geometry.covers(geometry)
                if protected and covered > 0:
                    reason = "eligible_gt_overlap"
                elif contained and not protected:
                    ignored, reason = True, "inside_ignore_regions"
            decisions.append({"prediction_index": index, "id": prediction.get("id"), "ignored": ignored,
                              "reason": reason, "ignored_area_fraction": coverage})
            if not ignored:
                kept.append(prediction)
        retained_indices = [r["prediction_index"] for r in decisions if not r["ignored"]]
        excluded = [r for r in self.gt_decisions if not r["eligible"]]
        counts = Counter(r["reason"] for r in excluded)
        total, eligible = len(self.gt_decisions), len(self.gt)
        effective_ignored_area = self.ignored_geometry.difference(self.eligible_geometry).area
        ledger = {"schema_version": "0.1", "task": self.task, "policy": self.policy.model_dump(),
                  "gt_sha256": self.gt_sha256,
                  "policy_id": self.policy.policy_id, "geometry_engine": geometry_engine(),
                  "gt": self.gt_decisions, "predictions": decisions, "ignore_regions": self.regions,
                  "retained_prediction_indices": retained_indices,
                  "effective_ignored_area_pixels": effective_ignored_area,
                  "prediction_sha256": json_sha256({"predictions": predictions})}
        scope_id = json_sha256(ledger)
        ledger["scope_id"] = scope_id
        metrics = {"scope_policy_version": "0.1", "scope_policy_id": self.policy.policy_id, "scope_id": scope_id,
                   "scope_policy_status": "candidate_not_publication_approved", "scope_empty_gt_images": int(not eligible),
                   "scope_unit": "line" if self.task in {"quality", "line_ordering"} else "block" if self.task == "ordering" else "structure_element",
                   "scope_task": self.task, "scope_input_gt": total, "scope_eligible_gt": eligible,
                   "scope_excluded_gt": total - eligible, "scope_eligible_gt_fraction": eligible / total if total else None,
                   "scope_input_predictions": len(predictions), "scope_retained_predictions": len(kept),
                   "scope_ignored_predictions": len(predictions) - len(kept),
                   "scope_unlocalized_predictions": sum(r["reason"] == "no_geometry" for r in decisions),
                   "scope_protected_predictions": sum(r["reason"] == "eligible_gt_overlap" for r in decisions),
                   "scope_ignored_area_fraction": effective_ignored_area / self.canvas_area,
                   "scope_canvas_area_pixels": self.canvas_area, "scope_ignored_area_pixels": effective_ignored_area,
                   "scope_ignore_region_count": len(self.regions),
                   "scope_input_gt_pairs": total * (total - 1) // 2,
                   "scope_eligible_gt_pairs": eligible * (eligible - 1) // 2,
                   "scope_eligible_pair_fraction": eligible * (eligible - 1) / (total * (total - 1)) if total > 1 else None}
        for reason in ("fully_clipped", "partially_clipped", "incomplete_text_block", "manual_region"):
            metrics[f"scope_excluded_{reason}"] = counts[reason]
        return kept, ledger, metrics


def prepare_scope(gt: dict, task: Task, policy: VisibilityPolicy | dict, *, page_number: int = 1) -> PreparedScope:
    if task not in {"quality", "ordering", "structure", "line_ordering"}:
        raise ValueError("Unsupported visibility task")
    policy = VisibilityPolicy.model_validate(policy)
    coordinates = gt.get("metadata", {}).get("coordinate_system", {})
    if (page_number != 1 or len(gt.get("pages", [])) != 1 or gt["pages"][0].get("page_number") != 1 or not isinstance(coordinates, dict)
            or coordinates.get("unit") != "pixels" or coordinates.get("origin") != "top-left"):
        raise ValueError("Visibility policy requires single-image pixel/top-left GT, not PDF coordinates")
    width, height = coordinates.get("image_width"), coordinates.get("image_height")
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (width, height)):
        raise ValueError("Visibility GT requires positive finite image dimensions")
    if (gt["pages"][0]["width"], gt["pages"][0]["height"]) != (width, height):
        raise ValueError("Visibility canvas and GT page dimensions differ")
    audit = audit_gt_document(gt, coordinate_system="image", tolerance=policy.coordinate_epsilon_pixels)
    if not audit.passed:
        finding = next(f for f in audit.findings if f.severity == "error")
        raise ValueError(f"GT audit must pass before visibility scoring: {finding.code}")
    canvas = box(0, 0, width, height)
    elements = {e["id"]: e for e in gt["elements"]}
    geometries, facts = {}, {}
    for identifier, element in elements.items():
        if not element.get("polygon"):
            raise ValueError("Visibility GT requires original transformed polygons, not inferred rotated AABBs")
        geometries[identifier] = polygon_geometry(element["polygon"])
        x0, y0, x1, y1 = geometries[identifier].bounds
        x0, x1 = min(width, max(0, x0)), min(width, max(0, x1))
        y0, y1 = min(height, max(0, y0)), min(height, max(0, y1))
        expected_box = [x0, y0, x1 - x0, y1 - y0]
        if any(abs(element["bbox"][key] - value) > policy.coordinate_epsilon_pixels
               for key, value in zip(("x", "y", "width", "height"), expected_box)):
            raise ValueError("GT bbox differs from its canvas-clipped polygon envelope")
        facts[identifier] = visibility_facts(element["polygon"], width, height, epsilon=policy.coordinate_epsilon_pixels)
        declared = element.get("metadata", {}).get("geometry_visibility")
        if declared is not None:
            if not isinstance(declared, dict):
                raise ValueError("Visibility facts must be a versioned object")
            exact = visibility_facts(element["polygon"], width, height, epsilon=declared.get("coordinate_epsilon_pixels", 0.05))
            if (not isinstance(declared, dict) or declared.get("schema_version") != "0.1" or declared.get("status") != exact["status"]
                    or not math.isclose(declared.get("visible_fraction", -1), exact["visible_fraction"], abs_tol=1e-9)):
                raise ValueError("Stored visibility facts differ from actual polygon/canvas geometry")
    canonical_task = "ordering" if task == "line_ordering" else task
    manual = [IgnoreRegion.model_validate(r) for r in gt.get("metadata", {}).get("evaluation_ignore_regions", [])]
    if len({r.id for r in manual}) != len(manual):
        raise ValueError("Manual ignore-region IDs must be unique")
    manual_geometry = unary_union([polygon_geometry(r.polygon).intersection(canvas) for r in manual if canonical_task in r.tasks])
    region_shapes, regions = [], []

    def add_region(identifier, reason, geometry):
        geometry = geometry.intersection(canvas)
        if geometry.area == 0:
            return
        region_shapes.append(geometry)
        regions.append({"id": identifier, "reason": reason, "area": geometry.area,
                        "geometry": geometry.__geo_interface__})

    for region in manual:
        if canonical_task in region.tasks:
            add_region("manual:" + region.id, "manual:" + region.reason, polygon_geometry(region.polygon))
    unsupported = {"image", "formula"} if task in {"quality", "line_ordering"} else {"image", "formula", "table"} if task == "ordering" else set()
    for element in elements.values():
        if element.get("metadata", {}).get("role") == "block" and element["type"] in unsupported:
            add_region("unannotated:" + element["id"], "unannotated_" + element["type"], geometries[element["id"]])
    if task in {"quality", "line_ordering"}:
        candidates = extract_gt_lines(gt, page_number=1)
        if task == "line_ordering":
            ranks = {identifier: index for index, identifier in enumerate(gt["reading_order"]["lines"])}
            candidates.sort(key=lambda e: ranks[e["id"]])
    elif task == "ordering":
        candidates = extract_visible_gt_blocks(gt, page_number=1)
    else:
        candidates = extract_gt_structure_elements(gt, page_number=1, unique_blocks=True)
    if len({candidate["id"] for candidate in candidates}) != len(candidates):
        raise ValueError("Derived task annotations must have unique stable IDs")
    eligible, eligible_shapes, decisions = [], [], []
    for candidate in candidates:
        identifier = candidate["id"]
        unit_facts = facts[identifier]
        geometry = geometries[identifier]
        reason = "eligible"
        if unit_facts["status"] == "outside":
            reason = "fully_clipped"
        elif task == "ordering":
            if any(facts[line_id]["status"] != "inside" for line_id in candidate["line_ids"]):
                reason = "incomplete_text_block"
        elif unit_facts["status"] != "inside" and (task != "structure" or policy.structure_partial == "exclude"):
            reason = "partially_clipped"
        if geometry.intersection(manual_geometry).area > 0:
            reason = "manual_region"
        accepted = reason == "eligible"
        decisions.append({"id": identifier, "eligible": accepted, "reason": reason,
                          "visible_fraction": unit_facts["visible_fraction"], "visibility_status": unit_facts["status"],
                          "line_ids": candidate.get("line_ids", candidate.get("metadata", {}).get("line_ids", []))})
        if accepted:
            eligible.append(candidate)
            eligible_shapes.append(geometry.intersection(canvas))
        else:
            # Detectors usually return AABBs; ignored excluded-unit envelopes are explicit.
            add_region("excluded:" + identifier, reason, geometry.envelope)
    ignored = unary_union(region_shapes) if region_shapes else GeometryCollection()
    protected = unary_union(eligible_shapes) if eligible_shapes else GeometryCollection()
    return PreparedScope(task, policy, eligible, decisions, regions, protected, ignored, width * height, json_sha256(gt))
