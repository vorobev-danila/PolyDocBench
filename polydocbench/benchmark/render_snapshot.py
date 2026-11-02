"""Opt-in, sealed inputs for offline benchmark rendering and verification."""

from __future__ import annotations

import copy
import json
import platform
import shutil
import subprocess
import tempfile
from importlib.metadata import distributions
from pathlib import Path
from typing import Any, Literal
from xml.etree import ElementTree

import yaml
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator
from reportlab.pdfbase import pdfmetrics

from polydocbench.document.assets import image_dimensions, resolve_image
from polydocbench.document.fonts import FALLBACK_FONT, font_fallback_scope
from polydocbench.document.normalize import flatten_source_content
from polydocbench.document.schema import validate_source_document
from polydocbench.layout import LayoutEngine
from polydocbench.layout.templates import DEFAULT_TEMPLATE_PATH, resolve_template_path
from polydocbench.render import PDFRenderer
from polydocbench.render.config import RenderConfig

from .files import FileFingerprint, fingerprint_file, json_sha256


ROOT = Path(__file__).resolve().parents[2]
RESOURCE_KEYS = ("src", "path", "url", "image_src")
PROVENANCE_NAME = "document_provenance.json"


class SnapshotFile(FileFingerprint):
    role: Literal["original_source", "prepared_source", "original_config", "layout_config", "render_config",
                  "font", "asset", "license", "generator_code", "toolchain"]


class AssetReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str
    original_reference: str
    snapshot_path: str


class RenderInputSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    schema_version: Literal["0.1"]
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    template: str
    files: list[SnapshotFile]
    assets: list[AssetReference]
    fonts: dict[str, str]
    environment: dict[str, str]
    generator_revision: str | None
    generator_dirty: bool | None
    source_url: str
    source_revision_status: Literal["not_verified"]
    rights_review_status: Literal["not_reviewed"]

    @model_validator(mode="after")
    def validate_seal(self) -> "RenderInputSnapshot":
        if self.snapshot_id != json_sha256(self.model_dump(exclude={"snapshot_id"})):
            raise ValueError("Render snapshot ID does not match its input records")
        by_path = {file.path: file for file in self.files}
        if len(by_path) != len(self.files):
            raise ValueError("Duplicate paths in render snapshot")
        for role in ("original_source", "prepared_source", "layout_config", "render_config"):
            if sum(file.role == role for file in self.files) != 1:
                raise ValueError(f"Snapshot requires exactly one {role}")
        for family in ("DejaVuSans", FALLBACK_FONT):
            if family not in self.fonts:
                raise ValueError(f"Required font is absent: {family}")
        for path in self.fonts.values():
            if path not in by_path or by_path[path].role != "font":
                raise ValueError("Font reference is outside the sealed font files")
        for asset in self.assets:
            if asset.snapshot_path not in by_path or by_path[asset.snapshot_path].role != "asset":
                raise ValueError("Asset reference is outside the sealed asset files")
        if not any(file.role == "generator_code" for file in self.files):
            raise ValueError("Generator source snapshot is missing")
        return self


class RenderProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["0.1"]
    inputs: RenderInputSnapshot
    pdf: FileFingerprint
    gt: FileFingerprint


def _json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return data


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _copy_file(root: Path, source: Path, relative: str, role: str, files: dict[str, SnapshotFile]) -> str:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    files[relative] = SnapshotFile(**fingerprint_file(root, target).model_dump(), role=role)
    return relative


def _record_json(root: Path, relative: str, data: dict, role: str, files: dict) -> None:
    _write_json(root / relative, data)
    files[relative] = SnapshotFile(**fingerprint_file(root, root / relative).model_dump(), role=role)


def _environment() -> dict[str, str]:
    result = {"python": platform.python_version(), "platform": platform.platform(),
              "implementation": platform.python_implementation(), "machine": platform.machine()}
    packages = {}
    for distribution in distributions():
        name = distribution.metadata.get("Name")
        if name:
            name = name.lower().replace("_", "-").replace(".", "-")
            if name in packages and packages[name] != distribution.version:
                raise ValueError(f"Conflicting installed distribution versions: {name}")
            packages[name] = distribution.version
    result.update({f"package:{name}": value for name, value in sorted(packages.items())})
    return result


def _generator_state() -> tuple[str | None, bool | None]:
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        state = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--",
                                "polydocbench", "configs", "pyproject.toml", "uv.lock"],
                               cwd=ROOT, capture_output=True, text=True, check=True).stdout
        return revision, bool(state)
    except (OSError, subprocess.CalledProcessError):
        return None, None


def _validate_asset(path: Path) -> str:
    image_dimensions(path)
    try:
        with Image.open(path) as image:
            suffix = {"PNG": ".png", "JPEG": ".jpg", "GIF": ".gif", "TIFF": ".tiff", "BMP": ".bmp"}.get(image.format)
            image.verify()
        if suffix is None:
            raise ValueError("Unsupported raster asset format")
        return suffix
    except OSError:
        root = ElementTree.parse(path).getroot()
        if root.tag.split("}")[-1] != "svg":
            raise ValueError("Unsupported non-raster asset")
        for element in root.iter():
            if element.tag.split("}")[-1] in {"text", "script", "foreignObject"}:
                raise ValueError("Snapshot SVGs must be self-contained graphics without text/script dependencies")
            for key, value in element.attrib.items():
                if key == "{http://www.w3.org/XML/1998/namespace}base" and value:
                    raise ValueError("SVG xml:base references are not supported in input snapshots")
                if key.split("}")[-1] == "href" and value and not value.startswith("#"):
                    raise ValueError("External SVG references cannot be sealed; embed/rasterize the asset first")
                if "url(" in value.lower() or "@import" in value.lower() or "@font-face" in value.lower():
                    raise ValueError("SVG stylesheet references are not supported in input snapshots")
            if element.tag.split("}")[-1] == "style" and element.text:
                if any(token in element.text.lower() for token in ("url(", "@import", "@font-face")):
                    raise ValueError("External SVG styles are not supported in input snapshots")
        return ".svg"


def _freeze_assets(data, source_dir, root, files, references, allow_downloads, location=""):
    if isinstance(data, list):
        for index, value in enumerate(data):
            _freeze_assets(value, source_dir, root, files, references, allow_downloads, f"{location}/{index}")
    elif isinstance(data, dict):
        if data.get("type") in {"image", "formula"}:
            containers = [data, data.get("metadata", {}), data.get("dimensions", {})]
            reference = next((str(container[key]) for container in containers if isinstance(container, dict)
                              for key in RESOURCE_KEYS if container.get(key)), "")
            if not reference:
                raise ValueError(f"A snapshot requires a renderable asset for {data['type']} at {location}")
            if reference.startswith(("http://", "https://")):
                if not allow_downloads:
                    raise ValueError(f"Network asset requires explicit --allow-downloads: {reference}")
                path = resolve_image(reference)
            else:
                path = Path(reference)
                if not path.is_file():
                    path = source_dir / reference
            if path is None or not path.is_file():
                raise ValueError(f"Asset could not be snapshotted: {reference}")
            suffix = _validate_asset(path)
            digest = fingerprint_file(path.parent, path).sha256
            relative = f"inputs/assets/{digest}{suffix}"
            if relative not in files:
                _copy_file(root, path, relative, "asset", files)
            references.append(AssetReference(location=location, original_reference=reference, snapshot_path=relative))
            for container in containers:
                if isinstance(container, dict):
                    for key in RESOURCE_KEYS:
                        container.pop(key, None)
            data["src"] = relative
        for key, value in list(data.items()):
            if key not in {"metadata", "dimensions"}:
                _freeze_assets(value, source_dir, root, files, references, allow_downloads, f"{location}/{key}")


def _font_file(root, path, files) -> str:
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Required font is missing: {path}")
    digest = fingerprint_file(path.parent, path).sha256
    relative = f"inputs/fonts/{digest}{path.suffix.lower()}"
    if relative not in files:
        _copy_file(root, path, relative, "font", files)
    for name in ("LICENSE.txt", "COPYRIGHT.txt", "OFL.txt"):
        license_path = path.parent / name
        if license_path.is_file():
            license_hash = fingerprint_file(path.parent, license_path).sha256
            license_relative = f"inputs/licenses/{license_hash}.txt"
            if license_relative not in files:
                _copy_file(root, license_path, license_relative, "license", files)
    return relative


def _assert_registered_fonts(root, snapshot):
    by_path = {file.path: file for file in snapshot.files}
    for family, relative in snapshot.fonts.items():
        if family in pdfmetrics.getRegisteredFontNames():
            registered = pdfmetrics.getFont(family)
            filename = getattr(registered.face, "filename", None)
            if not filename or not Path(filename).is_file():
                raise ValueError(f"Cannot verify already registered font {family}; use a fresh process")
            actual = fingerprint_file(Path(filename).parent, Path(filename)).sha256
            if actual != by_path[relative].sha256:
                raise ValueError(f"Already registered font differs from snapshot: {family}; use a fresh process")


def _assert_runtime(snapshot):
    if snapshot.environment != _environment():
        raise ValueError("Render environment differs from snapshot; restore the recorded package versions/platform")
    code_files = {file.path.removeprefix("generator/"): file for file in snapshot.files if file.role == "generator_code"}
    current = {path.relative_to(ROOT).as_posix() for path in (ROOT / "polydocbench").rglob("*.py")}
    if current != set(code_files):
        raise ValueError("Installed generator file set differs from the snapshot")
    for relative, expected in code_files.items():
        if fingerprint_file(ROOT, ROOT / relative).sha256 != expected.sha256:
            raise ValueError(f"Installed generator differs from snapshot: {relative}")


def _normalise_gt(data, root):
    if isinstance(data, dict):
        for key, value in list(data.items()):
            if key in {"src", "path", "image_src", "source_url"} and isinstance(value, str) and Path(value).is_absolute():
                try:
                    data[key] = Path(value).resolve().relative_to(root).as_posix()
                except ValueError:
                    pass
            else:
                _normalise_gt(value, root)
    elif isinstance(data, list):
        for value in data:
            _normalise_gt(value, root)


def _render_inputs(root: Path, snapshot: RenderInputSnapshot, output: Path) -> dict:
    _assert_runtime(snapshot)
    _assert_registered_fonts(root, snapshot)
    by_role = {file.role: file for file in snapshot.files}
    asset_paths = {file.path for file in snapshot.files if file.role == "asset"}
    font_paths = {file.path for file in snapshot.files if file.role == "font"}
    for relative in asset_paths:
        _validate_asset(root / relative)
    source = _json(root / by_role["prepared_source"].path)

    def absolute_assets(value):
        if isinstance(value, dict):
            if value.get("type") in {"image", "formula"}:
                if value.get("src") not in asset_paths:
                    raise ValueError("Prepared graphic references a file outside the sealed asset files")
                value["src"] = str((root / value["src"]).resolve())
            for key, child in value.items():
                if key not in {"metadata", "dimensions"}:
                    absolute_assets(child)
        elif isinstance(value, list):
            for child in value:
                absolute_assets(child)

    absolute_assets(source["elements"])
    config = _json(root / by_role["render_config"].path)
    for font in config["render"]["fonts"].values():
        if not font.get("embedded", True):
            continue
        for key in ("path", "bold_path", "italic_path"):
            if font.get(key):
                if font[key] not in font_paths:
                    raise ValueError("Render configuration references a file outside the sealed font files")
                font[key] = str((root / font[key]).resolve())
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pdb_render_") as temporary:
        temporary = Path(temporary)
        _write_json(temporary / "source.json", source)
        _write_json(temporary / "render.json", config)
        with font_fallback_scope(root / snapshot.fonts[FALLBACK_FONT]):
            renderer = PDFRenderer(config_path=temporary / "render.json", debug=False)
            layout = LayoutEngine(template_config_path=root / by_role["layout_config"].path,
                                  font_path=root / snapshot.fonts["DejaVuSans"]).layout_document(
                                      temporary / "source.json", snapshot.template)
            if layout.warnings:
                raise ValueError("Snapshot rendering refuses layout warnings")
            for element in layout.elements:
                if element.type == "formula" and element.metadata.get("role") == "block":
                    element.metadata["require_asset"] = True
            result = renderer.render(layout, output / "document.pdf")
    gt = _json(Path(result["gt_path"]))
    _normalise_gt(gt, root)
    gt["metadata"].update({"render_snapshot_id": snapshot.snapshot_id,
                           "timestamp": "1970-01-01T00:00:00Z", "export_time": "1970-01-01T00:00:00Z"})
    _write_json(Path(result["gt_path"]), gt)
    _assert_registered_fonts(root, snapshot)
    return result


def capture_render_snapshot(
    source_path: str | Path, output_dir: str | Path, *, template: str = "simple_article",
    layout_config_path: str | Path = DEFAULT_TEMPLATE_PATH,
    render_config_path: str | Path | None = None,
    font_path: str | Path = "DejaVu Sans/DejaVuSans.ttf", allow_downloads: bool = False,
) -> dict[str, Any]:
    """Seal exact source/config/font/asset/code copies, then render without network resources."""
    source_path = Path(source_path).resolve(strict=True)
    data = _json(source_path)
    document = validate_source_document(data)
    layout_path = resolve_template_path(layout_config_path)
    layout_config = yaml.safe_load(layout_path.read_text(encoding="utf-8"))
    if template not in layout_config.get("templates", {}):
        raise ValueError(f"Unknown snapshot template: {template}")
    selected = copy.deepcopy(layout_config["templates"][template])
    if selected.get("typography", {}).get("font_family", "DejaVuSans") != "DejaVuSans":
        raise ValueError("Snapshot rendering currently requires the DejaVuSans layout family")
    selected["strict_layout"] = True
    root = Path(output_dir).resolve()
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValueError("Snapshot output directory must be new or empty; existing artifacts are never overwritten")
    if render_config_path is not None and not Path(render_config_path).is_file():
        raise ValueError(f"Render configuration is missing: {render_config_path}")
    root.mkdir(parents=True, exist_ok=True)
    files, references = {}, []
    _copy_file(root, source_path, "inputs/source.original.json", "original_source", files)
    _copy_file(root, layout_path, "inputs/layout.original.yaml", "original_config", files)
    items = document.source_items()
    prepared = {"schema_version": document.schema_version, "title": document.title, "url": document.url,
                "elements": flatten_source_content(items) if document.content else items}
    _freeze_assets(prepared["elements"], source_path.parent, root, files, references, allow_downloads, "/elements")
    _record_json(root, "inputs/source.json", prepared, "prepared_source", files)
    _record_json(root, "inputs/layout.json", {"base_settings": layout_config.get("base_settings", {}),
                                             "templates": {template: selected}}, "layout_config", files)
    render = RenderConfig(render_config_path)
    if render_config_path:
        _copy_file(root, Path(render_config_path), "inputs/render.original.yaml", "original_config", files)
    effective = {"render": {"default_font": "dejavu", "default_font_size": render.get("render.default_font_size", 10),
                            "fonts": copy.deepcopy(render.get("render.fonts", {})),
                            "pdf": {"metadata": render.get("render.pdf.metadata", {}), "invariant": True},
                            "export": render.get("render.export", {})}}
    body_font = effective["render"]["fonts"].setdefault("dejavu", {})
    body_font.update({"family": "DejaVuSans", "embedded": True, "path": str(font_path)})
    fonts = {}
    for font in effective["render"]["fonts"].values():
        if not font.get("embedded", True):
            continue
        family = font.get("family")
        if not family:
            raise ValueError("Embedded font requires an explicit family")
        for key, suffix in (("path", ""), ("bold_path", "-Bold"), ("italic_path", "-Oblique")):
            if font.get(key):
                relative = _font_file(root, font[key], files)
                font[key] = relative
                if family + suffix in fonts and fonts[family + suffix] != relative:
                    raise ValueError(f"Conflicting font configuration for {family + suffix}")
                fonts[family + suffix] = relative
    fonts[FALLBACK_FONT] = _font_file(root, ROOT / "fonts/NotoSansSymbols2/NotoSansSymbols2-Regular.ttf", files)
    _record_json(root, "inputs/render.json", effective, "render_config", files)
    for path in sorted((ROOT / "polydocbench").rglob("*.py")):
        _copy_file(root, path, f"generator/{path.relative_to(ROOT).as_posix()}", "generator_code", files)
    for name in ("pyproject.toml", "uv.lock"):
        if (ROOT / name).is_file():
            _copy_file(root, ROOT / name, f"generator/{name}", "toolchain", files)
    revision, dirty = _generator_state()
    payload = {"schema_version": "0.1", "template": template,
               "files": [file.model_dump() for _, file in sorted(files.items())],
               "assets": [reference.model_dump() for reference in references], "fonts": fonts,
               "environment": _environment(), "generator_revision": revision, "generator_dirty": dirty,
               "source_url": str(data.get("url", "")), "source_revision_status": "not_verified",
               "rights_review_status": "not_reviewed"}
    snapshot = RenderInputSnapshot(snapshot_id=json_sha256(payload), **payload)
    _write_json(root / "render_inputs.json", snapshot.model_dump())
    result = _render_inputs(root, snapshot, root)
    provenance = RenderProvenance(schema_version="0.1", inputs=snapshot,
                                  pdf=fingerprint_file(root, Path(result["pdf_path"])),
                                  gt=fingerprint_file(root, Path(result["gt_path"])))
    _write_json(root / PROVENANCE_NAME, provenance.model_dump())
    return {**result, "provenance_path": str(root / PROVENANCE_NAME), "render_snapshot_id": snapshot.snapshot_id}


def verify_render_snapshot(root: str | Path, *, check_outputs: bool = True) -> RenderProvenance:
    root = Path(root).resolve(strict=True)
    provenance = RenderProvenance.model_validate(_json(root / PROVENANCE_NAME))
    declared = RenderInputSnapshot.model_validate(_json(root / "render_inputs.json"))
    if declared != provenance.inputs:
        raise ValueError("Render input snapshot differs from its output provenance")
    files = list(provenance.inputs.files)
    if check_outputs:
        files.extend((provenance.pdf, provenance.gt))
    for file in files:
        actual = fingerprint_file(root, root / file.path)
        if actual.model_dump() != file.model_dump(include={"path", "sha256", "size_bytes"}):
            raise ValueError(f"Render snapshot file differs: {file.path}")
    if check_outputs:
        gt = _json(root / provenance.gt.path)
        if gt.get("metadata", {}).get("render_snapshot_id") != provenance.inputs.snapshot_id:
            raise ValueError("Output GT is not bound to the render input snapshot")
    return provenance


def replay_render_snapshot(root: str | Path, output_dir: str | Path) -> dict[str, Any]:
    root, output = Path(root).resolve(strict=True), Path(output_dir).resolve()
    provenance = verify_render_snapshot(root, check_outputs=False)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Replay output directory must be new or empty")
    result = _render_inputs(root, provenance.inputs, output)
    for key, expected in (("pdf_path", provenance.pdf), ("gt_path", provenance.gt)):
        if fingerprint_file(output, Path(result[key])).sha256 != expected.sha256:
            raise ValueError(f"Replay output differs from the recorded file: {key}")
    return {**result, "render_snapshot_id": provenance.inputs.snapshot_id, "replay_verified": True}
