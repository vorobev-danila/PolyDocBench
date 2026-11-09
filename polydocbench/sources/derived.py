"""Replayable controlled compositions derived from revision-bound Wikipedia text."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, model_serializer

from polydocbench.document.normalize import flatten_source_content
from polydocbench.document.schema import validate_source_document
from polydocbench.provenance import FileFingerprint, fingerprint_file, json_sha256
from .snapshots import PROVENANCE_NAME as WIKI_PROVENANCE, verify_wikipedia_source

PROVENANCE_NAME = "derived_source_provenance.json"


class CompositionRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    algorithm: Literal["text_prefix_with_controlled_media_v1"] = "text_prefix_with_controlled_media_v1"
    text_items: int = Field(default=12, ge=2, le=50, strict=True)
    max_item_characters: int = Field(default=1200, ge=100, le=10000, strict=True)
    figure_caption: str = Field(min_length=1)
    table: dict
    text_filter: Literal["all_text", "prose_without_tex_or_navigation_v1"] = "all_text"

    @model_serializer(mode="wrap")
    def keep_existing_recipes(self, handler):
        result = handler(self)
        if self.text_filter == "all_text":
            result.pop("text_filter", None)
        return result


class DerivedSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["0.1"] = "0.1"
    derivation_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    recipe: CompositionRecipe
    files: list[FileFingerprint]
    source: FileFingerprint
    rights_status: Literal["pending_human_review"] = "pending_human_review"

    @model_validator(mode="after")
    def validate_seal(self):
        if self.derivation_id != json_sha256(self.model_dump(exclude={"derivation_id", "source"})):
            raise ValueError("Derived source seal differs from its inputs")
        paths = [f.path for f in self.files]
        expected = {f"origin/{name}" for name in (WIKI_PROVENANCE, "source.json", "query.json", "parse.json", "page.html")}
        if set(paths) != expected | {"assets/controlled_figure.png"} or len(paths) != len(set(paths)):
            raise ValueError("Derived source must preserve every parent evidence file and its figure")
        if self.source.path != "source.json":
            raise ValueError("Derived output must be source.json")
        return self


def _composition(parent: dict, recipe: CompositionRecipe, derivation_id: str) -> dict:
    document = validate_source_document(parent)
    items = flatten_source_content(document.source_items()) if document.content else document.source_items()
    selected = []
    skipped = []
    for index, item in enumerate(items):
        if item.get("type") != "paragraph" and not str(item.get("type", "")).startswith("heading"):
            continue
        original = str(item.get("content", "")).strip()
        if not original:
            continue
        if recipe.text_filter == "prose_without_tex_or_navigation_v1":
            reason = None
            if "\\" in original:
                reason = "tex_or_backslash_fragment"
            elif "\u27a4" in original or item.get("metadata", {}).get("source_type") == "hatnote":
                reason = "navigation_marker_or_hatnote"
            if reason:
                skipped.append({"parent_flat_index": index, "reason": reason})
                continue
        text = original
        if len(text) > recipe.max_item_characters:
            text = text[:recipe.max_item_characters].rsplit(" ", 1)[0]
        selected.append({"type": item["type"], "content": text,
                         "metadata": {"parent_flat_index": index, "prefix_truncated": text != original,
                                      "parent_item_sha256": json_sha256({"text": original})}})
        if len(selected) == recipe.text_items:
            break
    if len(selected) < 2:
        raise ValueError("Composition requires at least two nonempty source text items")
    figure = {"type": "image", "src": "assets/controlled_figure.png", "caption": recipe.figure_caption}
    table = {**copy.deepcopy(recipe.table), "type": "table"}
    # Keep source text order while putting controlled media early enough for page sampling.
    result = {"schema_version": "0.1", "title": document.title, "url": document.url,
              "elements": [*selected[:2], figure, table, *selected[2:]],
              "metadata": {"derived_source_id": derivation_id,
                           "composition_kind": "wikipedia_text_excerpt_with_synthetic_media",
                           "not_a_full_article": True, "original_media_omitted": True}}
    validate_source_document(result)
    if recipe.text_filter != "all_text":
        result["metadata"]["text_filter"] = recipe.text_filter
        result["metadata"]["skipped_text_items"] = skipped
    return result


def create_derived_source(parent_dir: str | Path, output_dir: str | Path, *, recipe: CompositionRecipe,
                          figure_path: str | Path) -> DerivedSource:
    parent, output = Path(parent_dir).resolve(strict=True), Path(output_dir).resolve()
    evidence = verify_wikipedia_source(parent, reparse=True)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Derived source output must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    (output / "origin").mkdir()
    (output / "assets").mkdir()
    for name in (WIKI_PROVENANCE, "source.json", "query.json", "parse.json", "page.html"):
        shutil.copyfile(parent / name, output / "origin" / name)
    shutil.copyfile(figure_path, output / "assets/controlled_figure.png")
    files = [fingerprint_file(output, p) for p in sorted((output / "origin").iterdir())]
    files.append(fingerprint_file(output, output / "assets/controlled_figure.png"))
    payload = {"schema_version": "0.1", "parent_snapshot_id": evidence.inputs.snapshot_id,
               "recipe": recipe.model_dump(), "files": [f.model_dump() for f in files],
               "rights_status": "pending_human_review"}
    identity = json_sha256(payload)
    source = _composition(json.loads((parent / "source.json").read_text(encoding="utf-8")), recipe, identity)
    (output / "source.json").write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = DerivedSource(derivation_id=identity, source=fingerprint_file(output, output / "source.json"), **payload)
    (output / PROVENANCE_NAME).write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return result


def verify_derived_source(root: str | Path) -> DerivedSource:
    root = Path(root).resolve(strict=True)
    result = DerivedSource.model_validate_json((root / PROVENANCE_NAME).read_text(encoding="utf-8"))
    for file in [*result.files, result.source]:
        if fingerprint_file(root, root / file.path) != file:
            raise ValueError(f"Derived source file changed: {file.path}")
    parent = verify_wikipedia_source(root / "origin")
    if parent.inputs.snapshot_id != result.parent_snapshot_id:
        raise ValueError("Derived source refers to another Wikipedia revision")
    actual = json.loads((root / "source.json").read_text(encoding="utf-8"))
    expected = _composition(json.loads((root / "origin/source.json").read_text(encoding="utf-8")),
                            result.recipe, result.derivation_id)
    if expected != actual:
        raise ValueError("Derived source does not replay from its sealed recipe")
    return result
