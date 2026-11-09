"""Generate offline table/figure/continuation fixtures, not a publication corpus."""

import argparse
import contextlib
import io
import json
from pathlib import Path

from polydocbench.benchmark.manifest import DatasetManifest, build_manifest, verify_manifest
from polydocbench.layout import LayoutEngine
from polydocbench.layout.content_loader import ContentLoader
from polydocbench.noise import load_noise_config, pdf_to_noisy_dataset
from polydocbench.provenance import fingerprint_file
from polydocbench.render import PDFRenderer


def prepare_fixture_dataset(output: Path, templates: list[str], dpi: int = 200, seed: int = 42,
                            text_manifest: Path | None = None, text_input_dir: Path | None = None):
    if (text_manifest is None) != (text_input_dir is None):
        raise ValueError("Provide both text manifest and text input directory")
    inventory = None
    if text_manifest is not None:
        inventory = DatasetManifest.model_validate_json(text_manifest.read_text(encoding="utf-8"))
        for record in inventory.records:
            parts = Path(record.source.path).parts
            if len(parts) != 3 or record.language != parts[0] or parts[-1] != "source.json":
                raise ValueError("Language/source path mismatch in text fixture inventory")
        if inventory.issues or verify_manifest(inventory, text_input_dir):
            raise ValueError("Text fixture inventory must pass integrity verification")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Fixture output must be new or empty")
    if not templates or len(set(templates)) != len(templates) or dpi < 36 or seed < 0:
        raise ValueError("Use unique templates, DPI >= 36 and nonnegative seed")
    # Template names are used as relative directory components.
    from polydocbench.layout.templates import load_layout_templates

    if set(templates) - set(load_layout_templates()["templates"]):
        raise ValueError("Unknown fixture template")
    output.mkdir(parents=True, exist_ok=True)
    case = output / "en" / "complex_gt_audit"
    case.mkdir(parents=True)
    original = Path("examples/complex_document.json").resolve(strict=True)
    document = json.loads(original.read_text(encoding="utf-8"))
    for item in document["content"]:
        if item["type"] == "image":
            item["src"] = str((original.parent / item["src"]).resolve(strict=True))
    document["metadata"] = {"audit_fixture_only": True, "original": fingerprint_file(Path.cwd(), original).model_dump()}
    source = case / "source.json"
    source.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    config = load_noise_config("configs/gt_audit_noise.json")
    profiles = ["clean", "medium_scan", "heavy_scan", *config.profiles]
    for template in templates:
        directory = case / template
        directory.mkdir()
        with contextlib.redirect_stdout(io.StringIO()):
            layout = LayoutEngine(font_path="DejaVu Sans/DejaVuSans.ttf").layout_document(source, template)
            rendered = PDFRenderer(debug=False).render(layout, directory / "document.pdf")
        if layout.warnings:
            raise ValueError(f"Fixture contains layout warnings: {layout.warnings}")
        for page in range(len(layout.pages)):
            pdf_to_noisy_dataset(rendered["pdf_path"], rendered["gt_path"], directory / "noisy" / f"page_{page + 1:03d}",
                                 page_index=page, n_variants=1, dpi=dpi, seed=seed, profiles=profiles, config=config)
        print(f"Fixture {template}: {len(layout.pages)} pages / {len(layout.pages) * len(profiles)} scans", flush=True)
    if text_manifest is not None:
        selected = {}
        for record in sorted(inventory.records, key=lambda r: (r.language, r.article_id, r.source.sha256)):
            selected.setdefault(record.language, record)
        text_templates = ["simple_article", "scientific_paper", "magazine_layout"]
        for index, (language, record) in enumerate(sorted(selected.items())):
            with contextlib.redirect_stdout(io.StringIO()):
                items = ContentLoader.load_json(text_input_dir / record.source.path)
            items = [item for item in items if item["type"] == "paragraph" or item["type"].startswith("heading")][:6]
            if not items:
                raise ValueError(f"No text blocks for {language}")
            case = output / language / "text_gt_audit"
            case.mkdir(parents=True)
            source = case / "source.json"
            source.write_text(json.dumps({"schema_version": "0.1", "title": f"{language} GT text fixture",
                "elements": items, "metadata": {"audit_fixture_only": True, "selection": "first_6_normalized_text_items",
                "original_source": record.source.model_dump(), "not_a_full_source_reconstruction": True}},
                ensure_ascii=False, indent=2), encoding="utf-8")
            template = text_templates[index % len(text_templates)]
            directory = case / template
            directory.mkdir()
            with contextlib.redirect_stdout(io.StringIO()):
                layout = LayoutEngine(font_path="DejaVu Sans/DejaVuSans.ttf").layout_document(source, template)
                rendered = PDFRenderer(debug=False).render(layout, directory / "document.pdf")
            if layout.warnings:
                raise ValueError(f"Text fixture contains layout warnings: {layout.warnings}")
            for page in range(len(layout.pages)):
                pdf_to_noisy_dataset(rendered["pdf_path"], rendered["gt_path"], directory / "noisy" / f"page_{page + 1:03d}",
                                     page_index=page, n_variants=1, dpi=dpi, seed=seed, profiles=profiles, config=config)
            print(f"Text fixture {language}/{template}: {len(layout.pages)} pages", flush=True)
    inventory = build_manifest(output)
    if inventory.issues:
        raise ValueError(f"Fixture inventory rejected artifacts: {inventory.issues[0].message}")
    (output / "manifest.json").write_text(inventory.model_dump_json(indent=2), encoding="utf-8")
    return inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--templates", nargs="+", default=["technical_report", "research_illustrated", "magazine_feature", "reference_sheet"])
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--text-sources-manifest", type=Path)
    parser.add_argument("--text-input-dir", type=Path)
    args = parser.parse_args()
    manifest = prepare_fixture_dataset(args.output_dir, args.templates, args.dpi, args.seed,
                                        args.text_sources_manifest, args.text_input_dir)
    print(json.dumps(manifest.summary(), indent=2))


if __name__ == "__main__":
    main()
