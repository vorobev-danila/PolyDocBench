import pytest


fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from polydocbench.api.app import app


def test_api_health_and_templates():
    client = TestClient(app)

    assert client.get("/health").json() == {"status": "ok"}
    templates = client.get("/templates").json()["templates"]
    assert "simple_article" in templates
