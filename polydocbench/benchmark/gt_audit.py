"""Frozen audit runs, evidence binding and explicit human-review records."""

from __future__ import annotations

import contextlib
import io
import json
import platform
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image, ImageDraw
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from polydocbench.gt.audit import GT_AUDIT_VERSION, GTAuditResult, audit_gt_document, text_signature
from polydocbench.gt.audit_geometry import audit_image_gt
from polydocbench.layout.content_loader import ContentLoader
from polydocbench.noise import render_pdf_page, replay_noise
from polydocbench.provenance import FileFingerprint, fingerprint_file, json_sha256
from .manifest import verify_manifest
from .pilot import PilotPlan


class AuditModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class GTAuditPlan(AuditModel):
    schema_version: Literal["0.1"] = "0.1"
    audit_version: Literal["0.1"] = GT_AUDIT_VERSION
    plan_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    pilot: PilotPlan
    point_tolerance: float = Field(default=0.01, ge=0, le=1)
    pixel_tolerance: float = Field(default=0.05, ge=0, le=1)
    replay_pixels: bool = True

    @model_validator(mode="after")
    def seal(self):
        if self.plan_id != json_sha256(self.model_dump(exclude={"plan_id"})):
            raise ValueError("GT audit plan seal differs from settings/selection")
        return self

    @classmethod
    def freeze(cls, pilot: PilotPlan, **settings):
        payload = {"schema_version": "0.1", "audit_version": GT_AUDIT_VERSION, "pilot": pilot.model_dump(),
                   "point_tolerance": 0.01, "pixel_tolerance": 0.05, "replay_pixels": True, **settings}
        # Normalize numeric settings before sealing the serialized representation.
        payload["point_tolerance"] = float(payload["point_tolerance"])
        payload["pixel_tolerance"] = float(payload["pixel_tolerance"])
        return cls(plan_id=json_sha256(payload), **payload)


class PageReview(AuditModel):
    unit_id: str
    status: Literal["pending", "accepted", "defect"] = "pending"
    reviewer: str | None = None
    reviewed_at: AwareDatetime | None = None
    notes: str = ""

    @model_validator(mode="after")
    def explicit_review(self):
        if self.status != "pending" and (not self.reviewer or not self.reviewer.strip() or self.reviewed_at is None):
            raise ValueError("A review decision needs a named reviewer and timezone-aware reviewed_at")
        if self.status == "defect" and not self.notes.strip():
            raise ValueError("A defect decision needs explanatory notes")
        return self


class AuditReviews(AuditModel):
    schema_version: Literal["0.1"] = "0.1"
    audit_plan_id: str
    reviews: list[PageReview]


def _save(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2) + "\n", encoding="utf-8")


def _jsonl(path: Path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=True, allow_nan=False) + "\n" for row in rows), encoding="utf-8")


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _preview(image, gt, page_number, output, stem, *, pdf=False, dpi=200):
    clean = Image.fromarray(image).convert("RGB")
    overlay = clean.copy()
    draw = ImageDraw.Draw(overlay)
    for element in gt.get("elements", []):
        box = element.get("bbox") or {}
        if box.get("page") != page_number:
            continue
        try:
            if pdf:
                scale = dpi / 72
                x, y, w, h = (float(box[k]) for k in ("x", "y", "width", "height"))
                points = [(x * scale, clean.height - (y + h) * scale), ((x + w) * scale, clean.height - y * scale)]
                if not np.isfinite(points).all():
                    continue
                draw.rectangle(points, outline="red" if element["type"] == "text_line" else "#1675b9", width=2)
            else:
                points = element.get("polygon")
                if points and np.isfinite(points).all():
                    draw.line([tuple(p) for p in points] + [tuple(points[0])],
                              fill="red" if element["type"] == "text_line" else "#1675b9", width=2)
        except (KeyError, TypeError, ValueError):
            continue
    paths = []
    for suffix, bitmap in (("original", clean), ("gt", overlay)):
        path = output / "previews" / f"{stem}_{suffix}.jpg"
        bitmap.thumbnail((1000, 1400))
        bitmap.save(path, quality=88)
        paths.append(path.relative_to(output).as_posix())
    return paths


def _pdf_evidence(source_gt, pdf, result, tolerance):
    """Independent PDF page dimensions and extracted-character inventory diagnostic."""
    pages = {page["page_number"]: page for page in source_gt["pages"]}
    if set(pages) != set(range(1, len(pdf) + 1)):
        result.add("pdf_page_inventory", "PDF and GT page-number inventories differ")
    differences = 0
    for number, page in enumerate(pdf, 1):
        spec = pages.get(number)
        if spec and (abs(page.rect.width - float(spec["width"])) > tolerance or abs(page.rect.height - float(spec["height"])) > tolerance):
            result.add("pdf_dimensions", "PDF page dimensions differ from GT", page=number)
        expected = "".join(str(e["content"]) for e in source_gt.get("elements", [])
                           if e["type"] == "text_line" and e.get("metadata", {}).get("role") == "line"
                           and (e.get("bbox") or {}).get("page") == number)
        signature = lambda s: Counter(text_signature(unicodedata.normalize("NFKC", s)))
        wanted, actual = signature(expected), signature(page.get_text())
        missing, extra = sum((wanted - actual).values()), sum((actual - wanted).values())
        if missing or extra:
            differences += 1
            result.add("pdf_text_inventory", f"PDF extractor differs: {missing} missing / {extra} extra characters; inspect glyphs/rendering",
                       severity="warning", page=number)
    result.counts["pdf_text_inventory_different_pages"] = differences
    result.checks["pdf_dimensions"] = "checked"
    result.checks["pdf_text_inventory"] = "diagnostic_not_ink_alignment_proof"


def run_gt_audit(plan: GTAuditPlan, input_dir: str | Path, output_dir: str | Path) -> dict:
    import fitz

    root, output = Path(input_dir).resolve(strict=True), Path(output_dir).resolve()
    issues = verify_manifest(plan.pilot.selection, root)
    if issues:
        raise ValueError(f"GT audit input integrity failed: {issues[0].path}")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("GT audit output must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    (output / "previews").mkdir()
    _save(output / "audit_plan.json", plan.model_dump())
    documents, images, units = [], [], []
    cached, previewed = {}, set()
    for index, record in enumerate(plan.pilot.selection.records, 1):
        document_id = json_sha256({"pdf": record.pdf.sha256, "gt": record.pdf_gt.sha256, "source": record.source.sha256})
        if document_id not in cached:
            source_gt = _load(root / record.pdf_gt.path)
            with contextlib.redirect_stdout(io.StringIO()):
                items = ContentLoader.load_json(root / record.source.path)
            result = audit_gt_document(source_gt, coordinate_system="pdf", tolerance=plan.point_tolerance, source_items=items)
            with fitz.open(root / record.pdf.path) as pdf:
                if result.checks.get("structure") == "checked":
                    _pdf_evidence(source_gt, pdf, result, plan.point_tolerance)
                else:
                    result.checks["pdf_evidence"] = "not_checked_invalid_gt"
            documents.append({"document_id": document_id, "source": record.source.path, "pdf": record.pdf.path,
                              "language": record.language, "article_id": record.article_id, "template": record.template,
                              "result": result.model_dump()})
            cached[document_id] = source_gt
        source_gt = cached[document_id]
        page_key = (document_id, record.source_page_number)
        if page_key not in previewed:
            previewed.add(page_key)
            raster, _ = render_pdf_page(root / record.pdf.path, record.source_page_number - 1, record.dpi)
            unit_id = "pdf_" + json_sha256({"document_id": document_id, "page": record.source_page_number})
            original, overlay = _preview(raster, source_gt, record.source_page_number, output, unit_id, pdf=True, dpi=record.dpi)
            units.append({"unit_id": unit_id, "kind": "pdf_page", "document_id": document_id,
                          "source_page_number": record.source_page_number, "language": record.language,
                          "article_id": record.article_id, "template": record.template, "profile": "PDF",
                          "original": original, "overlay": overlay})
        data = _load(root / record.image_gt.path)
        with Image.open(root / record.image.path) as bitmap:
            pixels = np.array(bitmap.convert("RGB"))
        result = audit_image_gt(data, source_gt, source_page_number=record.source_page_number,
                                image_size=(pixels.shape[1], pixels.shape[0]), dpi=record.dpi, tolerance=plan.pixel_tolerance)
        trace = data.get("metadata", {}).get("noise_generation")
        if plan.replay_pixels and trace:
            try:
                base, _ = render_pdf_page(root / record.pdf.path, record.source_page_number - 1, record.dpi)
                replayed = replay_noise(base, trace)
                buffer = io.BytesIO()
                Image.fromarray(replayed.image).save(buffer, "PNG" if trace["encoding"] == "PNG" else "JPEG",
                                                    **({} if trace["encoding"] == "PNG" else {"quality": 95}))
                import hashlib

                if hashlib.sha256(buffer.getvalue()).hexdigest() != record.image.sha256:
                    result.add("pixel_replay", "Encoded image replay differs from the selected scan")
                    result.checks["pixel_replay"] = "failed"
                else:
                    result.checks["pixel_replay"] = "passed"
            except (ValueError, KeyError, TypeError) as exc:
                result.add("pixel_replay", str(exc))
                result.checks["pixel_replay"] = "failed"
        else:
            result.checks["pixel_replay"] = "not_requested" if not plan.replay_pixels else "unavailable_legacy_trace"
        images.append({"artifact_id": record.artifact_id, "document_id": document_id,
                       "language": record.language, "article_id": record.article_id, "template": record.template,
                       "source_page_number": record.source_page_number, "profile": record.profile,
                       "image": record.image.path, "image_gt": record.image_gt.path, "result": result.model_dump()})
        unit_id = "image_" + record.artifact_id
        original, overlay = _preview(pixels, data, 1, output, unit_id)
        units.append({"unit_id": unit_id, "kind": "scan", "document_id": document_id, "artifact_id": record.artifact_id,
                      "language": record.language, "article_id": record.article_id, "template": record.template,
                      "source_page_number": record.source_page_number, "profile": record.profile,
                      "original": original, "overlay": overlay})
        print(f"Audit [{index}/{len(plan.pilot.selection.records)}] {record.language}/{record.template}/{record.profile}: "
              f"{sum(f.severity == 'error' for f in result.findings)} errors, {sum(f.severity == 'warning' for f in result.findings)} warnings", flush=True)
    _jsonl(output / "document_results.jsonl", documents)
    _jsonl(output / "image_results.jsonl", images)
    _save(output / "review_units.json", units)
    template = AuditReviews(audit_plan_id=plan.plan_id, reviews=[PageReview(unit_id=u["unit_id"]) for u in units])
    _save(output / "reviews.json", template.model_dump(mode="json"))
    files = [output / name for name in ("document_results.jsonl", "image_results.jsonl", "review_units.json")]
    files.extend(sorted((output / "previews").glob("*.jpg")))
    code_root = Path(__file__).resolve().parents[2]
    code = [fingerprint_file(code_root, p).model_dump() for p in sorted((code_root / "polydocbench").rglob("*.py"))]
    _save(output / "audit_evidence.json", {"audit_plan_id": plan.plan_id, "python": platform.python_version(),
                                         "code_sha256": json_sha256({"files": code}),
                                         "files": [fingerprint_file(output, p).model_dump() for p in files]})
    return rebuild_gt_audit(output, root)


def rebuild_gt_audit(output_dir: str | Path, input_dir: str | Path, review_file: str | Path | None = None) -> dict:
    output, root = Path(output_dir).resolve(strict=True), Path(input_dir).resolve(strict=True)
    plan = GTAuditPlan.model_validate_json((output / "audit_plan.json").read_text(encoding="utf-8"))
    if verify_manifest(plan.pilot.selection, root):
        raise ValueError("GT audit selected input hashes changed")
    evidence = _load(output / "audit_evidence.json")
    if evidence["audit_plan_id"] != plan.plan_id:
        raise ValueError("Evidence belongs to a different GT audit plan")
    paths = [value["path"] for value in evidence["files"]]
    if len(paths) != len(set(paths)) or not {"document_results.jsonl", "image_results.jsonl", "review_units.json"} <= set(paths):
        raise ValueError("Incomplete/duplicate audit evidence inventory")
    for value in evidence["files"]:
        fingerprint = FileFingerprint.model_validate(value)
        if fingerprint_file(output, output / fingerprint.path) != fingerprint:
            raise ValueError(f"GT audit evidence changed: {fingerprint.path}")
    read_rows = lambda name: [json.loads(line) for line in (output / name).read_text(encoding="utf-8").splitlines() if line.strip()]
    documents, images, units = read_rows("document_results.jsonl"), read_rows("image_results.jsonl"), _load(output / "review_units.json")
    reviews = AuditReviews.model_validate_json(Path(review_file or output / "reviews.json").read_text(encoding="utf-8"))
    unit_ids = {unit["unit_id"] for unit in units}
    if reviews.audit_plan_id != plan.plan_id or len(reviews.reviews) != len(unit_ids) or {r.unit_id for r in reviews.reviews} != unit_ids:
        raise ValueError("Human reviews must cover exactly this frozen plan's preview units without duplicates")
    all_results = [GTAuditResult.model_validate(row["result"]) for row in [*documents, *images]]
    if len(images) != len(plan.pilot.selection.records) or {r["artifact_id"] for r in images} != {r.artifact_id for r in plan.pilot.selection.records}:
        raise ValueError("Audit results must retain every selected image exactly once")
    errors = sum(f.severity == "error" for r in all_results for f in r.findings)
    summary = {"audit_plan_id": plan.plan_id, "audit_version": GT_AUDIT_VERSION, "split": plan.pilot.split,
               "documents_checked": len(documents), "document_pages_checked": sum(r["result"]["counts"].get("pages", 0) for r in documents),
               "previewed_pdf_pages": len(units) - len(images), "selected_images": len(images),
               "images_without_errors": sum(GTAuditResult.model_validate(r["result"]).passed for r in images),
               "documents_without_errors": sum(GTAuditResult.model_validate(r["result"]).passed for r in documents),
               "automatic_error_findings": errors, "automatic_warning_findings": sum(f.severity == "warning" for r in all_results for f in r.findings),
               "manual_review_units": len(units), "manual_review_statuses": dict(Counter(r.status for r in reviews.reviews)),
               "reviewed_preview_units": sum(r.status != "pending" for r in reviews.reviews),
               "manual_preview_unit_defect_rate": (sum(r.status == "defect" for r in reviews.reviews)
                   / sum(r.status != "pending" for r in reviews.reviews) if any(r.status != "pending" for r in reviews.reviews) else None),
               "maximum_coordinate_error_pixels": max((r.max_geometry_error_pixels for r in all_results
                   if r.max_geometry_error_pixels is not None), default=None),
               "checked_transform_elements": sum(r.counts.get("checked_transform_elements", 0) for r in all_results),
               "partially_clipped_elements": sum(r.counts.get("partially_clipped_elements", 0) for r in all_results),
               "fully_clipped_elements": sum(r.counts.get("fully_clipped_elements", 0) for r in all_results),
               "applied_reviews_sha256": json_sha256(reviews.model_dump(mode="json")),
               "manual_review_scope": "selected_previews_only_not_all_document_pages",
               "rights_and_family_approval": "not_granted_by_gt_audit", "publication_gt_approval": "not_automatic"}
    _save(output / "summary.json", summary)
    from .gt_audit_report import write_gt_audit_report

    write_gt_audit_report(output, summary, documents, images, units, reviews, root, plan.pilot)
    return summary
