"""Command line interface for PolyDocBench."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from polydocbench.sources.wikipedia import WikipediaParser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="polydocbench", description="PolyDocBench research toolkit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_wiki = subparsers.add_parser("parse-wiki", help="Parse a Wikipedia page into PolyDocBench JSON")
    parse_wiki.add_argument("url", help="Wikipedia article URL")
    parse_wiki.add_argument("-o", "--output", required=True, help="Output JSON path")
    parse_wiki.add_argument("--debug", action="store_true", help="Print parser debug messages")

    capture_wiki = subparsers.add_parser(
        "capture-wiki", help="Capture a revision-bound Wikipedia source and raw MediaWiki evidence"
    )
    capture_wiki.add_argument("url", help="Wikipedia article URL or permanent oldid URL")
    capture_wiki.add_argument("-o", "--output-dir", required=True, help="New or empty source directory")
    capture_wiki.add_argument("--revision-id", type=int, default=None, help="Optional positive MediaWiki revision ID")

    verify_wiki = subparsers.add_parser(
        "verify-wiki-source", help="Verify a captured Wikipedia source without network access"
    )
    verify_wiki.add_argument("source_dir")
    verify_wiki.add_argument("--reparse", action="store_true", help="Also require the current parser/environment to reproduce source.json")

    templates = subparsers.add_parser("list-templates", help="List available layout templates")
    templates.add_argument("--config", default="configs/layout_templates.yaml", help="Template config path")

    render = subparsers.add_parser("render", help="Render parsed JSON")
    render.add_argument("json_path", help="Parsed source JSON")
    render.add_argument("-o", "--output", required=True, help="Output PDF path")
    render.add_argument("--template", default="simple_article", help="Layout template name")
    render.add_argument("--font", default="DejaVu Sans/DejaVuSans.ttf", help="Font path")
    render.add_argument("--debug", action="store_true", help="Render debug bboxes")

    snapshot = subparsers.add_parser("render-snapshot", help="Seal source/config/fonts/assets/code and render a benchmark document")
    snapshot.add_argument("json_path")
    snapshot.add_argument("-o", "--output-dir", required=True, help="New or empty document directory")
    snapshot.add_argument("--template", default="simple_article")
    snapshot.add_argument("--layout-config", default="configs/layout_templates.yaml")
    snapshot.add_argument("--render-config", default=None)
    snapshot.add_argument("--font", default="DejaVu Sans/DejaVuSans.ttf")
    snapshot.add_argument("--allow-downloads", action="store_true", help="Allow explicit URL asset capture; subsequent render is local")

    verify = subparsers.add_parser("verify-render-snapshot", help="Verify sealed render inputs and PDF/GT hashes")
    verify.add_argument("snapshot_dir")
    replay = subparsers.add_parser("replay-render-snapshot", help="Verify and rerender sealed inputs with matching code/environment")
    replay.add_argument("snapshot_dir")
    replay.add_argument("-o", "--output-dir", required=True, help="New or empty replay directory")

    overlay = subparsers.add_parser("draw-gt-overlay", help="Draw noisy-image GT polygons and/or bboxes over an image")
    overlay.add_argument("image_path", help="Input noisy image path")
    overlay.add_argument("gt_path", help="Input noisy-image GT JSON path")
    overlay.add_argument("-o", "--output", required=True, help="Output image path")
    overlay.add_argument("--mode", choices=["polygon", "bbox", "both"], default="polygon", help="Overlay mode")
    overlay.add_argument("--polygon-color", default="red", help="Polygon line color")
    overlay.add_argument("--bbox-color", default="blue", help="BBox line color")
    overlay.add_argument("--line-width", type=int, default=2, help="Overlay line width in pixels")

    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_console_encoding()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "parse-wiki":
        wiki_parser = WikipediaParser(debug=args.debug)
        data = wiki_parser.parse_from_url(args.url)
        if "error" in data:
            parser.error(data["error"])
        wiki_parser.save_to_file(data, args.output)
        print(f"Parsed '{data.get('title', '')}' with {len(data.get('content', []))} top-level items -> {args.output}")
        return 0

    if args.command == "capture-wiki":
        from polydocbench.sources import capture_wikipedia_source

        result = capture_wikipedia_source(args.url, args.output_dir, revision_id=args.revision_id)
        print(f"Source: {result['source_path']}")
        print(f"Revision: {result['revision_id']}")
        print(f"Snapshot: {result['snapshot_id']}")
        return 0

    if args.command == "verify-wiki-source":
        from polydocbench.sources import verify_wikipedia_source

        evidence = verify_wikipedia_source(args.source_dir, reparse=args.reparse)
        print(f"Wikipedia source verified: revision={evidence.inputs.revision_id} snapshot={evidence.inputs.snapshot_id}")
        return 0

    if args.command == "list-templates":
        from polydocbench.layout.templates import list_template_names

        for name in list_template_names(args.config):
            print(name)
        return 0

    if args.command == "render":
        from polydocbench.layout import LayoutEngine
        from polydocbench.render import PDFRenderer

        font_path = Path(args.font)
        layout_engine = LayoutEngine(font_path=font_path if font_path.exists() else None)
        layout_result = layout_engine.layout_document(args.json_path, template_name=args.template)
        result = PDFRenderer(debug=args.debug).render(layout_result, args.output)
        print(f"PDF: {result['pdf_path']}")
        print(f"GT : {result['gt_path']}")
        return 0

    if args.command == "draw-gt-overlay":
        from polydocbench.noise import draw_gt_overlay

        output_path = draw_gt_overlay(
            image_path=args.image_path,
            gt_path=args.gt_path,
            output_path=args.output,
            mode=args.mode,
            polygon_color=args.polygon_color,
            bbox_color=args.bbox_color,
            line_width=args.line_width,
        )
        print(f"Overlay: {output_path}")
        return 0

    if args.command == "render-snapshot":
        from polydocbench.benchmark import capture_render_snapshot

        result = capture_render_snapshot(args.json_path, args.output_dir, template=args.template,
                                         layout_config_path=args.layout_config, render_config_path=args.render_config,
                                         font_path=args.font, allow_downloads=args.allow_downloads)
        print(f"PDF: {result['pdf_path']}")
        print(f"GT: {result['gt_path']}")
        print(f"Provenance: {result['provenance_path']}")
        return 0

    if args.command == "verify-render-snapshot":
        from polydocbench.benchmark import verify_render_snapshot

        evidence = verify_render_snapshot(args.snapshot_dir)
        print(f"Render snapshot verified: {evidence.inputs.snapshot_id}")
        return 0

    if args.command == "replay-render-snapshot":
        from polydocbench.benchmark import replay_render_snapshot

        result = replay_render_snapshot(args.snapshot_dir, args.output_dir)
        print(f"Byte-identical PDF/GT replay verified: {result['render_snapshot_id']}")
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


def _configure_console_encoding() -> None:
    """Use UTF-8 output on Windows cp1251 consoles."""

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    raise SystemExit(main())
