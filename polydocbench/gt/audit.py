"""Semantic GT audits, separate from permissive interchange schema validation."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .schema import validate_gt_document

GT_AUDIT_VERSION = "0.1"


class _AuditMetadata(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    role: Literal["block", "line", "cell"]
    parent_id: str | None = None
    caption_for: str | None = None
    source_index: int | None = None
    reading_order: int | None = None
    line_index: int | None = None
    source_cell_id: str | None = None
    row_index: int | None = None
    column_index: int | None = None
    rowspan: int | None = None
    colspan: int | None = None
    row_indexes: list[int] = Field(default_factory=list)
    repeated_header_rows: int = 0
    repeated_header: bool = False


class AuditFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    code: str
    severity: Literal["error", "warning"]
    message: str
    element_id: str | None = None
    page: int | None = None


class GTAuditResult(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    audit_version: Literal["0.1"] = GT_AUDIT_VERSION
    coordinate_system: Literal["pdf", "image"]
    counts: dict[str, int] = Field(default_factory=dict)
    findings: list[AuditFinding] = Field(default_factory=list)
    checks: dict[str, str] = Field(default_factory=dict)
    max_geometry_error_pixels: float | None = None

    @property
    def passed(self) -> bool:
        return not any(f.severity == "error" for f in self.findings)

    def add(self, code, message, element=None, *, severity="error", page=None):
        self.findings.append(AuditFinding(code=code, severity=severity, message=message,
                                         element_id=element.get("id") if element else None,
                                         page=page or ((element.get("bbox") or {}).get("page") if element else None)))


def text_signature(text: str) -> str:
    """Ignore whitespace and all hyphens; preserve case/accents/other punctuation."""
    return re.sub(r"\s+", "", text).replace("-", "").replace("\u00ad", "")


def _box(element):
    box = element.get("bbox")
    if not box or not all(isinstance(box.get(k), (int, float)) and math.isfinite(box[k])
                          for k in ("x", "y", "width", "height")):
        return None
    return box


def _within(child, parent, tolerance):
    return (child["x"] >= parent["x"] - tolerance and child["y"] >= parent["y"] - tolerance
            and child["x"] + child["width"] <= parent["x"] + parent["width"] + tolerance
            and child["y"] + child["height"] <= parent["y"] + parent["height"] + tolerance)


def audit_gt_document(data: dict, *, coordinate_system: Literal["pdf", "image"],
                      tolerance: float = 0.01, source_items: list[dict] | None = None) -> GTAuditResult:
    """Audit unique IDs per representation, references, text and table ownership.

    Flat and container copies are not duplicate annotations. Text block allocations
    may be flat-only; rendered lines/cells must occur in exactly one container.
    """
    if coordinate_system not in {"pdf", "image"} or not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("Choose pdf/image coordinates and a finite nonnegative tolerance")
    result = GTAuditResult(coordinate_system=coordinate_system)
    try:
        validate_gt_document(data)
    except (ValidationError, TypeError, ValueError) as exc:
        result.add("schema_invalid", str(exc))
        return result
    if data.get("schema_version") != "0.1":
        result.add("schema_version", "Audit supports explicit GT schema_version 0.1")
    elements, pages = data.get("elements", []), data.get("pages", [])
    if any("page_number" not in page for page in pages):
        result.add("page_number_missing", "Page number must be explicit, not schema-defaulted")
        return result
    result.counts.update(elements=len(elements), pages=len(pages))
    for element in elements:
        try:
            _AuditMetadata.model_validate(element.get("metadata", {}))
        except ValidationError:
            result.add("metadata_invalid", "Malformed/missing role, reference, index or table metadata", element)
        text_type = element["type"] in {"paragraph", "text_line", "caption", "table_cell"} or element["type"].startswith("heading")
        if text_type and not isinstance(element.get("content"), str):
            result.add("text_content_type", "Text annotations require string content", element)
    if result.findings:
        return result
    if not elements or not pages:
        result.add("empty_gt", "Audit requires explicit flat elements and pages")
    indexed = {element["id"]: element for element in elements}
    for identifier, count in Counter(e["id"] for e in elements).items():
        if count > 1:
            result.add("duplicate_id", f"Flat ID appears {count} times", indexed[identifier])
    page_map = {page["page_number"]: page for page in pages}
    if len(page_map) != len(pages):
        result.add("duplicate_page", "Page numbers must be unique")
    nested = Counter()
    for page in pages:
        width, height = page["width"], page["height"]
        if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (width, height)):
            result.add("page_size", "Page dimensions must be finite and positive", page=page["page_number"])
            continue
        if page["page_number"] < 1:
            result.add("page_number", "Page numbers must be positive", page=page["page_number"])
        container_ids = [container["id"] for container in page.get("containers", [])]
        if len(container_ids) != len(set(container_ids)):
            result.add("duplicate_container", "Container IDs must be unique within a page", page=page["page_number"])
        for container in page.get("containers", []):
            allocation = _box(container)
            if allocation is not None and allocation.get("page") != page["page_number"]:
                result.add("container_bbox_page", "Container bbox page differs from its enclosing page", container)
            if container.get("element_count") != len(container.get("elements", [])):
                result.add("container_count", f"Container {container['id']} has an inconsistent element_count", page=page["page_number"])
            for element in container.get("elements", []):
                nested[element["id"]] += 1
                canonical = indexed.get(element["id"])
                if canonical is None:
                    result.add("container_orphan", "Container element has no flat counterpart", element)
                elif any(element.get(k) != canonical.get(k) for k in ("type", "content", "bbox", "polygon")):
                    result.add("container_copy", "Flat and container type/content/geometry differ", element)
                if (element.get("bbox") or {}).get("page") != page["page_number"]:
                    result.add("container_page", "Container and element page differ", element)
                if allocation and _box(element) and not _within(element["bbox"], allocation, tolerance):
                    result.add("container_bounds", "Element bbox exceeds its container allocation", element)
    children = defaultdict(list)
    for element in elements:
        meta = element.get("metadata", {})
        result.counts[element["type"]] = result.counts.get(element["type"], 0) + 1
        box = _box(element)
        if box is None:
            result.add("bbox_invalid", "Missing or nonfinite bbox", element)
            continue
        if min(box["width"], box["height"]) < 0 or (coordinate_system == "pdf" and min(box["width"], box["height"]) <= 0):
            result.add("bbox_extent", "Invalid bbox extent", element)
        page = page_map.get(box.get("page"))
        if page is None:
            result.add("element_page", "Element references an unknown page", element)
        elif all(isinstance(page[k], (int, float)) and math.isfinite(page[k]) for k in ("width", "height")):
            if not _within(box, {"x": 0, "y": 0, "width": page["width"], "height": page["height"]}, tolerance):
                result.add("bbox_outside_page", "BBox exceeds page bounds", element)
        if nested[element["id"]] > 1:
            result.add("multiple_containers", "Element appears in multiple containers", element)
        if meta.get("role") in {"line", "cell"} and nested[element["id"]] != 1:
            result.add("container_missing", "Line/cell must occur in one container", element)
        parent_id = meta.get("parent_id")
        if parent_id:
            parent = indexed.get(parent_id)
            children[parent_id].append(element)
            if parent is None:
                result.add("parent_missing", "Unknown parent_id", element)
            elif _box(parent):
                if box.get("page") != parent["bbox"].get("page"):
                    result.add("parent_page", "Child and parent belong to different pages", element)
                elif not _within(box, parent["bbox"], tolerance):
                    result.add("parent_bounds", "Child bbox exceeds parent allocation", element)
        elif meta.get("role") in {"line", "cell"}:
            result.add("parent_missing", "Line/cell requires parent_id", element)
        if element["type"] == "caption":
            owner = indexed.get(meta.get("caption_for"))
            if owner is None or owner["type"] not in {"image", "table"}:
                result.add("caption_owner", "Caption must reference a table or image", element)
            elif _box(owner) and owner["bbox"]["page"] != box["page"]:
                result.add("caption_page", "Caption and owner must share a page", element)
    for key, role in (("blocks", "block"), ("lines", "line")):
        order = data.get("reading_order", {}).get(key)
        expected = {e["id"] for e in elements if e.get("metadata", {}).get("role") == role}
        if order is None or len(order) != len(set(order)) or set(order) != expected:
            result.add("reading_order_coverage", f"{key} must contain every {role} ID exactly once")
            continue
        previous_page = 0
        for identifier in order:
            e = indexed[identifier]
            if _box(e) and e["bbox"].get("page", 0) < previous_page:
                result.add("reading_order_page", "Reading order goes backwards across pages", e)
            previous_page = (e.get("bbox") or {}).get("page", previous_page)
        if coordinate_system == "pdf":
            for rank, identifier in enumerate(order, 1):
                if indexed[identifier].get("metadata", {}).get("reading_order") != rank:
                    result.add("reading_order_index", "Metadata index differs from explicit reading order", indexed[identifier])
    for element in elements:
        visited, current = set(), element
        while current.get("metadata", {}).get("parent_id") in indexed:
            if current["id"] in visited:
                result.add("parent_cycle", "Parent references contain a cycle", element)
                break
            visited.add(current["id"])
            current = indexed[current["metadata"]["parent_id"]]
    for parent in elements:
        needs_lines = parent["type"] in {"paragraph", "caption", "table_cell"} or parent["type"].startswith("heading")
        if needs_lines and isinstance(parent.get("content"), str) and text_signature(parent["content"]):
            if not any(e["type"] == "text_line" for e in children[parent["id"]]):
                result.add("missing_text_lines", "Nonempty text allocation has no text-line annotations", parent)
    for parent_id, items in children.items():
        parent = indexed.get(parent_id)
        lines = [e for e in items if e["type"] == "text_line"]
        if parent and isinstance(parent.get("content"), str) and lines:
            ordered = sorted(lines, key=lambda e: e.get("metadata", {}).get("line_index", 0))
            if text_signature(parent["content"]) != text_signature(" ".join(e["content"] for e in ordered)):
                result.add("parent_text", "Parent text differs from its line reconstruction", parent)
    _audit_tables(elements, indexed, children, result)
    if data.get("metadata", {}).get("layout_warnings"):
        result.add("layout_warnings", "Renderer reported unsupported/missing content; inspect original warnings")
    result.checks["structure"] = "checked"
    if source_items is not None:
        _audit_source(source_items, elements, result)
        result.checks["source_coverage"] = "checked_full_document"
    else:
        result.checks["source_coverage"] = "not_checked"
    return result


def _audit_tables(elements, indexed, children, result):
    source_cells = defaultdict(list)
    for element in elements:
        if element["type"] != "table_cell":
            continue
        meta = element.get("metadata", {})
        parent = indexed.get(meta.get("parent_id"))
        if parent is None or parent["type"] != "table":
            result.add("cell_owner", "Cell parent must be a table fragment", element)
            continue
        rows = parent.get("metadata", {}).get("row_indexes", [])
        row, column = meta.get("row_index"), meta.get("column_index")
        rowspan, colspan = meta.get("rowspan"), meta.get("colspan")
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in (row, column, rowspan, colspan)) or min(row, column) < 0 or min(rowspan, colspan) < 1:
            result.add("cell_grid", "Cell needs nonnegative row/column and positive integer spans", element)
            continue
        widths = (parent.get("dimensions") or {}).get("column_widths", [])
        if not set(range(row, row + rowspan)) <= set(rows) or column + colspan > len(widths):
            result.add("cell_span", "Cell span crosses a fragment/column boundary", element)
        repeated_count = parent.get("metadata", {}).get("repeated_header_rows", 0)
        if meta.get("repeated_header") != (row in rows[:repeated_count]):
            result.add("repeated_header_flag", "Repeated-header flag differs from fragment rows", element)
        if not meta.get("source_cell_id"):
            result.add("source_cell_id", "Cell lacks its stable source-cell ID", element)
        else:
            source_cells[meta["source_cell_id"]].append(element)
    for items in source_cells.values():
        originals = [e for e in items if not e["metadata"].get("repeated_header")]
        if (result.coordinate_system == "pdf" and len(originals) != 1) or len(originals) > 1:
            result.add("source_cell_occurrence", "Source cell must have one original and only declared header repeats", items[0])
        if any(e["content"] != items[0]["content"] for e in items):
            result.add("repeated_header_text", "Repeated header text differs from its source cell", items[0])
    for table in (e for e in elements if e["type"] == "table"):
        occupied = set()
        for cell in (e for e in children[table["id"]] if e["type"] == "table_cell"):
            m = cell["metadata"]
            if not all(isinstance(m.get(k), int) for k in ("row_index", "column_index", "rowspan", "colspan")):
                continue
            if not (0 < m["rowspan"] <= len(table.get("metadata", {}).get("row_indexes", []))
                    and 0 < m["colspan"] <= len((table.get("dimensions") or {}).get("column_widths", []))):
                continue
            slots = {(r, c) for r in range(m["row_index"], m["row_index"] + min(m["rowspan"], 1000))
                     for c in range(m["column_index"], m["column_index"] + min(m["colspan"], 1000))}
            if occupied & slots:
                result.add("cell_overlap", "Logical cells overlap within a table fragment", cell)
            occupied.update(slots)


def _audit_source(source_items, elements, result):
    blocks = defaultdict(list)
    for element in elements:
        if element.get("metadata", {}).get("role") == "block":
            blocks[element["metadata"].get("source_index")].append(element)
            if element["metadata"].get("source_index") not in range(1, len(source_items) + 1):
                result.add("source_index", "Block references no normalized source item", element)
    checked = 0
    for index, source in enumerate(source_items, 1):
        owners = blocks[index]
        if not owners:
            result.add("source_item_missing", f"No GT block for source item {index} ({source['type']})")
            continue
        if source.get("caption") and not any(e["type"] == "caption" and e["content"] == source["caption"] for e in owners):
            result.add("source_caption", f"Missing/changed caption for source item {index}", owners[0])
        if source["type"] in {"paragraph", "text", "text_line"} or source["type"].startswith("heading"):
            fragments = sorted((e for e in owners if e["type"] == source["type"]),
                               key=lambda e: (e["bbox"]["page"], e["metadata"].get("reading_order", 0)))
            expected = source.get("content", source.get("text", ""))
            if text_signature(str(expected)) != text_signature(" ".join(str(e["content"]) for e in fragments)):
                result.add("source_text", f"Text reconstruction differs for source item {index}", owners[0])
            checked += 1
        elif source["type"] == "table":
            from polydocbench.document.tables import validate_table

            cells, _ = validate_table(source).grid()
            actual = {(e["metadata"].get("row_index"), e["metadata"].get("column_index")): e
                      for e in elements if e["type"] == "table_cell" and e["metadata"].get("source_index") == index
                      and not e["metadata"].get("repeated_header")}
            if set(actual) != {(c.row, c.column) for c in cells}:
                result.add("source_table_cells", f"Missing/extra logical source cells for item {index}", owners[0])
            for cell in cells:
                entry = actual.get((cell.row, cell.column))
                if entry and (entry["content"] != cell.cell.text or entry["metadata"].get("rowspan") != cell.cell.rowspan
                              or entry["metadata"].get("colspan") != cell.cell.colspan):
                    result.add("source_table_cell", "Cell text/span differs from normalized source", entry)
    result.counts["source_items"] = len(source_items)
    result.counts["source_text_items_checked"] = checked
