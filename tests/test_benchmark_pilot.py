import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from polydocbench.benchmark.manifest import DatasetManifest, ManifestRecord
from polydocbench.benchmark.pilot import PilotPlan, base_page_key, prepare_pilot
from polydocbench.benchmark.pilot_runtime import run_pilot, summarize_run
from polydocbench.benchmark.pilot_worker import run_worker
from polydocbench.provenance import FileFingerprint, json_sha256


def make_inventory(profiles=("clean", "light_scan", "medium_scan", "heavy_scan")):
    records = []
    for language in ("en", "ru"):
        for article in ("algebra", "history"):
            for template in ("simple_article", "scientific_paper"):
                for profile in profiles:
                    files = {name: FileFingerprint(path=f"{language}/{article}/{template}/{profile}/{name}.json",
                                                  sha256=json_sha256({"name": name, "article": article}), size_bytes=1)
                             for name in ("source", "pdf", "pdf_gt", "image", "image_gt")}
                    payload = {"language": language, "article_id": article, "template": template,
                               "page": 1, "profile": profile, "variant": 0,
                               "files": {name: value.sha256 for name, value in files.items()}}
                    records.append(ManifestRecord(
                        artifact_id=json_sha256(payload), language=language, article_id=article,
                        source_family=article, template=template, source_page_number=1, profile=profile, variant=0,
                        source_url=f"https://{language}.wikipedia.org/wiki/{article}",
                        source_schema_version="0.1", gt_schema_version="0.1", **files,
                        width=10, height=10, dpi=72, transform_matrix=[[1, 0, 0], [0, 1, 0]],
                        provenance_gaps=["source_family_not_reviewed"],
                    ))
    return DatasetManifest(discovered_count=len(records), records=records, issues=[])


def test_selection_is_order_independent_balanced_and_paired():
    manifest = make_inventory()
    plan = prepare_pilot(manifest, base_pages=4, split="unassigned")
    reversed_manifest = manifest.model_copy(update={"records": list(reversed(manifest.records))})
    assert plan == prepare_pilot(reversed_manifest, base_pages=4, split="unassigned")
    assert len(plan.selection.records) == 16
    assert len({base_page_key(r) for r in plan.selection.records}) == 4
    assert set(plan.summary()["languages"].values()) == {8}
    assert set(plan.summary()["templates"].values()) == {8}
    assert all(record.split == "unassigned" for record in plan.selection.records)
    assert PilotPlan.model_validate_json(plan.model_dump_json()) == plan


def test_selection_refuses_missing_conditions_and_unreviewed_dev():
    manifest = make_inventory(profiles=("medium_scan",))
    with pytest.raises(ValueError, match="only 0 available"):
        prepare_pilot(manifest, base_pages=1, split="unassigned")
    with pytest.raises(ValueError, match="split=dev"):
        prepare_pilot(manifest, base_pages=1, profiles=["medium_scan"])
    with pytest.raises(ValueError):
        prepare_pilot(make_inventory(), base_pages=9, split="unassigned")


def test_pilot_seal_and_pair_validation():
    plan = prepare_pilot(make_inventory(), base_pages=1, split="unassigned")
    data = plan.model_dump()
    data["seed"] += 1
    with pytest.raises(ValidationError, match="seal"):
        PilotPlan.model_validate(data)
    data = plan.model_dump()
    data["selection"]["records"].pop()
    data["selection"]["discovered_count"] -= 1
    data["plan_id"] = json_sha256({k: v for k, v in data.items() if k != "plan_id"})
    with pytest.raises(ValidationError, match="exactly"):
        PilotPlan.model_validate(data)


def test_worker_retains_failures_and_separates_inference_evaluation(tmp_path):
    plan = prepare_pilot(make_inventory(), base_pages=1, split="unassigned")
    for record in plan.selection.records:
        gt_path = tmp_path / record.image_gt.path
        gt_path.parent.mkdir(parents=True, exist_ok=True)
        gt_path.write_text("{}", encoding="utf-8")

    class Adapter:
        calls = 0

        def predict(self, record, image, raw):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("sensitive response should not be persisted")
            return []

        def evaluate(self, record, gt, predictions):
            return {"evaluation_protocol_version": "0.2", "score": 1}

    run_worker({"plan": plan.model_dump(), "input_dir": str(tmp_path), "engine": "tesseract"},
               tmp_path, Adapter())
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    rows = [event for event in events if event["event"] == "result"]
    assert len(rows) == 4
    assert [row["status"] for row in rows] == ["success", "failed", "success", "success"]
    assert rows[0]["phase"] == "first_call" and rows[1]["phase"] == "subsequent_call"
    assert rows[1]["failed_stage"] == "inference"
    assert "sensitive" not in json.dumps(events)
    assert rows[0]["evaluation_seconds"] >= 0 and rows[0]["inference_seconds"] >= 0


def test_summary_uses_all_selected_images_as_success_denominator():
    rows = [
        {"status": "success", "phase": "first_call", "inference_seconds": 5},
        {"status": "success", "phase": "subsequent_call", "inference_seconds": 2},
        {"status": "timeout", "phase": "subsequent_call", "inference_seconds": None},
        {"status": "not_run", "phase": None, "inference_seconds": None},
    ]
    summary = summarize_run(rows, elapsed=10, peak_rss=100, engine="dotsocr")
    assert summary["selected"] == 4 and summary["success_rate"] == 0.5
    assert summary["subsequent_successful_call_count"] == 1
    assert summary["subsequent_inference_mean_seconds"] == 2
    assert summary["memory_scope"] == "client_process_tree_only"
    assert summary["measured_cost"] is None and summary["gpu_peak_bytes"] is None


@pytest.mark.parametrize("mode", ["timeout", "crash"])
def test_supervisor_failure_preserves_denominator(tmp_path, monkeypatch, mode):
    psutil = pytest.importorskip("psutil")
    plan = prepare_pilot(make_inventory(), base_pages=1, split="unassigned")
    monkeypatch.setattr("polydocbench.benchmark.pilot_runtime.verify_manifest", lambda *args: [])
    monkeypatch.setattr("polydocbench.benchmark.pilot_runtime.runtime_environment", lambda: {})
    original_popen = subprocess.Popen
    children = []
    code = (
        "import json,sys,time; from pathlib import Path; "
        "p=Path(sys.argv[1]); j=json.loads(p.read_text()); "
        "r=j['plan']['selection']['records'][0]; "
        "f=(p.parent/'events.jsonl').open('w'); "
        "f.write(json.dumps({'event':'start','artifact_id':r['artifact_id'],'phase':'first_call'})+'\\n'); "
        "f.flush(); "
    )
    code += "time.sleep(60)" if mode == "timeout" else "sys.exit(3)"

    def popen(command, **kwargs):
        child = original_popen([sys.executable, "-c", code, command[-1]], **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr("polydocbench.benchmark.pilot_runtime.subprocess.Popen", popen)
    summary = run_pilot(plan, tmp_path, tmp_path / "run", engine="docling",
                        timeout_per_image=1, sample_interval=0.02)
    assert summary["statuses"] == {"timeout" if mode == "timeout" else "worker_failed": 1, "not_run": 3}
    assert children[0].poll() is not None
    assert not psutil.pid_exists(children[0].pid)
    rows = (tmp_path / "run/results.jsonl").read_text().splitlines()
    assert len(rows) == 4
    with pytest.raises(ValueError, match="new or empty"):
        run_pilot(plan, tmp_path, tmp_path / "run", engine="docling")


def test_supervisor_checks_integrity_before_starting_any_model(tmp_path, monkeypatch):
    pytest.importorskip("psutil")
    from polydocbench.benchmark.manifest import InventoryIssue

    plan = prepare_pilot(make_inventory(), base_pages=1, split="unassigned")
    issue = InventoryIssue(path="changed.png", error_type="ValueError", message="changed")
    monkeypatch.setattr("polydocbench.benchmark.pilot_runtime.verify_manifest", lambda *args: [issue])
    with pytest.raises(ValueError, match="integrity verification"):
        run_pilot(plan, tmp_path, tmp_path / "run", engine="docling")
    assert not (tmp_path / "run").exists()
