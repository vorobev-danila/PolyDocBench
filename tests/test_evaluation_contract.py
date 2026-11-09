import json

import pytest

from polydocbench.benchmark.calibration import CalibrationPlan, CalibrationSpec, NoiseSweep, prepare_calibration, summarize_calibration
from polydocbench.eval.contract import EvaluationSettings, FrozenEvaluation, freeze_evaluation
from polydocbench.eval.protocol import result_protocol_version
from polydocbench.provenance import json_sha256
from test_benchmark_pilot import make_inventory
from test_noise_calibration import rows_for, spec as legacy_spec


def test_contract_freezes_choices_code_and_geometry():
    contract = freeze_evaluation(EvaluationSettings())
    contract.verify_runtime()
    assert FrozenEvaluation.model_validate_json(contract.model_dump_json()) == contract
    assert freeze_evaluation(EvaluationSettings(quality_iou=0.5)).contract_id != contract.contract_id
    data = contract.model_dump()
    data["settings"]["quality_iou"] = 0.8
    with pytest.raises(ValueError, match="seal"):
        FrozenEvaluation.model_validate(data)
    changed = contract.model_dump(exclude={"contract_id"})
    changed["implementation_files"][0]["sha256"] = "0" * 64
    stale = FrozenEvaluation(contract_id=json_sha256(changed), **changed)
    with pytest.raises(ValueError, match="implementation"):
        stale.verify_runtime()


def test_legacy_calibration_plan_roundtrip_does_not_change_serialized_seal():
    spec = legacy_spec()
    assert "evaluation_contract" not in spec.model_dump()
    plan = prepare_calibration(make_inventory(), spec, base_pages=1, split="unassigned")
    assert CalibrationPlan.model_validate_json(plan.model_dump_json()) == plan
    assert json_sha256(plan.model_dump(exclude={"plan_id"})) == plan.plan_id
    with pytest.raises(ValueError, match="requires"):
        CalibrationSpec(evaluation_protocol_version="0.3", sweeps=spec.sweeps)


def test_scoped_calibration_rejects_mixed_contracts_and_thresholds():
    contract = freeze_evaluation(EvaluationSettings())
    spec = CalibrationSpec(evaluation_protocol_version="0.3", evaluation_contract=contract,
                           sweeps=[NoiseSweep(operation="defocus_blur", parameter="sigma_pixels", levels=[0.8, 1.6])])
    plan = prepare_calibration(make_inventory(), spec, base_pages=1, split="unassigned")
    rows = rows_for(plan)
    # Minimal sufficient scoped rows for aggregation; no inference is fabricated.
    for row in rows:
        row["metrics"].update(evaluation_protocol_version="0.3", evaluation_contract_id=contract.contract_id,
                              scope_policy_id=contract.visibility_policy_id, scope_task="quality", scope_unit="line",
                              matching_iou_threshold=0.3, scope_input_gt=10, scope_eligible_gt=10,
                              scope_excluded_gt=0, scope_input_predictions=10, scope_retained_predictions=10,
                              scope_ignored_predictions=0, scope_empty_gt_images=0,
                              scope_canvas_area_pixels=10000, scope_ignored_area_pixels=0,
                              scope_unlocalized_predictions=0, scope_protected_predictions=0,
                              scope_excluded_fully_clipped=0, scope_excluded_partially_clipped=0,
                              scope_excluded_incomplete_text_block=0, scope_excluded_manual_region=0,
                              scope_policy_status="candidate_not_publication_approved")
    summary, pairs = summarize_calibration(plan, rows)
    assert summary[0]["evaluation_protocol_version"] == "0.3"
    assert summary[0]["clean_scope_eligible_gt"] == 10 and all(p["paired"] for p in pairs)
    rows[-1]["metrics"]["matching_iou_threshold"] = 0.5
    with pytest.raises(ValueError, match="contract"):
        summarize_calibration(plan, rows)
    with pytest.raises(ValueError, match="contracts"):
        result_protocol_version([rows[0]["metrics"], {**rows[0]["metrics"], "evaluation_contract_id": None}])
