"""R01 production-entry tests for repair budget and ready-result regression."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import PropertyMock, patch

from app.agent_service import RobotAgentService
from app.cad_residual_repair import (
    discrete_residual,
    numeric_residual,
    residual_vector,
)
from app.creative_projects import CreativeProjectStore

SOURCE = "生成一个太极图，外圆半径2米，S形分割线，两个对称小圆"
COMPOSITE_SOURCE = "画一个矩形宽4米高2米，在四个角各放一个半径0.5米的圆"


def _ready_payload() -> dict:
    return {
        "schema": "cad.construction-interpretation-result.v1",
        "status": "ready",
        "parser": "structured_model",
        "provider_attempted": True,
        "confidence": 0.9,
        "plan": {"units": "m", "steps": []},
        "acceptance_summary": {"status": "passed", "review_required": False},
    }


def _invalid_payload(
    vector: dict,
    tag: str = "a",
    *,
    model_required: bool = False,
    error_code: str | None = None,
) -> dict:
    code = error_code or f"radius_mismatch_{tag}"
    payload = {
        "schema": "cad.construction-interpretation-result.v1",
        "status": "invalid",
        "parser": "structured_model",
        "provider_attempted": True,
        "confidence": 0.4,
        "plan": {"units": "m", "steps": [], "attempt_tag": tag},
        "rejected_plan": {"units": "m", "steps": [], "attempt_tag": tag},
        "residual_vector": vector,
        "construction_error": {
            "code": code,
            "details": {"affected_output_refs": ["outer_ref"]},
        },
        "error": {"code": code, "message": f"外圆半径错误 {tag}"},
    }
    if model_required:
        payload["model_required"] = True
    return payload


def _curve_clarification_payload() -> dict:
    return {
        "schema": "cad.construction-interpretation-result.v1",
        "status": "clarification_required",
        "parser": "structured_model",
        "provider_attempted": True,
        "confidence": 0.4,
        "clarification": {
            "question_key": "curve_constraints",
            "question": "请提供曲线控制点",
            "suggested_prompt": "请提供曲线控制点",
        },
    }


def _run(payloads: list[dict]):
    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "deepseek"
    store = CreativeProjectStore(Path(tempfile.mkdtemp()) / "projects.json")
    project = store.create(
        "r01", SOURCE,
        requirements={"shape": "generic_2d_cad"},
        missing_parameters=[],
    )
    route = {
        "name": "drawing_design",
        "operation": "create",
        "stage": "candidate_generation",
        "selected_project_id": project["id"],
    }
    calls = []

    def plan(_model_input, **_kwargs):
        calls.append("plan")
        return payloads[min(len(calls) - 1, len(payloads) - 1)]

    with patch("app.agent_service.get_creative_project_store", return_value=store), \
         patch.object(
             RobotAgentService,
             "configured",
             new_callable=PropertyMock,
             return_value=True,
         ), \
         patch.object(
             service,
             "_interpret_cad_construction_plan",
             side_effect=plan,
         ), \
         patch(
             "app.cad_construction_interpreter.interpret_sketch_graph_candidates",
             side_effect=AssertionError("alternative path must not bypass budget"),
         ):
        raw = service._formal_cad_construction(SOURCE, route, mode="advanced")
    return raw, calls


def test_two_automatic_repairs_are_hard_ceiling_in_production_entry():
    failed = residual_vector([numeric_residual(
        requirement_id="R-OUTER", predicate="radius", expected=2000,
        measured=500, tolerance=0.5, mandatory=True, predicate_axis="outer_ref")])
    payloads = [
        _invalid_payload(failed, "a"),
        _invalid_payload(failed, "b"),
        _invalid_payload(failed, "c"),
    ]
    raw, calls = _run(payloads)
    interpretation = raw["construction_interpretation"]
    assert len(calls) == 3  # initial plan + exactly two repairs
    assert interpretation["status"] == "invalid"
    assert interpretation["repair_execution_ledger"]["automatic_repairs"] == 2
    assert interpretation["repair_execution_ledger"]["alternative_candidate_requests"] == 0


def test_ready_result_missing_previously_passed_requirement_is_rejected():
    passed_width = numeric_residual(
        requirement_id="R-WIDTH", predicate="width", expected=2000,
        measured=2000, tolerance=0.5, mandatory=True, predicate_axis="outer_ref")
    failed_radius = numeric_residual(
        requirement_id="R-OUTER", predicate="radius", expected=2000,
        measured=500, tolerance=0.5, mandatory=True, predicate_axis="outer_ref")
    first = _invalid_payload(residual_vector([passed_width, failed_radius]))
    missing_width_ready = _ready_payload()
    missing_width_ready["residual_vector"] = residual_vector([numeric_residual(
        requirement_id="R-OUTER", predicate="radius", expected=2000,
        measured=2000, tolerance=0.5, mandatory=True, predicate_axis="outer_ref")])
    payloads = [first, missing_width_ready, missing_width_ready]
    raw, calls = _run(payloads)
    interpretation = raw["construction_interpretation"]
    assert len(calls) == 2  # ready regression is terminal, not retried blindly
    assert interpretation["status"] == "invalid"
    assert interpretation["error"]["code"] == "mandatory_requirement_regressed"
    assert interpretation["mandatory_regression"]["regressions"]


def test_curve_constraint_replan_consumes_budget_before_the_loop():
    failed = residual_vector([numeric_residual(
        requirement_id="R-OUTER", predicate="radius", expected=2000,
        measured=500, tolerance=0.5, mandatory=True, predicate_axis="outer_ref")])
    payloads = [
        _curve_clarification_payload(),
        _invalid_payload(failed, "curve-retry"),
        _invalid_payload(failed, "loop-repair"),
        _invalid_payload(failed, "must-not-run"),
    ]
    raw, calls = _run(payloads)
    ledger = raw["construction_interpretation"]["repair_execution_ledger"]
    assert len(calls) == 3  # initial + curve replan + one remaining repair
    assert ledger["clarification_replans"] == 1
    assert ledger["automatic_repairs"] == 2


def test_model_required_retry_consumes_budget_before_the_loop():
    failed = residual_vector([numeric_residual(
        requirement_id="R-OUTER", predicate="radius", expected=2000,
        measured=500, tolerance=0.5, mandatory=True, predicate_axis="outer_ref")])
    payloads = [
        _invalid_payload(failed, "initial", model_required=True),
        _invalid_payload(failed, "required-retry"),
        _invalid_payload(failed, "loop-repair"),
        _invalid_payload(failed, "must-not-run"),
    ]
    raw, calls = _run(payloads)
    ledger = raw["construction_interpretation"]["repair_execution_ledger"]
    assert len(calls) == 3  # initial + model-required retry + one remaining repair
    assert ledger["model_required_retries"] == 1
    assert ledger["automatic_repairs"] == 2


def test_two_legacy_replans_share_the_same_two_repair_budget():
    failed = residual_vector([numeric_residual(
        requirement_id="R-OUTER", predicate="radius", expected=2000,
        measured=500, tolerance=0.5, mandatory=True, predicate_axis="outer_ref")])
    payloads = [
        _curve_clarification_payload(),
        _invalid_payload(failed, "curve-retry", model_required=True),
        _invalid_payload(failed, "required-retry"),
        _invalid_payload(failed, "must-not-run"),
    ]
    raw, calls = _run(payloads)
    ledger = raw["construction_interpretation"]["repair_execution_ledger"]
    assert len(calls) == 3  # initial + curve replan + model-required retry
    assert ledger["automatic_repairs"] == 2
    assert ledger["clarification_replans"] == 1
    assert ledger["model_required_retries"] == 1


def _run_alternative(payloads: list[dict], *, trial_ready: bool):
    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "deepseek"
    store = CreativeProjectStore(Path(tempfile.mkdtemp()) / "projects.json")
    project = store.create(
        "r01-alt", COMPOSITE_SOURCE,
        requirements={"shape": "generic_2d_cad"},
        missing_parameters=[],
    )
    route = {
        "name": "drawing_design",
        "operation": "create",
        "stage": "candidate_generation",
        "selected_project_id": project["id"],
    }
    calls = []

    def plan(_model_input, **_kwargs):
        calls.append("plan")
        return payloads[min(len(calls) - 1, len(payloads) - 1)]

    alternatives = {
        "status": "ok",
        "confidence": 0.5,
        "candidate_set": {"candidates": [{
            "candidate_id": "alt-1",
            "plan": {"units": "m", "steps": []},
        }]},
    }
    trial = _ready_payload() if trial_ready else _invalid_payload(
        residual_vector([numeric_residual(
            requirement_id="R-OUTER", predicate="radius", expected=2000,
            measured=500, tolerance=0.5, mandatory=True, predicate_axis="outer_ref")]),
        "alt-trial",
    )

    with patch("app.agent_service.get_creative_project_store", return_value=store), \
         patch.object(
             RobotAgentService,
             "configured",
             new_callable=PropertyMock,
             return_value=True,
         ), \
         patch.object(service, "_interpret_cad_construction_plan", side_effect=plan), \
         patch.object(
             service,
             "_cad_construction_model_callback",
             return_value=(lambda *_args, **_kwargs: None, {"request_attempts": 1}),
         ), \
         patch(
             "app.cad_construction_interpreter.interpret_sketch_graph_candidates",
             return_value=alternatives,
         ), \
         patch(
             "app.cad_construction_interpreter.interpret_construction_request",
             return_value=trial,
         ):
        raw = service._formal_cad_construction(SOURCE, route, mode="advanced")
    return raw, calls


def test_failed_alternative_request_consumes_repair_capacity():
    failed = residual_vector([numeric_residual(
        requirement_id="R-OUTER", predicate="radius", expected=2000,
        measured=500, tolerance=0.5, mandatory=True, predicate_axis="outer_ref")])
    payloads = [
        _curve_clarification_payload(),
        _invalid_payload(failed, "no-loop", error_code="persistence_failed"),
    ]
    raw, calls = _run_alternative(payloads, trial_ready=False)
    ledger = raw["construction_interpretation"]["repair_execution_ledger"]
    assert len(calls) == 2  # initial + curve replan; alternative is the second repair
    assert ledger["automatic_repairs"] == 2
    assert ledger["alternative_candidate_requests"] == 1
    assert ledger["alternative_candidates_selected"] == 0


def test_selected_alternative_is_counted_once_at_request_time():
    failed = residual_vector([numeric_residual(
        requirement_id="R-OUTER", predicate="radius", expected=2000,
        measured=500, tolerance=0.5, mandatory=True, predicate_axis="outer_ref")])
    payloads = [
        _curve_clarification_payload(),
        _invalid_payload(failed, "no-loop", error_code="persistence_failed"),
    ]
    raw, calls = _run_alternative(payloads, trial_ready=True)
    ledger = raw["cad_generation_failure"]["repair_execution_ledger"]
    assert len(calls) == 2  # initial + curve replan; alternative request is the second repair
    assert ledger["automatic_repairs"] == 2
    assert ledger["alternative_candidate_requests"] == 1
    assert ledger["alternative_candidates_selected"] == 1

