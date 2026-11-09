import json
from pathlib import Path

import pytest
from PIL import Image

from polydocbench.benchmark.development import DevelopmentSource, DevelopmentSpec, select_content_page
from polydocbench.benchmark.development_review import DevelopmentDecision, DevelopmentReview
from polydocbench.benchmark.manifest import build_manifest, verify_manifest
from polydocbench.benchmark.render_snapshot import capture_render_snapshot, replay_render_snapshot, verify_render_snapshot
from polydocbench.sources.derived import CompositionRecipe, create_derived_source, verify_derived_source
from polydocbench.sources.snapshots import capture_wikipedia_source
from test_wikipedia_snapshots import _fake_mediawiki


@pytest.fixture
def composition(tmp_path, monkeypatch):
    _fake_mediawiki(monkeypatch)
    monkeypatch.setattr("test_wikipedia_snapshots.HTML", '<div class="mw-parser-output"><p>First source paragraph with original words.</p><p>Second paragraph has sufficient text for a composition.</p></div>')
    parent = tmp_path / "parent"
    capture_wikipedia_source("https://en.wikipedia.org/wiki/Test_Article", parent)
    figure = tmp_path / "figure.png"
    Image.new("RGB", (80, 35), "green").save(figure)
    root = tmp_path / "dataset/en/test"
    recipe = CompositionRecipe(figure_caption="Synthetic control figure.", table={
        "rows": [[{"text": "A", "is_header": True}, {"text": "B", "is_header": True}],
                 [{"text": "1"}, {"text": "2"}]], "caption": "Synthetic table."})
    create_derived_source(parent, root, recipe=recipe, figure_path=figure)
    return root


def test_composition_preserves_revision_recipe_and_explicit_scope(composition):
    evidence = verify_derived_source(composition)
    data = json.loads((composition / "source.json").read_text())
    assert data["metadata"]["not_a_full_article"]
    assert data["metadata"]["derived_source_id"] == evidence.derivation_id
    assert "wikipedia_snapshot_id" not in data["metadata"]
    assert evidence.rights_status == "pending_human_review"
    assert [item["type"] for item in data["elements"]] == ["paragraph", "paragraph", "image", "table"]
    (composition / "origin/query.json").write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        verify_derived_source(composition)


def test_source_or_recipe_tampering_is_rejected(composition):
    path = composition / "derived_source_provenance.json"
    data = json.loads(path.read_text())
    data["recipe"]["text_items"] += 1
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="seal"):
        verify_derived_source(composition)


def test_prose_filter_records_skipped_tex_and_navigation_without_rewriting_text(composition, tmp_path, monkeypatch):
    monkeypatch.setattr("test_wikipedia_snapshots.HTML", '<div class="mw-parser-output"><p>Literal \\displaystyle fragment.</p>'
                        '<p>Navigation \u27a4 marker.</p><p>First usable prose paragraph.</p><p>Second usable prose paragraph.</p></div>')
    parent = tmp_path / "new_parent"
    capture_wikipedia_source("https://en.wikipedia.org/wiki/Test_Article", parent)
    old = verify_derived_source(composition)
    assert "text_filter" not in old.recipe.model_dump()
    recipe = old.recipe.model_copy(update={"text_filter": "prose_without_tex_or_navigation_v1"})
    target = tmp_path / "filtered"
    create_derived_source(parent, target, recipe=recipe, figure_path=composition / "assets/controlled_figure.png")
    result = json.loads((target / "source.json").read_text())
    assert [e["content"] for e in result["elements"][:2]] == ["First usable prose paragraph.", "Second usable prose paragraph."]
    assert {e["reason"] for e in result["metadata"]["skipped_text_items"]} == {"tex_or_backslash_fragment", "navigation_marker_or_hatnote"}
    assert verify_derived_source(target).derivation_id != old.derivation_id


def test_derived_lineage_is_sealed_in_render_and_manifest(composition, tmp_path):
    pytest.importorskip("cv2")
    pytest.importorskip("fitz")
    from polydocbench.noise import pdf_to_noisy_dataset

    output = composition / "technical_report"
    result = capture_render_snapshot(composition / "source.json", output, template="technical_report")
    evidence = verify_render_snapshot(output)
    assert evidence.inputs.source_revision_status == "derived_response_bound"
    assert replay_render_snapshot(output, tmp_path / "replay")["replay_verified"]
    pdf_to_noisy_dataset(result["pdf_path"], result["gt_path"], output / "noisy/page_001",
                         page_index=0, n_variants=1, dpi=72, profiles=["clean"])
    manifest = build_manifest(composition.parents[1])
    assert not manifest.issues and len(manifest.records) == 1
    record = manifest.records[0]
    assert record.source_revision_id == 123 and record.source_snapshot_id
    assert "source_revision_not_verified" not in record.provenance_gaps
    assert "controlled_composition_not_full_article" in record.provenance_gaps
    assert record.split == "unassigned" and not verify_manifest(manifest, composition.parents[1])


def test_page_selection_prefers_media_then_text_with_stable_ties():
    elements = []
    for page, types in ((1, ["text_line"] * 8), (2, ["image", "table", "text_line"]),
                        (3, ["image", "table", "text_line"])):
        elements.extend({"type": value, "bbox": {"page": page}} for value in types)
    assert select_content_page({"pages": [{"page_number": p} for p in (1, 2, 3)], "elements": elements})[0] == 2


def test_development_spec_paths_language_and_test_scope():
    data = json.loads(Path("configs/development_corpus.json").read_text(encoding="utf-8"))
    spec = DevelopmentSpec.model_validate(data)
    assert len(spec.sources) * len(spec.templates) == 72
    assert len({s.language for s in spec.sources}) == 6
    with pytest.raises(ValueError):
        DevelopmentSource(language="ru", article_id="../unsafe", family_id="x", url="https://en.wikipedia.org/wiki/X")
    data["purpose"] = "final_test"
    with pytest.raises(ValueError):
        DevelopmentSpec.model_validate(data)


def test_review_cannot_claim_automatic_or_anonymous_approval():
    assert DevelopmentDecision(unit_id="x", category="evaluation_protocol").status == "pending"
    with pytest.raises(ValueError):
        DevelopmentDecision(unit_id="x", category="evaluation_protocol", status="approved")
    with pytest.raises(ValueError):
        DevelopmentDecision(unit_id="x", category="evaluation_protocol", reviewer_kind="ai")
    with pytest.raises(ValueError):
        DevelopmentReview(bundle_id="0" * 64, files=[], decisions=[])


def test_pending_gt_or_failed_calibration_cannot_pass_development_gate():
    from types import SimpleNamespace
    from polydocbench.benchmark.development_review import readiness_blockers

    review = SimpleNamespace(decisions=[SimpleNamespace(status="approved")])
    audit = {"automatic_error_findings": 0, "manual_review_statuses": {"accepted": 10}, "manual_review_units": 10}
    calibration = {"selected_images": 20, "successful_images": 20}
    assert not readiness_blockers(review, audit, calibration)
    review.decisions[0].status = "pending"
    assert readiness_blockers(review, audit, calibration)
    review.decisions[0].status = "approved"
    audit["manual_review_statuses"] = {"accepted": 9, "pending": 1}
    assert readiness_blockers(review, audit, calibration)
    audit["manual_review_statuses"] = {"accepted": 10}
    calibration["successful_images"] = 19
    assert readiness_blockers(review, audit, calibration)


def test_scenario_selection_keeps_exact_calibration_pages_and_all_conditions():
    from polydocbench.benchmark.calibration import prepare_calibration
    from polydocbench.benchmark.pilot import base_page_key
    from scripts.run_development_scenarios import scenario_plan
    from test_benchmark_pilot import make_inventory
    from test_noise_calibration import spec

    inventory = make_inventory(profiles=("clean", "light_scan", "medium_scan", "heavy_scan"))
    calibration = prepare_calibration(inventory, spec(), base_pages=2, split="unassigned")
    plan = scenario_plan(inventory, calibration)
    assert {base_page_key(r) for r in plan.selection.records} == {base_page_key(r) for r in calibration.selection.records}
    assert len(plan.selection.records) == 8


def test_scoped_calibration_uses_frozen_contract_and_bound_ledgers(composition, tmp_path, monkeypatch):
    pytest.importorskip("cv2")
    pytest.importorskip("plotly")
    from polydocbench.benchmark.calibration import CalibrationSpec, NoiseSweep, prepare_calibration
    from polydocbench.benchmark.calibration_run import generate_calibration, write_calibration_results
    from polydocbench.benchmark.pilot_worker import PilotAdapter, run_worker
    from polydocbench.benchmark.pilot_runtime import default_model_config
    from polydocbench.eval.contract import EvaluationSettings, freeze_evaluation
    from polydocbench.noise import pdf_to_noisy_dataset
    from polydocbench.provenance import json_sha256

    target = composition / "technical_report"
    rendered = capture_render_snapshot(composition / "source.json", target, template="technical_report")
    pdf_to_noisy_dataset(rendered["pdf_path"], rendered["gt_path"], target / "noisy/page_001",
                         n_variants=1, dpi=72, profiles=["clean"])
    contract = freeze_evaluation(EvaluationSettings())
    spec = CalibrationSpec(dpi=72, evaluation_protocol_version="0.3", evaluation_contract=contract,
                           sweeps=[NoiseSweep(operation="defocus_blur", parameter="sigma_pixels", levels=[0.8, 1.6])])
    plan = prepare_calibration(build_manifest(composition.parents[1]), spec, base_pages=1, split="unassigned")
    output = tmp_path / "calibration"
    pilot = generate_calibration(plan, composition.parents[1], output)
    run = output / "run"
    run.mkdir()
    config = {**default_model_config(), **contract.model_config_values()}
    job = {"plan": pilot.model_dump(), "input_dir": str(output / "dataset"), "engine": "tesseract", "config": config}
    adapter = PilotAdapter("tesseract", config)
    monkeypatch.setattr(adapter, "predict", lambda *args: [])
    run_worker(job, run, adapter=adapter)
    metadata = {"plan_id": pilot.plan_id, "engine": "tesseract", "environment": {"fixture_only": True}}
    metadata["configuration_sha256"] = json_sha256({"engine": "tesseract", "config": config, "environment": metadata["environment"]})
    (run / "run.json").write_text(json.dumps(metadata))
    (run / "job.json").write_text(json.dumps(job))
    events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
    rows = [{**e, "plan_id": pilot.plan_id, "configuration_sha256": metadata["configuration_sha256"], "profile": r.profile}
            for e, r in zip([e for e in events if e["event"] == "result"], pilot.selection.records)]
    assert all(r["status"] == "success" for r in rows)
    (run / "results.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    summary = write_calibration_results(output)
    assert summary["evaluation_contract_id"] == contract.contract_id
    assert summary["selected_images"] == summary["successful_images"] == 3
    assert "Protocol 0.3" in (output / "dashboard.html").read_text()
    (run / rows[0]["prediction_path"]).write_text('[{"text": "tampered"}]')
    with pytest.raises(ValueError, match="scope ledger"):
        write_calibration_results(output)
