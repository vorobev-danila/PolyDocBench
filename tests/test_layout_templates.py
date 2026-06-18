from pathlib import Path

from polydocbench.layout.templates import list_template_names, resolve_template_path


def test_default_template_path_resolves_outside_project_root(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    resolved = resolve_template_path()

    assert resolved == Path(__file__).resolve().parents[1] / "configs" / "layout_templates.yaml"
    assert "simple_article" in list_template_names()
