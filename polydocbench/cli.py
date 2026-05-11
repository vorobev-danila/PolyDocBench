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

    templates = subparsers.add_parser("list-templates", help="List available layout templates")
    templates.add_argument("--config", default="configs/layout_templates.yaml", help="Template config path")

    render = subparsers.add_parser("render", help="Render parsed JSON")
    render.add_argument("json_path", help="Parsed source JSON")
    render.add_argument("-o", "--output", required=True, help="Output PDF path")
    render.add_argument("--template", default="simple_article", help="Layout template name")
    render.add_argument("--font", default="DejaVu Sans/DejaVuSans.ttf", help="Font path")
    render.add_argument("--debug", action="store_true", help="Render debug bboxes")

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

    parser.error(f"Unknown command: {args.command}")
    return 2


def _configure_console_encoding() -> None:
    """Use UTF-8 output on Windows cp1251 consoles."""

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    raise SystemExit(main())
