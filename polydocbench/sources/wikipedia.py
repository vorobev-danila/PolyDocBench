"""Wikipedia HTML parser for PolyDocBench source documents.

The parser produces the normalized JSON shape consumed by the layout engine:

```
{
  "title": "...",
  "url": "...",
  "content": [
    {"type": "paragraph", "text": "..."},
    {"type": "heading", "level": 2, "text": "...", "content": [...]}
  ]
}
```

Internally the code is split into small extractors so adding support for new
Wikipedia elements does not require editing one very large method.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from polydocbench.document.schema import FORMAT_SCHEMA_VERSION


DEFAULT_USER_AGENT = (
    "PolyDocBench/0.1 "
    "(https://github.com/vorobev-danila/PolyDocBench; danila_vorobev_02@list.ru)"
)

CONTENT_TAGS = {
    "div",
    "dl",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ol",
    "p",
    "section",
    "table",
    "ul",
}

SKIP_CLASSES = {
    "ambox",
    "authority-control",
    "metadata",
    "mw-editsection",
    "mw-empty-elt",
    "navbox",
    "noprint",
    "reference",
    "reflist",
    "sidebar",
    "sistersitebox",
    "toc",
    "vertical-navbox",
}


@dataclass(frozen=True)
class HeadingInfo:
    level: int
    text: str
    element_id: str


class WikipediaParser:
    """Parse Wikipedia HTML into the normalized content structure."""

    def __init__(
        self,
        debug: bool = False,
        timeout: float = 30.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.debug = debug
        self.timeout = timeout
        self.user_agent = user_agent
        self.soup: BeautifulSoup | None = None

    def parse_from_url(self, url: str) -> dict[str, Any]:
        """Download and parse a Wikipedia article page."""

        import requests

        try:
            response = requests.get(url, headers={"User-Agent": self.user_agent}, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            return {"error": f"Failed to download Wikipedia page: {exc}"}

        return self.parse_html(response.text, url=url)

    def parse_from_file(self, file_path: str | Path, url: str = "") -> dict[str, Any]:
        """Parse a saved Wikipedia HTML file."""

        try:
            html = Path(file_path).read_text(encoding="utf-8")
        except OSError as exc:
            return {"error": f"Failed to read HTML file: {exc}"}

        return self.parse_html(html, url=url)

    def parse_html(self, html: str, url: str = "") -> dict[str, Any]:
        """Parse a Wikipedia HTML string."""

        self.soup = BeautifulSoup(html, "html.parser")
        content_root = self.soup.find("div", class_="mw-parser-output")
        if not isinstance(content_root, Tag):
            return {"error": "Wikipedia content container 'mw-parser-output' was not found"}

        document = {
            "schema_version": FORMAT_SCHEMA_VERSION,
            "title": self._extract_title(),
            "url": url,
            "content": [],
        }
        items = [item for item in self._iter_content_items(content_root) if item]
        document["content"] = self._build_hierarchy(items)
        return document

    def to_json(self, data: dict[str, Any], indent: int = 2) -> str:
        return json.dumps(data, ensure_ascii=False, indent=indent)

    def save_to_file(self, data: dict[str, Any], filename: str | Path) -> None:
        Path(filename).write_text(self.to_json(data), encoding="utf-8")

    def print_structure(self, data: dict[str, Any], max_depth: int = 4) -> None:
        """Print a compact tree view for exploratory parser debugging."""

        print(data.get("title", ""))

        def print_node(node: dict[str, Any], depth: int = 0) -> None:
            if depth > max_depth:
                return

            indent = "  " * depth
            if node.get("type") == "heading":
                content_count = len(node.get("content", []))
                print(f"{indent}H{node.get('level')}: {node.get('text', '')} [{content_count}]")
                for child in node.get("content", []):
                    print_node(child, depth + 1)
                return

            if node.get("type") == "formula":
                preview = node.get("latex") or node.get("alttext") or ""
            else:
                preview = node.get("text") or node.get("caption") or node.get("type", "")

            print(f"{indent}{node.get('type', 'unknown')}: {str(preview)[:80]}")

        for item in data.get("content", []):
            print_node(item, 1)

    def _iter_content_items(self, content_root: Tag) -> list[dict[str, Any] | None]:
        items: list[dict[str, Any] | None] = []

        for node in content_root.find_all(CONTENT_TAGS, recursive=False):
            if not isinstance(node, Tag) or self._should_skip(node):
                continue

            heading = self._extract_heading(node)
            if heading:
                items.append(
                    {
                        "type": "heading",
                        "level": heading.level,
                        "text": heading.text,
                        "id": heading.element_id,
                        "content": [],
                    }
                )
                continue

            items.extend(self._extract_content_items(node))

        return items

    def _extract_content_items(self, node: Tag) -> list[dict[str, Any]]:
        if node.name == "p":
            return self._extract_paragraph_with_formulas(node)
        if node.name in {"ul", "ol"}:
            item = self._extract_list(node)
            return [item] if item else []
        if node.name == "table":
            item = self._extract_table(node)
            return [item] if item else []
        if node.name == "section":
            return [item for item in self._iter_content_items(node) if item]
        if node.name == "dl":
            return self._extract_items_from_div(node)
        if node.name == "figure" or self._has_class(node, "thumb"):
            item = self._extract_image(node)
            return [item] if item else []
        if self._has_class(node, "hatnote"):
            text = self._clean_text(node.get_text(" ", strip=True))
            return [{"type": "hatnote", "text": text}] if text else []
        if node.name == "div":
            return self._extract_items_from_div(node)

        return []

    def _extract_items_from_div(self, node: Tag) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []

        for math_node in self._find_formula_nodes(node):
            formula = self._extract_formula(math_node)
            if formula:
                items.append(formula)

        # Some Wikipedia language editions wrap display math in definition lists.
        for child in node.find_all(["p", "ul", "ol", "table", "figure"], recursive=False):
            if not self._should_skip(child):
                items.extend(self._extract_content_items(child))

        return items

    def _extract_paragraph_with_formulas(self, node: Tag) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        text = self._clean_text(node.get_text(" ", strip=True))
        if text:
            items.append({"type": "paragraph", "text": text})

        # Preserve math as separate elements for current renderer experiments.
        for math_node in self._find_formula_nodes(node):
            formula = self._extract_formula(math_node)
            if formula:
                items.append(formula)

        return items

    def _extract_list(self, node: Tag) -> dict[str, Any] | None:
        list_items = []
        for list_item in node.find_all("li", recursive=False):
            text = self._clean_text(list_item.get_text(" ", strip=True))
            if text:
                list_items.append({"text": text})

        if not list_items:
            return None

        return {
            "type": "list",
            "list_type": "ordered" if node.name == "ol" else "unordered",
            "items": list_items,
        }

    def _extract_table(self, node: Tag) -> dict[str, Any] | None:
        rows = []
        for table_row in node.find_all("tr"):
            cells = []
            for cell in table_row.find_all(["td", "th"], recursive=False):
                text = self._clean_text(cell.get_text(" ", strip=True))
                if text:
                    cells.append({"text": text, "is_header": cell.name == "th"})
            if cells:
                rows.append(cells)

        return {"type": "table", "rows": rows} if rows else None

    def _extract_image(self, node: Tag) -> dict[str, Any] | None:
        image = node.find("img")
        if not isinstance(image, Tag):
            return None

        src = image.get("src", "")
        if not src:
            return None

        caption_node = node.find("figcaption") or node.find("div", class_="thumbcaption")
        caption = self._clean_text(caption_node.get_text(" ", strip=True)) if isinstance(caption_node, Tag) else ""

        return {
            "type": "image",
            "src": self._absolute_url(str(src), base="https://commons.wikimedia.org"),
            "caption": caption,
            "alt": image.get("alt", ""),
        }

    def _extract_formula(self, node: Tag) -> dict[str, Any] | None:
        mathml = None
        latex = None
        image_src = None
        alt_text = None
        alttext = None

        math_tag = node if node.name == "math" else node.find("math")
        if isinstance(math_tag, Tag):
            mathml = re.sub(r">\s+<", "><", str(math_tag).strip())
            alttext = math_tag.get("alttext")
            annotation = math_tag.find("annotation", encoding="application/x-tex")
            if isinstance(annotation, Tag):
                latex = self._clean_latex(annotation.get_text(strip=True))

        image = node.find("img", class_=re.compile("mwe-math")) if node.name != "img" else node
        if isinstance(image, Tag):
            src = image.get("src", "")
            if src:
                image_src = self._absolute_url(str(src), base="https://wikimedia.org")
            alt_text = image.get("alt")

        if not any([mathml, latex, image_src, alt_text, alttext]):
            return None

        classes = self._classes(node)
        parent_classes = self._classes(node.parent) if isinstance(node.parent, Tag) else []
        formula_type = "display" if any("display" in item for item in classes + parent_classes) else "inline"

        return {
            "type": "formula",
            "formula_type": formula_type,
            "mathml": mathml,
            "latex": latex,
            "image_src": image_src,
            "alt_text": alt_text,
            "alttext": alttext,
        }

    def _find_formula_nodes(self, node: Tag) -> list[Tag]:
        seen: set[int] = set()
        formulas: list[Tag] = []

        for candidate in node.find_all(["math", "span", "img"]):
            if not isinstance(candidate, Tag):
                continue

            if self._has_seen_formula_ancestor(candidate, seen):
                continue

            is_formula = (
                candidate.name == "math"
                or self._has_class(candidate, "mwe-math-element")
                or self._has_class(candidate, "mwe-math-fallback-image-inline")
            )
            if is_formula and id(candidate) not in seen:
                formulas.append(candidate)
                seen.add(id(candidate))

        return formulas

    @staticmethod
    def _has_seen_formula_ancestor(node: Tag, seen: set[int]) -> bool:
        parent = node.parent
        while isinstance(parent, Tag):
            if id(parent) in seen:
                return True
            parent = parent.parent
        return False

    def _extract_heading(self, node: Tag) -> HeadingInfo | None:
        heading_node = node
        if node.name == "div" and self._has_class(node, "mw-heading"):
            found = node.find(["h1", "h2", "h3", "h4", "h5", "h6"])
            if not isinstance(found, Tag):
                return None
            heading_node = found

        if heading_node.name not in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            return None

        try:
            level = int(heading_node.name[1])
        except (TypeError, ValueError):
            return None

        text = self._clean_heading_text(heading_node.get_text(" ", strip=True))
        if not text:
            return None

        return HeadingInfo(level=level, text=text, element_id=str(heading_node.get("id", "")))

    def _build_hierarchy(self, flat_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        root: dict[str, Any] = {"type": "root", "content": []}
        stack: list[tuple[int, dict[str, Any]]] = [(0, root)]
        last_heading_key: tuple[int, str] | None = None

        for item in flat_items:
            if item.get("type") != "heading":
                stack[-1][1].setdefault("content", []).append(item)
                continue

            heading_key = (int(item.get("level", 0)), item.get("text", ""))
            if heading_key == last_heading_key:
                self._log(f"Skipped duplicate heading: {heading_key[1]}")
                continue
            last_heading_key = heading_key

            level = int(item["level"])
            while len(stack) > 1 and stack[-1][0] >= level:
                stack.pop()

            stack[-1][1].setdefault("content", []).append(item)
            stack.append((level, item))

        return root["content"]

    def _extract_title(self) -> str:
        if not self.soup:
            return ""

        title = self.soup.find("h1", class_="firstHeading") or self.soup.find("h1")
        return self._clean_text(title.get_text(" ", strip=True)) if isinstance(title, Tag) else ""

    def _should_skip(self, node: Tag) -> bool:
        if node.name in {"link", "meta", "script", "style"}:
            return True

        classes = self._classes(node)
        if any(class_name in SKIP_CLASSES for class_name in classes):
            return True

        if node.name == "p" and not self._clean_text(node.get_text(" ", strip=True)):
            return True

        return False

    def _has_class(self, node: Tag, class_name: str) -> bool:
        return class_name in self._classes(node)

    @staticmethod
    def _classes(node: Any) -> list[str]:
        if not isinstance(node, Tag):
            return []
        raw_classes = node.get("class", [])
        return [str(item) for item in raw_classes]

    @staticmethod
    def _clean_heading_text(text: str) -> str:
        text = re.sub(r"\s*\[edit\]\s*", " ", text)
        return WikipediaParser._clean_text(text)

    @staticmethod
    def _clean_text(text: str) -> str:
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"\[\s*\d+\s*\]", "", text)
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        text = re.sub(r"([(])\s+", r"\1", text)
        text = re.sub(r"\s+([)])", r"\1", text)
        return text

    @staticmethod
    def _clean_latex(text: str) -> str:
        text = re.sub(r"^\{\\displaystyle\s*", "", text)
        text = re.sub(r"\s*\}$", "", text)
        return text.strip()

    @staticmethod
    def _absolute_url(url: str, base: str) -> str:
        if url.startswith("//"):
            return f"https:{url}"
        if url.startswith(("http://", "https://")):
            return url
        return urljoin(base, url)

    def _log(self, message: str) -> None:
        if self.debug:
            print(f"DEBUG: {message}")


def parse_wikipedia_html(html: str, url: str = "") -> dict[str, Any]:
    """Convenience function for tests and small scripts."""

    return WikipediaParser().parse_html(html, url=url)
