"""Evidence-bound review handoff; pending decisions cannot become release approval."""

from __future__ import annotations

from collections import Counter
import html
import json
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from polydocbench.eval.contract import FrozenEvaluation
from polydocbench.provenance import FileFingerprint, fingerprint_file, json_sha256
from .calibration import CalibrationPlan
from .calibration_run import write_calibration_results
from .gt_audit import rebuild_gt_audit
from .manifest import DatasetManifest, verify_manifest


class DevelopmentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit_id: str
    category: Literal["source_rights", "source_families", "font_asset_rights", "evaluation_protocol", "noise_severity"]
    status: Literal["pending", "approved", "rejected"] = "pending"
    reviewer: str | None = None
    reviewer_kind: Literal["human"] = "human"
    reviewed_at: AwareDatetime | None = None
    notes: str = ""

    @model_validator(mode="after")
    def explicit_human_decision(self):
        if self.status != "pending" and (not self.reviewer or not self.reviewer.strip() or not self.reviewed_at or not self.notes.strip()):
            raise ValueError("Approval/rejection requires a named human, timezone-aware time and rationale")
        return self


class DevelopmentReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["0.1"] = "0.1"
    bundle_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    purpose: Literal["development_only_never_final_test"] = "development_only_never_final_test"
    files: list[FileFingerprint] = Field(min_length=1)
    decisions: list[DevelopmentDecision] = Field(min_length=1)

    @model_validator(mode="after")
    def seal(self):
        payload = self.model_dump(mode="json", exclude={"bundle_id", "decisions"})
        payload["units"] = [{"unit_id": d.unit_id, "category": d.category} for d in self.decisions]
        if self.bundle_id != json_sha256(payload):
            raise ValueError("Review bundle does not match its frozen evidence and decision units")
        keys = [(d.category, d.unit_id) for d in self.decisions]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate development review units")
        required = {"source_rights", "source_families", "font_asset_rights", "evaluation_protocol", "noise_severity"}
        if {d.category for d in self.decisions} != required or len({f.path for f in self.files}) != len(self.files):
            raise ValueError("Review must retain every approval category and unique evidence files")
        return self


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path, value):
    with path.open("x", encoding="utf-8") as file:
        file.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def prepare_development_review(root: Path) -> DevelopmentReview:
    root = root.resolve(strict=True)
    inventory = DatasetManifest.model_validate(_read(root / "manifest.json"))
    if inventory.issues or verify_manifest(inventory, root / "dataset"):
        raise ValueError("Resolve candidate inventory issues before review")
    audit = rebuild_gt_audit(root / "audit", root / "dataset")
    calibration = write_calibration_results(root / "calibration")
    plan = CalibrationPlan.model_validate(_read(root / "calibration/calibration_plan.json"))
    contract = plan.spec.evaluation_contract
    if contract is None:
        raise ValueError("Development review requires a frozen visibility-aware evaluation contract")
    contract.verify_runtime()
    _save(root / "frozen_evaluation.json", contract.model_dump())
    paths = [root / name for name in ("manifest.json", "development_spec.json", "development_summary.json",
             "capture_summary.json", "page_selection.json", "source_families.draft.json", "frozen_evaluation.json",
             "audit/audit_plan.json", "audit/audit_evidence.json", "audit/review_units.json",
             "calibration/calibration_plan.json", "calibration/pilot_plan.json", "calibration/manifest.json",
             "calibration/run/run.json", "calibration/run/job.json", "calibration/run/results.jsonl",
             "calibration/calibration_metrics.jsonl", "calibration/paired_results.jsonl")]
    paths.extend(sorted((root / "rights").glob("*.json")))
    # Review snapshots also bind local model predictions and scope ledgers.
    paths.extend(sorted((root / "calibration/run/predictions").glob("*.json")))
    if (root / "scenarios/comparison.json").exists():
        paths.extend(sorted((root / "scenarios").rglob("*.json")))
        paths.extend(sorted((root / "scenarios").rglob("*.jsonl")))
        paths.append(root / "scenarios/summary.csv")
    if (root / "AI_VISUAL_REVIEW.md").exists():
        paths.append(root / "AI_VISUAL_REVIEW.md")
    files = [fingerprint_file(root, path) for path in paths]
    sources = {record.source.path: record.source.sha256 for record in inventory.records}
    units = [{"unit_id": sha, "category": "source_rights"} for _, sha in sorted(sources.items())]
    units.extend({"unit_id": json_sha256(_read(root / name)), "category": category} for name, category in (
        ("source_families.draft.json", "source_families"), ("development_summary.json", "font_asset_rights")))
    units.extend([{"unit_id": contract.contract_id, "category": "evaluation_protocol"},
                  {"unit_id": plan.plan_id, "category": "noise_severity"}])
    payload = {"schema_version": "0.1", "purpose": "development_only_never_final_test", "files": [f.model_dump() for f in files]}
    result = DevelopmentReview(bundle_id=json_sha256({**payload, "units": units}),
                               decisions=[DevelopmentDecision(**u) for u in units], **payload)
    _save(root / "review_checklist.json", result.model_dump(mode="json"))
    _write_handoff(root, result, audit, calibration)
    return result


def check_development_review(root: Path) -> dict:
    root = root.resolve(strict=True)
    review = DevelopmentReview.model_validate(_read(root / "review_checklist.json"))
    for file in review.files:
        if fingerprint_file(root, root / file.path) != file:
            raise ValueError(f"Reviewed evidence changed: {file.path}")
    inventory = DatasetManifest.model_validate(_read(root / "manifest.json"))
    if inventory.issues or verify_manifest(inventory, root / "dataset"):
        raise ValueError("Development input hashes no longer verify")
    contract = FrozenEvaluation.model_validate(_read(root / "frozen_evaluation.json"))
    contract.verify_runtime()
    audit = rebuild_gt_audit(root / "audit", root / "dataset")
    calibration = write_calibration_results(root / "calibration")
    plan = CalibrationPlan.model_validate(_read(root / "calibration/calibration_plan.json"))
    expected_units = {(r.source.sha256, "source_rights") for r in inventory.records}
    expected_units.update((json_sha256(_read(root / name)), category) for name, category in (
        ("source_families.draft.json", "source_families"), ("development_summary.json", "font_asset_rights")))
    expected_units.update({(contract.contract_id, "evaluation_protocol"), (plan.plan_id, "noise_severity")})
    if {(d.unit_id, d.category) for d in review.decisions} != expected_units:
        raise ValueError("Approval units do not cover this exact candidate's sources and protocols")
    reasons = readiness_blockers(review, audit, calibration)
    if (root / "scenarios/comparison.json").exists():
        scenarios = _read(root / "scenarios/comparison.json")
        if scenarios["selected_images"] != scenarios["successful_images"]:
            reasons.append("Bundled-scenario comparison has unresolved failures")
    result = {"bundle_id": review.bundle_id, "development_approved": not reasons, "blocking_reasons": reasons,
              "decisions": dict(Counter(d.status for d in review.decisions)),
              "gt_reviews": audit["manual_review_statuses"], "evaluation_contract_id": contract.contract_id,
              "final_test_approved": False,
              "review_validation_limit": "Checks explicit records and integrity, not reviewer honesty or legal sufficiency"}
    (root / "review_status.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    _write_handoff(root, review, audit, calibration)
    return result


def readiness_blockers(review, audit, calibration):
    reasons = []
    if any(d.status != "approved" for d in review.decisions):
        reasons.append("Source/family/rights/protocol/severity decisions are not all approved")
    if audit["automatic_error_findings"]:
        reasons.append("Automatic GT audit contains errors")
    if audit["manual_review_statuses"].get("accepted", 0) != audit["manual_review_units"]:
        reasons.append("Not every selected GT preview has an explicit accepted review")
    if calibration["selected_images"] != calibration["successful_images"]:
        reasons.append("Calibration has failures; resolve them or freeze an explicit missingness policy")
    return reasons


def _write_handoff(root, review, audit, calibration):
    spec = _read(root / "development_spec.json")
    selection = _read(root / "page_selection.json")["pages"]
    rows = "".join(f"<tr><td>{html.escape(s['language'])}</td><td>{html.escape(s['article_id'])}</td>"
                   f"<td>{html.escape(s['template'])}</td><td>{s['page']}</td>"
                   f"<td>{s['page_element_counts'].get('table', 0)}</td><td>{s['page_element_counts'].get('image', 0)}</td></tr>" for s in selection)
    page = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    page += '<title>PolyDocBench Development Review</title><style>body{font:15px system-ui;max-width:1200px;margin:32px auto;padding:16px;color:#25312e}a{color:#126b93}table{border-collapse:collapse;font-size:13px}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}.scroll{overflow:auto}p{line-height:1.6}</style>'
    page += '<h1>PolyDocBench Development Candidate</h1><p><strong>Not approved for publication. Human review required.</strong></p>'
    page += f'<p>{len(selection)} base pages; {len(spec["sources"])} sources; {len(spec["templates"])} templates. Controlled text excerpts, synthetic tables/figures; no real-scanner validation.</p>'
    page += '<p><a href="audit/index.html">GT review gallery</a> | <a href="calibration/dashboard.html">Noise calibration</a> | <a href="review_checklist.json">Approval checklist</a> | <a href="audit/reviews.json">GT decisions</a> | <a href="frozen_evaluation.json">Frozen evaluator</a> | <a href="source_families.draft.json">Source families</a> | <a href="rights/">Captured rights metadata</a></p>'
    if (root / "scenarios/comparison.json").exists():
        page += '<p><a href="scenarios/dashboard.html">Existing noise bundles</a> | <a href="scenarios/comparison.json">Scenario counts and caveats</a>. Names are scenarios, not an approved monotonic difficulty scale.</p>'
    if (root / "AI_VISUAL_REVIEW.md").exists():
        page += '<p><a href="AI_VISUAL_REVIEW.md">AI-assisted visual spot checks and unresolved limitations</a> (not human approval).</p>'
    page += f'<p>Automatic GT errors: {audit["automatic_error_findings"]}; human GT decisions: {html.escape(str(audit["manual_review_statuses"]))}; calibration requests: {calibration["successful_images"]}/{calibration["selected_images"]}. Approval decisions: {html.escape(str(dict(Counter(d.status for d in review.decisions))))}.</p>'
    page += '<h2>Selected pages</h2><div class="scroll"><table><tr><th>Language</th><th>Source</th><th>Template</th><th>Page</th><th>Tables</th><th>Figures</th></tr>' + rows + '</table></div>'
    page += '<h2>Review boundaries</h2><p>Families are reserved for development only, never a final test. All pages and noise variants of a family must stay together. Two families do not support broad statistical generalization. Font/project-asset rights and the project code license still require explicit release decisions. Site-wide rights metadata alone is not a per-excerpt rights approval. No model ranking or calibrated real-scanner severity is claimed.</p></html>'
    (root / "index.html").write_text(page, encoding="utf-8")
