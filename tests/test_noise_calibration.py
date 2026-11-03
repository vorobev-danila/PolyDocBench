import json
import shutil
import subprocess
from pathlib import Path

import pytest

from polydocbench.benchmark.calibration import (
    CalibrationPlan, CalibrationSpec, NoiseSweep, calibration_page_id, prepare_calibration, summarize_calibration,
)
from polydocbench.benchmark.calibration_run import generate_calibration, run_calibration, write_calibration_results
from polydocbench.benchmark.manifest import build_manifest
from polydocbench.eval.quality import aggregate_ocr_counts
from test_benchmark_pilot import make_inventory


def spec(repeats=2):
    return CalibrationSpec(dpi=72, repeats=repeats, sweeps=[
        NoiseSweep(operation="defocus_blur", parameter="sigma_pixels", levels=[0.8, 1.6]),
        NoiseSweep(operation="sensor_noise", parameter="sigma", levels=[5, 12]),
    ])


def metrics(errors, chars=100):
    values = {"char_errors": errors, "word_errors": errors, "gt_char_count": chars, "gt_word_count": 20,
              "num_gt_lines": 10, "num_predicted_lines": 10, "num_matched_lines": 8}
    return {**values, **aggregate_ocr_counts([values]), "evaluation_protocol_version": "0.2"}


def rows_for(plan):
    rows = []
    for index, record in enumerate(plan.selection.records):
        page_id = calibration_page_id(record)
        rows.append({"base_page_id": page_id, "profile": "clean", "status": "success", "metrics": metrics(5, 100 + 100 * index)})
        for condition in plan.spec.conditions():
            rows.append({"base_page_id": page_id, "profile": condition["profile"], "status": "success",
                         "metrics": metrics(5 + 10 * condition["level"], 100 + 100 * index)})
    return rows


def test_calibration_selection_balances_languages_before_templates_and_is_order_invariant():
    inventory = make_inventory(profiles=("clean",))
    first = prepare_calibration(inventory, spec(), base_pages=4, split="unassigned")
    reverse = inventory.model_copy(update={"records": list(reversed(inventory.records))})
    assert first == prepare_calibration(reverse, spec(), base_pages=4, split="unassigned")
    assert [r.language for r in first.selection.records] == ["en", "ru", "en", "ru"]
    assert {r.template for r in first.selection.records} == {"scientific_paper", "simple_article"}
    assert CalibrationPlan.model_validate_json(first.model_dump_json()) == first
    changed = first.model_dump()
    changed["spec"]["seed"] += 1
    with pytest.raises(ValueError, match="seal"):
        CalibrationPlan.model_validate(changed)


def test_unreviewed_sources_cannot_be_selected_as_dev_and_unknown_languages_fail():
    with pytest.raises(ValueError, match="split=dev"):
        prepare_calibration(make_inventory(), spec(), base_pages=1)
    with pytest.raises(ValueError, match="languages"):
        prepare_calibration(make_inventory(), spec(), base_pages=1, split="unassigned", languages=["xx"])


def test_sensor_field_is_paired_across_sigma_and_independent_across_pages_repeats():
    settings = spec()
    one, two = settings.recipes("page_1"), settings.recipes("page_2")
    seed = lambda config, level, repeat: config.profiles[f"cal_sensor_noise_l{level}_r{repeat}"][0].parameters["noise_seed"]
    assert seed(one, 1, 0) == seed(one, 2, 0)
    assert seed(one, 1, 0) != seed(one, 1, 1) != seed(two, 1, 1)
    assert len(settings.conditions()) == 6
    assert {c["repeat"] for c in settings.conditions() if c["operation"] == "defocus_blur"} == {0}


@pytest.mark.parametrize("sweep", [
    {"operation": "motion_blur", "parameter": "length_pixels", "levels": [3, 7]},
    {"operation": "motion_blur", "parameter": "length_pixels", "levels": [3, 4], "fixed_parameters": {"angle_degrees": 20}},
    {"operation": "faded_ink", "parameter": "retained_contrast", "levels": [0.2, 0.7]},
    {"operation": "defocus_blur", "parameter": "sigma_pixels", "levels": [1, 1]},
    {"operation": "sensor_noise", "parameter": "sigma", "levels": [5, 12], "fixed_parameters": {"noise_seed": "0" * 64}},
])
def test_sweeps_refuse_uncontrolled_or_invalid_parameters(sweep):
    with pytest.raises(ValueError):
        NoiseSweep.model_validate(sweep)


def test_aggregation_is_micro_weighted_and_controls_are_page_paired():
    plan = prepare_calibration(make_inventory(), spec(), base_pages=2, split="unassigned")
    summaries, pairs = summarize_calibration(plan, rows_for(plan))
    row = next(r for r in summaries if r["dimension"] == "overall" and r["operation"] == "defocus_blur" and r["level"] == 1)
    assert row["clean_micro_CER"] == pytest.approx(10 / 300)
    assert row["noisy_micro_CER"] == pytest.approx(30 / 300)
    assert row["delta_micro_CER"] == pytest.approx(20 / 300)
    assert row["clean_char_errors"] == 10 and row["noisy_char_errors"] == 30
    assert row["clean_gt_char_count"] == row["noisy_gt_char_count"] == 300
    assert row["curve_pairs"] == 2 and row["complete_base_pages"] == 2
    assert len(pairs) == 12 and all(p["paired"] for p in pairs)


def test_failure_excludes_page_from_entire_effect_curve_without_hiding_other_pairs():
    plan = prepare_calibration(make_inventory(), spec(), base_pages=2, split="unassigned")
    rows = rows_for(plan)
    next(r for r in rows if r["profile"] == "cal_defocus_blur_l2_r0").update(status="timeout", metrics=None)
    summaries, _ = summarize_calibration(plan, rows)
    curve = [r for r in summaries if r["dimension"] == "overall" and r["operation"] == "defocus_blur"]
    assert all(r["complete_base_pages"] == 1 and r["curve_pairs"] == 1 for r in curve)
    assert curve[0]["available_pairs"] == 2 and curve[1]["available_pairs"] == 1
    assert all(r["selected_base_pages"] == 2 for r in curve)


def test_missing_results_remain_not_run_and_null_not_zero():
    plan = prepare_calibration(make_inventory(), spec(), base_pages=1, split="unassigned")
    summaries, pairs = summarize_calibration(plan, [])
    assert all(r["delta_micro_CER"] is None and r["complete_base_pages"] == 0 for r in summaries)
    assert all(p["noisy_status"] == p["clean_status"] == "not_run" for p in pairs)


def test_duplicate_results_and_inconsistent_gt_denominators_are_rejected():
    plan = prepare_calibration(make_inventory(), spec(), base_pages=1, split="unassigned")
    rows = rows_for(plan)
    with pytest.raises(ValueError, match="Duplicate"):
        summarize_calibration(plan, rows + [rows[0]])
    rows[1]["metrics"]["gt_char_count"] += 1
    with pytest.raises(ValueError, match="denominator"):
        summarize_calibration(plan, rows)


@pytest.fixture
def corpus(tmp_path):
    pytest.importorskip("cv2")
    pytest.importorskip("fitz")
    from reportlab.pdfgen import canvas
    from polydocbench.noise import pdf_to_noisy_dataset

    root = tmp_path / "input"
    case = root / "en/algebra"
    template = case / "simple_article"
    template.mkdir(parents=True)
    (case / "source.json").write_text(json.dumps({"schema_version": "0.1", "title": "Calibration",
        "content": [{"type": "paragraph", "text": "Known text"}]}), encoding="utf-8")
    pdf = canvas.Canvas(str(template / "document.pdf"), pagesize=(160, 100), invariant=1)
    pdf.drawString(10, 60, "Known text")
    pdf.save()
    line = {"id": "line", "type": "text_line", "content": "Known text",
            "bbox": {"x": 10, "y": 58, "width": 65, "height": 12, "page": 1}}
    (template / "document_gt.json").write_text(json.dumps({"schema_version": "0.1", "elements": [line],
        "pages": [{"page_number": 1, "width": 160, "height": 100,
                   "containers": [{"id": "main", "elements": [line]}]}]}), encoding="utf-8")
    pdf_to_noisy_dataset(template / "document.pdf", template / "document_gt.json", template / "noisy/page_001",
                         profiles=["clean"], n_variants=1, dpi=72)
    return root


def test_generation_gt_integrity_and_report_ledger_binding(corpus, tmp_path):
    pytest.importorskip("plotly")
    from polydocbench.noise import replay_noise, render_pdf_page

    plan = prepare_calibration(build_manifest(corpus), spec(), base_pages=1, split="unassigned")
    output = tmp_path / "calibration"
    pilot = generate_calibration(plan, corpus, output)
    assert len(pilot.selection.records) == 7
    for record in pilot.selection.records:
        data = json.loads((output / "dataset" / record.image_gt.path).read_text())
        base, _ = render_pdf_page(output / "dataset" / record.pdf.path, dpi=72)
        replay_noise(base, data["metadata"]["noise_generation"])
    run = output / "run"
    run.mkdir()
    (run / "run.json").write_text(json.dumps({"plan_id": pilot.plan_id, "engine": "tesseract", "configuration_sha256": "test"}))
    rows = [{"artifact_id": r.artifact_id, "plan_id": pilot.plan_id, "engine": "tesseract", "configuration_sha256": "test",
             "profile": r.profile, "status": "success", "metrics": metrics(5)} for r in pilot.selection.records]
    ledger = run / "results.jsonl"
    ledger.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    validation = write_calibration_results(output)
    assert validation["selected_images"] == validation["successful_images"] == 7
    assert (output / "dashboard.html").exists() and (output / "calibration_summary.csv").exists()
    assert "plotly" in (output / "dashboard.html").read_text(encoding="utf-8").lower()
    _check_report_selectors(output / "dashboard.html")
    with pytest.raises(ValueError, match="new or empty"):
        generate_calibration(plan, corpus, output)
    changed = [dict(row) for row in rows]
    changed[0]["profile"] = "wrong_profile"
    ledger.write_text("\n".join(json.dumps(r) for r in changed), encoding="utf-8")
    with pytest.raises(ValueError, match="configuration"):
        write_calibration_results(output)
    ledger.write_text("\n".join(json.dumps(r) for r in rows[:-1]), encoding="utf-8")
    with pytest.raises(ValueError, match="every selected"):
        write_calibration_results(output)
    alternate_spec = spec().model_copy(update={"dpi": 144})
    alternate = prepare_calibration(build_manifest(corpus), alternate_spec, base_pages=1, split="unassigned")
    (output / "calibration_plan.json").write_text(alternate.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="settings differ"):
        write_calibration_results(output)
    alternate = prepare_calibration(build_manifest(corpus), spec(repeats=1), base_pages=1, split="unassigned")
    (output / "calibration_plan.json").write_text(alternate.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="frozen calibration matrix"):
        write_calibration_results(output)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_timeout_fails_before_any_generation(tmp_path, timeout):
    plan = prepare_calibration(make_inventory(), spec(), base_pages=1, split="unassigned")
    output = tmp_path / "must_not_exist"
    with pytest.raises(ValueError, match="finite and positive"):
        run_calibration(plan, tmp_path, output, timeout_per_image=timeout)
    assert not output.exists()


def _check_report_selectors(path):
    # Optional JS logic check; this does not substitute for browser layout QA.
    if shutil.which("node") is None:
        return
    from bs4 import BeautifulSoup

    page = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    payload = json.loads(page.find("script", id="data").string)
    script = page.find_all("script")[-1].string
    check = r"""
const assert=require('node:assert/strict'),vm=require('node:vm');
const input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const element=()=>({value:'',textContent:'',children:[],addEventListener(){},
 appendChild(x){this.children.push(x)},replaceChildren(){this.children=[]}});
const nodes=Object.fromEntries(['data','effect','scope','metric','coverage','values'].map(id=>[id,element()]));
nodes.data.textContent=JSON.stringify(input.payload);
nodes.effect.value=input.payload.rows[0].operation;nodes.scope.value='0';nodes.metric.value='micro_CER';
let plots=[];const context=vm.createContext({document:{getElementById:id=>nodes[id],createElement:element},
 Plotly:{react(...args){plots.push(args)}}});
vm.runInContext(input.script,context);
for(const operation of new Set(input.payload.rows.map(r=>r.operation))){
 for(let scope=0;scope<input.payload.scopes.length;scope++)for(const metric of ['micro_CER','micro_WER','line_F1']){
  nodes.effect.value=operation;nodes.scope.value=String(scope);nodes.metric.value=metric;plots=[];
  vm.runInContext('draw()',context);
  const [dimension,group]=input.payload.scopes[scope];
  const rows=input.payload.rows.filter(r=>r.operation===operation&&r.dimension===dimension&&r.group===group).sort((a,b)=>a.level-b.level);
  assert.equal(plots.length,2);assert.equal(plots[0][0],'absolute');assert.equal(plots[1][0],'delta');
  assert.deepEqual(Array.from(plots[0][1][1].y),rows.map(r=>r['noisy_'+metric]));
  assert.deepEqual(Array.from(plots[1][1][0].y),rows.map(r=>r['delta_'+metric]===null?null:r['delta_'+metric]*(metric==='line_F1'?1:100)));
  assert.equal(nodes.values.children.length,rows.length);
 }
}
"""
    result = subprocess.run([shutil.which("node"), "-e", check], input=json.dumps({"payload": payload, "script": script}),
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
