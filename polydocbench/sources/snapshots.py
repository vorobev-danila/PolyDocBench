"""Revision-bound Wikipedia source capture with offline response verification."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests
from pydantic import BaseModel, ConfigDict, Field, model_validator

from polydocbench.document.schema import validate_source_document
from polydocbench.provenance import FileFingerprint, fingerprint_file, json_sha256
from .wikipedia import DEFAULT_USER_AGENT, WikipediaParser


PROVENANCE_NAME = "source_provenance.json"
ROOT = Path(__file__).resolve().parents[2]
PARSER_FILES = ("polydocbench/sources/wikipedia.py", "polydocbench/document/schema.py", "polydocbench/document/tables.py")


class WikipediaInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["0.1"]
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    method: Literal["mediawiki_revision_parse"]
    requested_url: str
    requested_revision_id: int | None
    language: str
    canonical_title: str
    canonical_url: str
    permanent_url: str
    page_id: int = Field(gt=0, strict=True)
    revision_id: int = Field(gt=0, strict=True)
    revision_timestamp: str
    revision_sha1: str | None
    wikidata_item_id: str | None = Field(pattern=r"^Q[1-9][0-9]*$")
    retrieved_at: str
    query_response: FileFingerprint
    parse_response: FileFingerprint
    html: FileFingerprint
    parser_files: list[FileFingerprint] = Field(min_length=len(PARSER_FILES))
    parser_environment: dict[str, str]

    @model_validator(mode="after")
    def validate_identity(self) -> "WikipediaInputs":
        if self.snapshot_id != json_sha256(self.model_dump(exclude={"snapshot_id"})):
            raise ValueError("Wikipedia snapshot ID does not match its response records")
        language, _, url_revision = wikipedia_target(self.requested_url)
        if language != self.language or self.canonical_url != article_url(language, self.canonical_title):
            raise ValueError("Wikipedia URL/language/title identity mismatch")
        if self.permanent_url != f"https://{language}.wikipedia.org/w/index.php?oldid={self.revision_id}":
            raise ValueError("Permanent URL does not identify the captured revision")
        for requested in (url_revision, self.requested_revision_id):
            if requested is not None and requested != self.revision_id:
                raise ValueError("Captured revision differs from the requested revision")
        for value in (self.retrieved_at, self.revision_timestamp):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Source timestamps must include a timezone")
        if (self.query_response.path, self.parse_response.path, self.html.path) != (
                "query.json", "parse.json", "page.html"):
            raise ValueError("Wikipedia evidence files must use the standard snapshot paths")
        if {file.path for file in self.parser_files} != set(PARSER_FILES):
            raise ValueError("Wikipedia snapshot must identify every parser implementation file")
        if set(self.parser_environment) != {"python", "beautifulsoup4", "pydantic"}:
            raise ValueError("Wikipedia snapshot parser environment is incomplete")
        return self


class WikipediaProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["0.1"]
    inputs: WikipediaInputs
    source: FileFingerprint

    @model_validator(mode="after")
    def validate_paths(self) -> "WikipediaProvenance":
        if self.source.path != "source.json":
            raise ValueError("Wikipedia source evidence must identify source.json")
        return self


def article_url(language: str, title: str) -> str:
    return f"https://{language}.wikipedia.org/wiki/{quote(title.replace(' ', '_'), safe='(),_')}"


def wikipedia_target(url: str) -> tuple[str, str | None, int | None]:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    match = re.fullmatch(r"([a-z][a-z0-9-]*)\.(?:m\.)?wikipedia\.org", host)
    if parsed.scheme not in {"https", "http"} or not match or parsed.username or parsed.password or parsed.port:
        raise ValueError("Expected a public Wikipedia article URL without credentials or a port")
    query = parse_qs(parsed.query)
    oldids = query.get("oldid", [])
    if len(oldids) > 1 or oldids and (not oldids[0].isdigit() or int(oldids[0]) < 1):
        raise ValueError("oldid must be a single positive revision ID")
    revision = int(oldids[0]) if oldids else None
    title = None
    if parsed.path.startswith("/wiki/"):
        title = unquote(parsed.path[len("/wiki/"):]).replace("_", " ")
    elif parsed.path == "/w/index.php":
        titles = query.get("title", [])
        if len(titles) > 1:
            raise ValueError("Expected one article title")
        title = titles[0].replace("_", " ") if titles else None
    else:
        raise ValueError("Expected /wiki/TITLE or /w/index.php?oldid=REVISION")
    if not title and revision is None:
        raise ValueError("Wikipedia URL requires an article title or revision ID")
    return match[1], title, revision


def _read(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Expected a MediaWiki JSON object")
    return data


def _write(path: Path, data: dict):
    with path.open("x", encoding="utf-8") as file:
        file.write(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def _page(payload: dict) -> tuple[dict, dict]:
    if "error" in payload:
        raise ValueError(f"MediaWiki error: {payload['error']}")
    pages = payload.get("query", {}).get("pages", [])
    if not isinstance(pages, list) or len(pages) != 1:
        raise ValueError("Expected exactly one resolved Wikipedia page")
    page = pages[0]
    if "missing" in page or page.get("ns") != 0 or not page.get("revisions"):
        raise ValueError("Wikipedia source must be an existing main-namespace article with a visible revision")
    revisions = page["revisions"]
    if len(revisions) != 1 or not revisions[0].get("revid") or not revisions[0].get("timestamp"):
        raise ValueError("Expected a visible revision ID and timestamp")
    return page, revisions[0]


def _parsed_html(payload: dict, page: dict, revision: dict) -> str:
    if "error" in payload:
        raise ValueError(f"MediaWiki parse error: {payload['error']}")
    parsed = payload.get("parse", {})
    if (parsed.get("revid") != revision["revid"] or parsed.get("pageid") != page["pageid"]
            or parsed.get("title") != page["title"]):
        raise ValueError("Parsed HTML does not belong to the queried page/revision")
    html = parsed.get("text")
    if not isinstance(html, str) or not html.strip():
        raise ValueError("MediaWiki did not return revision HTML")
    return html


def _parser_environment() -> dict[str, str]:
    import platform

    return {"python": platform.python_version(), "beautifulsoup4": version("beautifulsoup4"), "pydantic": version("pydantic")}


def _document(html: str, inputs: WikipediaInputs) -> dict:
    data = WikipediaParser().parse_html(html, url=inputs.canonical_url)
    if "error" in data or not data.get("content"):
        raise ValueError(f"Captured revision has no usable parsed content: {data.get('error', inputs.canonical_url)}")
    data["title"] = inputs.canonical_title
    data["metadata"] = {"wikipedia_snapshot_id": inputs.snapshot_id, "wikipedia_provenance": PROVENANCE_NAME}
    validate_source_document(data)
    return data


def capture_wikipedia_source(url: str, output_dir: str | Path, *, revision_id: int | None = None,
                             timeout: float = 30, user_agent: str = DEFAULT_USER_AGENT) -> dict:
    """Resolve once, parse that oldid, and save raw API evidence; never fall back to latest HTML."""
    language, title, url_revision = wikipedia_target(url)
    if revision_id is not None and (isinstance(revision_id, bool) or not isinstance(revision_id, int) or revision_id < 1):
        raise ValueError("revision_id must be a positive integer")
    if revision_id is not None and url_revision is not None and revision_id != url_revision:
        raise ValueError("Explicit revision_id conflicts with URL oldid")
    selected_revision = revision_id if revision_id is not None else url_revision
    root = Path(output_dir).resolve()
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValueError("Source snapshot directory must be new or empty")
    api_url = f"https://{language}.wikipedia.org/w/api.php"
    query = {"action": "query", "prop": "revisions|pageprops", "rvprop": "ids|timestamp|sha1",
             "ppprop": "wikibase_item", "format": "json", "formatversion": "2"}
    if selected_revision is None:
        query.update({"titles": title, "redirects": "1", "rvlimit": "1"})
    else:
        query["revids"] = str(selected_revision)

    def get(parameters):
        response = requests.get(api_url, params=parameters, headers={"User-Agent": user_agent}, timeout=timeout)
        response.raise_for_status()
        if urlparse(response.url).hostname != f"{language}.wikipedia.org":
            raise ValueError("MediaWiki response redirected to an unexpected host")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Expected a MediaWiki JSON response")
        return response.content, payload

    raw_query, metadata = get(query)
    page, revision = _page(metadata)
    if selected_revision is not None and revision["revid"] != selected_revision:
        raise ValueError("MediaWiki returned a different revision than requested")
    raw_parse, parsed = get({"action": "parse", "oldid": str(revision["revid"]),
                             "prop": "text|revid|displaytitle", "format": "json", "formatversion": "2"})
    html = _parsed_html(parsed, page, revision)
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValueError("Source snapshot directory changed during capture; refusing to overwrite it")
    root.mkdir(parents=True, exist_ok=True)
    for name, content in (("query.json", raw_query), ("parse.json", raw_parse),
                          ("page.html", html.encode("utf-8"))):
        with (root / name).open("xb") as file:
            file.write(content)
    payload = {"schema_version": "0.1", "method": "mediawiki_revision_parse", "requested_url": url,
               "requested_revision_id": selected_revision, "language": language, "canonical_title": page["title"],
               "canonical_url": article_url(language, page["title"]),
               "permanent_url": f"https://{language}.wikipedia.org/w/index.php?oldid={revision['revid']}",
               "page_id": page["pageid"], "revision_id": revision["revid"],
               "revision_timestamp": revision["timestamp"], "revision_sha1": revision.get("sha1"),
               "wikidata_item_id": page.get("pageprops", {}).get("wikibase_item"),
               "retrieved_at": datetime.now(timezone.utc).isoformat(),
               "query_response": fingerprint_file(root, root / "query.json").model_dump(),
               "parse_response": fingerprint_file(root, root / "parse.json").model_dump(),
               "html": fingerprint_file(root, root / "page.html").model_dump(),
               "parser_files": [fingerprint_file(ROOT, ROOT / name).model_dump() for name in PARSER_FILES],
               "parser_environment": _parser_environment()}
    inputs = WikipediaInputs(snapshot_id=json_sha256(payload), **payload)
    data = _document(html, inputs)
    _write(root / "source.json", data)
    provenance = WikipediaProvenance(schema_version="0.1", inputs=inputs, source=fingerprint_file(root, root / "source.json"))
    _write(root / PROVENANCE_NAME, provenance.model_dump())
    return {"source_path": str(root / "source.json"), "provenance_path": str(root / PROVENANCE_NAME),
            "revision_id": inputs.revision_id, "snapshot_id": inputs.snapshot_id, "data": data}


def verify_wikipedia_source(root: str | Path, *, reparse: bool = False) -> WikipediaProvenance:
    """Verify saved revision/response/content relationships offline; optionally reparse HTML."""
    root = Path(root).resolve(strict=True)
    evidence = WikipediaProvenance.model_validate(_read(root / PROVENANCE_NAME))
    inputs = evidence.inputs
    for file in (evidence.source, inputs.query_response, inputs.parse_response, inputs.html):
        if fingerprint_file(root, root / file.path) != file:
            raise ValueError(f"Wikipedia snapshot file changed: {file.path}")
    page, revision = _page(_read(root / inputs.query_response.path))
    html = _parsed_html(_read(root / inputs.parse_response.path), page, revision)
    if (page["pageid"] != inputs.page_id or page["title"] != inputs.canonical_title
            or revision["revid"] != inputs.revision_id or revision["timestamp"] != inputs.revision_timestamp
            or revision.get("sha1") != inputs.revision_sha1
            or page.get("pageprops", {}).get("wikibase_item") != inputs.wikidata_item_id):
        raise ValueError("Saved API evidence does not match the declared Wikipedia identity")
    if html.encode("utf-8") != (root / inputs.html.path).read_bytes():
        raise ValueError("Captured HTML differs from the parsed revision response")
    data = _read(root / evidence.source.path)
    validate_source_document(data)
    if (data.get("metadata", {}).get("wikipedia_snapshot_id") != inputs.snapshot_id
            or data.get("url") != inputs.canonical_url or data.get("title") != inputs.canonical_title):
        raise ValueError("Source JSON is not bound to the Wikipedia snapshot")
    if reparse:
        if inputs.parser_environment != _parser_environment():
            raise ValueError("Parser environment differs from the source snapshot")
        for file in inputs.parser_files:
            if fingerprint_file(ROOT, ROOT / file.path) != file:
                raise ValueError(f"Parser implementation differs: {file.path}")
        if _document(html, inputs) != data:
            raise ValueError("Offline parsing does not reproduce source JSON")
    return evidence
