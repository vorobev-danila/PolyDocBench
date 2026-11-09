"""Build a development-only candidate; never grant human or publication approval."""

from __future__ import annotations

from collections import Counter
import contextlib
import io
import json
import shutil
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field, model_validator
import requests

from polydocbench.document.tables import validate_table
from polydocbench.noise import pdf_to_noisy_dataset
from polydocbench.provenance import fingerprint_file, json_sha256
from polydocbench.sources.derived import CompositionRecipe, create_derived_source
from polydocbench.sources.snapshots import capture_wikipedia_source, verify_wikipedia_source, wikipedia_target
from polydocbench.sources.wikipedia import DEFAULT_USER_AGENT
from .manifest import DatasetManifest, build_manifest, verify_manifest
from .render_snapshot import capture_render_snapshot
from .splits import SourceFamily, SourceFamilyCatalog, draft_source_catalog


class DevelopmentSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: Literal["en", "ru", "fr", "de", "es", "it"]
    article_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    family_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    url: str

    @model_validator(mode="after")
    def correct_language(self):
        if wikipedia_target(self.url)[0] != self.language:
            raise ValueError("Source language differs from its Wikipedia host")
        return self


class DevelopmentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: Literal["0.1"] = "0.1"
    purpose: Literal["development_candidate_only"] = "development_candidate_only"
    sources: list[DevelopmentSource] = Field(min_length=1)
    templates: list[str] = Field(min_length=1)
    text_items: int = Field(default=12, ge=2, le=50, strict=True)
    max_item_characters: int = Field(default=1200, ge=100, le=10000, strict=True)
    text_filter: Literal["prose_without_tex_or_navigation_v1"] = "prose_without_tex_or_navigation_v1"
    dpi: int = Field(default=200, ge=72, le=300, strict=True)
    seed: int = Field(default=42, ge=0, strict=True)
    profiles: list[Literal["clean", "light_scan", "medium_scan", "heavy_scan"]]
    page_selection: Literal["max_table_figure_presence_then_text_v1"]
    labels: dict[str, tuple[str, str]]

    @model_validator(mode="after")
    def validate_matrix(self):
        from polydocbench.layout.templates import load_layout_templates

        keys = [(s.language, s.article_id) for s in self.sources]
        if len(keys) != len(set(keys)) or len({s.url for s in self.sources}) != len(self.sources):
            raise ValueError("Duplicate development source")
        if set(self.templates) - set(load_layout_templates()["templates"]) or len(set(self.templates)) != len(self.templates):
            raise ValueError("Unknown or duplicate template")
        if "clean" not in self.profiles or len(set(self.profiles)) != len(self.profiles):
            raise ValueError("Use unique conditions including a clean control")
        if {s.language for s in self.sources} - set(self.labels):
            raise ValueError("Every language needs figure and table labels")
        return self

    @property
    def spec_id(self):
        return json_sha256(self.model_dump())


def _write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as file:
        file.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def capture_development_sources(spec: DevelopmentSpec, root: Path, *, source_cache: Path | None = None) -> dict:
    """Resume only verified source captures; retain the exact recipe before fetching."""
    root.mkdir(parents=True, exist_ok=True)
    frozen = root / "development_spec.json"
    if frozen.exists():
        if DevelopmentSpec.model_validate_json(frozen.read_text(encoding="utf-8")) != spec:
            raise ValueError("Development root contains a different frozen specification")
    else:
        _write(frozen, spec.model_dump())
    for index, source in enumerate(spec.sources, 1):
        directory = root / "sources" / source.language / source.article_id
        if source_cache is not None and not directory.exists():
            cached = source_cache / "sources" / source.language / source.article_id
            cached_evidence = verify_wikipedia_source(cached, reparse=True)
            if wikipedia_target(cached_evidence.inputs.requested_url) != wikipedia_target(source.url):
                raise ValueError("Cached revision does not match the requested source")
            directory.mkdir(parents=True)
            for name in ("source.json", "source_provenance.json", "query.json", "parse.json", "page.html"):
                shutil.copyfile(cached / name, directory / name)
        if directory.exists() and any(directory.iterdir()):
            evidence = verify_wikipedia_source(directory, reparse=True)
        else:
            capture_wikipedia_source(source.url, directory)
            evidence = verify_wikipedia_source(directory, reparse=True)
        if wikipedia_target(evidence.inputs.requested_url) != wikipedia_target(source.url):
            raise ValueError("Existing source snapshot differs from the requested source")
        print(f"Capture [{index}/{len(spec.sources)}] {source.language}/{source.article_id}: revision {evidence.inputs.revision_id}", flush=True)
    receipts = []
    for language in sorted({s.language for s in spec.sources}):
        path = root / "rights" / f"{language}_siteinfo.json"
        if not path.exists():
            response = requests.get(f"https://{language}.wikipedia.org/w/api.php",
                                    params={"action": "query", "meta": "siteinfo", "siprop": "rightsinfo",
                                            "format": "json", "formatversion": "2"},
                                    headers={"User-Agent": DEFAULT_USER_AGENT}, timeout=30)
            response.raise_for_status()
            payload = response.json()
            if not payload.get("query", {}).get("rightsinfo", {}).get("text"):
                raise ValueError("Wikipedia did not provide rights information")
            _write(path, payload)
        receipts.append(fingerprint_file(root, path).model_dump())
    result = {"spec_id": spec.spec_id, "source_count": len(spec.sources), "rights_receipts": receipts,
              "rights_review": "pending_human_review", "test_usage": "prohibited_for_reserved_development_families"}
    if not (root / "capture_summary.json").exists():
        _write(root / "capture_summary.json", result)
    elif json.loads((root / "capture_summary.json").read_text(encoding="utf-8")) != result:
        raise ValueError("Captured rights receipts changed; use a new development root")
    return result


def select_content_page(gt: dict) -> tuple[int, dict]:
    """Choose without looking at model output; report what the selected page contains."""
    choices = []
    for page in gt["pages"]:
        number = page["page_number"]
        elements = [e for e in gt["elements"] if e.get("bbox", {}).get("page") == number]
        counts = Counter(e["type"] for e in elements)
        presence = int(counts["image"] > 0) + int(counts["table"] > 0)
        choices.append(((presence, counts["text_line"], -number), number, dict(counts)))
    _, number, counts = max(choices)
    if not counts.get("text_line"):
        raise ValueError("Selected development page has no text lines")
    return number, counts


def _controlled_figure(path):
    # A reproducible computational graphic without unannotated letters or numerals.
    image = Image.new("RGB", (800, 320), "white")
    draw = ImageDraw.Draw(image)
    draw.line((35, 280, 760, 280), fill="#333333", width=3)
    for index, height in enumerate((95, 180, 130, 220, 155)):
        x = 65 + index * 135
        draw.rectangle((x, 280 - height, x + 80, 279), fill=("#177fa3", "#b34d63", "#38946c")[index % 3])
    image.save(path, format="PNG")


def build_development_corpus(spec: DevelopmentSpec, root: Path) -> DatasetManifest:
    frozen = DevelopmentSpec.model_validate_json((root / "development_spec.json").read_text(encoding="utf-8"))
    if frozen != spec:
        raise ValueError("Capture and build specifications differ")
    output = root / "dataset"
    if output.exists() and any(output.iterdir()):
        raise ValueError("Development dataset must be new or empty; use a new root for changes")
    for source in spec.sources:
        verify_wikipedia_source(root / "sources" / source.language / source.article_id, reparse=True)
    summary = json.loads((root / "capture_summary.json").read_text(encoding="utf-8"))
    for data in summary["rights_receipts"]:
        if fingerprint_file(root, root / data["path"]).model_dump() != data:
            raise ValueError("Captured rights receipt changed")
    figure = root / "controlled_figure.png"
    if not figure.exists():
        _controlled_figure(figure)
    selections = []
    for source in spec.sources:
        directory = output / source.language / source.article_id
        figure_caption, table_caption = spec.labels[source.language]
        table = {"caption": table_caption, "header_rows": 2, "column_weights": [1.5, 1, 1, 1], "rows": [
            [{"text": "A", "rowspan": 2, "is_header": True}, {"text": "B", "colspan": 3, "is_header": True}],
            [{"text": "B1", "is_header": True}, {"text": "B2", "is_header": True}, {"text": "B3", "is_header": True}],
            *[[{"text": str(value)} for value in (i, i * 3, i * 7, i * 11)] for i in range(1, 5)]]}
        validate_table(table)
        recipe = CompositionRecipe(text_items=spec.text_items, max_item_characters=spec.max_item_characters,
                                   figure_caption=figure_caption, table=table, text_filter=spec.text_filter)
        create_derived_source(root / "sources" / source.language / source.article_id, directory,
                              recipe=recipe, figure_path=figure)
        for template in spec.templates:
            target = directory / template
            with contextlib.redirect_stdout(io.StringIO()):
                rendered = capture_render_snapshot(directory / "source.json", target, template=template)
            gt = json.loads(Path(rendered["gt_path"]).read_text(encoding="utf-8"))
            page, counts = select_content_page(gt)
            pdf_to_noisy_dataset(rendered["pdf_path"], rendered["gt_path"], target / "noisy" / f"page_{page:03d}",
                                 page_index=page - 1, n_variants=1, seed=spec.seed, dpi=spec.dpi, profiles=spec.profiles)
            selections.append({"language": source.language, "article_id": source.article_id, "family_id": source.family_id,
                               "template": template, "page": page, "page_element_counts": counts})
            print(f"Build [{len(selections)}/{len(spec.sources) * len(spec.templates)}] "
                  f"{source.language}/{source.article_id}/{template}: page {page}", flush=True)
    manifest = build_manifest(output)
    expected = len(selections) * len(spec.profiles)
    if manifest.issues or len(manifest.records) != expected or verify_manifest(manifest, output):
        raise ValueError("Development candidate inventory failed or its matrix is incomplete")
    _write(root / "manifest.json", manifest.model_dump())
    catalog = draft_source_catalog(manifest)
    family_by_key = {(s.language, s.article_id): s.family_id for s in spec.sources}
    grouped = {}
    for family in catalog.families:
        for member in family.members:
            grouped.setdefault(family_by_key[(member.language, member.article_id)], []).append(member)
    catalog = SourceFamilyCatalog(families=[SourceFamily(family_id=key, members=members) for key, members in sorted(grouped.items())])
    # Family IDs are a draft research decision, never a reviewed split assignment.
    _write(root / "source_families.draft.json", catalog.model_dump())
    _write(root / "page_selection.json", {"spec_id": spec.spec_id, "algorithm": spec.page_selection, "pages": selections})
    _write(root / "development_summary.json", {"spec_id": spec.spec_id, "status": "candidate_not_approved",
           "base_pages": len(selections), "images": len(manifest.records), "sources": len(spec.sources),
           "families_proposed": sorted({s.family_id for s in spec.sources}), "manifest": fingerprint_file(root, root / "manifest.json").model_dump(),
           "rights": "pending", "human_gt_review": "pending", "evaluation_policy": "pending", "severity": "pending"})
    return manifest
