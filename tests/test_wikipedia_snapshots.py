import json
from urllib.parse import parse_qs, urlparse

import pytest

from polydocbench.sources.snapshots import capture_wikipedia_source, verify_wikipedia_source, wikipedia_target


HTML = '<div class="mw-parser-output"><p>A revision-bound article with enough text for parsing.</p></div>'


class Response:
    def __init__(self, url, payload):
        self.url = url
        self._payload = payload
        self.content = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _fake_mediawiki(monkeypatch, *, revision=123, response_host="en.wikipedia.org"):
    calls = []

    def get(url, params, **kwargs):
        calls.append((url, params, kwargs))
        if params["action"] == "query":
            payload = {"query": {"pages": [{
                "pageid": 7,
                "ns": 0,
                "title": "Test Article",
                "pageprops": {"wikibase_item": "Q42"},
                "revisions": [{
                    "revid": revision,
                    "parentid": revision - 1,
                    "timestamp": "2026-11-01T10:00:00Z",
                    "sha1": "abc123",
                }],
            }]}}
        else:
            payload = {"parse": {"title": "Test Article", "pageid": 7, "revid": revision, "text": HTML}}
        return Response(f"https://{response_host}/w/api.php", payload)

    monkeypatch.setattr("polydocbench.sources.snapshots.requests.get", get)
    return calls


def test_capture_and_offline_verify_revision_bound_source(tmp_path, monkeypatch):
    calls = _fake_mediawiki(monkeypatch)
    root = tmp_path / "source"

    result = capture_wikipedia_source("https://en.wikipedia.org/wiki/Test_Article", root)
    evidence = verify_wikipedia_source(root, reparse=True)

    assert result["revision_id"] == 123
    assert evidence.inputs.page_id == 7
    assert evidence.inputs.wikidata_item_id == "Q42"
    assert evidence.inputs.permanent_url.endswith("oldid=123")
    assert calls[0][1]["titles"] == "Test Article"
    assert calls[1][1]["oldid"] == "123"
    source = json.loads((root / "source.json").read_text(encoding="utf-8"))
    assert source["metadata"]["wikipedia_snapshot_id"] == result["snapshot_id"]


def test_capture_respects_oldid_and_rejects_conflicts(tmp_path, monkeypatch):
    calls = _fake_mediawiki(monkeypatch, revision=321)
    capture_wikipedia_source("https://en.wikipedia.org/w/index.php?oldid=321", tmp_path / "source")
    assert calls[0][1]["revids"] == "321"
    with pytest.raises(ValueError, match="conflicts"):
        capture_wikipedia_source(
            "https://en.wikipedia.org/w/index.php?oldid=321", tmp_path / "other", revision_id=322
        )


def test_verify_detects_changed_api_evidence(tmp_path, monkeypatch):
    _fake_mediawiki(monkeypatch)
    root = tmp_path / "source"
    capture_wikipedia_source("https://en.wikipedia.org/wiki/Test_Article", root)
    (root / "query.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        verify_wikipedia_source(root)


def test_capture_rejects_cross_host_response_and_unsafe_urls(tmp_path, monkeypatch):
    _fake_mediawiki(monkeypatch, response_host="example.com")
    with pytest.raises(ValueError, match="unexpected host"):
        capture_wikipedia_source("https://en.wikipedia.org/wiki/Test", tmp_path / "source")
    for url in ("https://example.com/wiki/Test", "https://user@en.wikipedia.org/wiki/Test", "file:///Test"):
        with pytest.raises(ValueError):
            wikipedia_target(url)
