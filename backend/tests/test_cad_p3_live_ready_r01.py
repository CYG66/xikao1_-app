"""R01 production-entry tests for repair budget and ready-result regression."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest

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

    def plan(_model_input, request_budget=None, planning_kind="initial", **_kwargs):
        if request_budget is not None:
            request_budget(planning_kind)
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
    assert ledger["replan_evidence"][0]["status"] == "clarification_required"


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


def test_ready_numeric_residual_enters_repair_and_reaches_independent_acceptance():
    from app.cad_residual_repair import feedback_text as real_feedback_text

    failing = numeric_residual(
        requirement_id="R-OUTER", predicate="radius", expected=2000,
        measured=500, tolerance=0.5, mandatory=True, predicate_axis="outer_ref",
        plan_step_ids=["outer_ref"])
    ready_failed = _ready_payload()
    ready_failed["acceptance_summary"] = {
        "status": "review_required", "review_required": True}
    ready_failed["residual_vector"] = residual_vector([failing])
    fixed = _ready_payload()
    fixed["residual_vector"] = residual_vector([numeric_residual(
        requirement_id="R-OUTER", predicate="radius", expected=2000,
        measured=2000, tolerance=0.5, mandatory=True, predicate_axis="outer_ref")])
    committed = {
        "schema": "cad.construction-commit.v1",
        "recommended_candidate_id": "mock-variant",
        "project": {"id": "mock-project", "status": "draft"},
        "recommended_variant": {
            "id": "mock-variant",
            "preview_paths": [],
            "geometries": [],
            "logical_objects": [],
            "topology": {},
            "acceptance_summary": {"status": "passed", "review_required": False},
        },
        "persisted_candidate_count": 1,
    }
    with patch("app.agent_service.commit_construction_interpretation",
               return_value=committed), \
         patch("app.cad_residual_repair.feedback_text",
               wraps=real_feedback_text) as feedback:
        raw, calls = _run([ready_failed, fixed])
    interpretation = raw.get("construction_interpretation") or {}
    ledger = (raw.get("construction_commit") or {}).get(
        "repair_execution_ledger") or {}
    assert raw.get("ok") is True, raw
    assert len(calls) == 2  # initial ready result + one actual repair callback
    assert ledger.get("automatic_repairs") == 1, (list(raw), ledger)
    assert feedback.call_count >= 1
    assert feedback.call_args.kwargs.get("residual_vector") or feedback.call_args.args
    assert interpretation.get("status", "ready") == "ready"


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


def _run_alternative(payloads: list[dict], *, trial_ready: bool,
                     should_repair_value: bool | None = None):
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
    alternative_calls = []

    def plan(_model_input, request_budget=None, planning_kind="initial", **_kwargs):
        if request_budget is not None:
            request_budget(planning_kind)
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

    def fake_model_callback(**kwargs):
        request_budget = kwargs.get("request_budget")
        if request_budget is not None:
            request_budget(kwargs.get("planning_kind", "repair"))
        alternative_calls.append("request")
        return (lambda *_args, **_kwargs: None, {"request_attempts": 1})

    patches = [
        patch("app.agent_service.get_creative_project_store", return_value=store),
        patch.object(
            RobotAgentService,
            "configured",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch.object(service, "_interpret_cad_construction_plan", side_effect=plan),
        patch.object(
            service,
            "_cad_construction_model_callback",
            side_effect=fake_model_callback,
        ),
        patch(
            "app.cad_construction_interpreter.interpret_sketch_graph_candidates",
            return_value=alternatives,
        ),
        patch(
            "app.cad_construction_interpreter.interpret_construction_request",
            return_value=trial,
        ),
    ]
    if should_repair_value is not None:
        patches.append(
            patch("app.agent_service.should_repair",
                  return_value=should_repair_value)
        )
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        if len(patches) > 6:
            with patches[6]:
                raw = service._formal_cad_construction(SOURCE, route, mode="advanced")
        else:
            raw = service._formal_cad_construction(SOURCE, route, mode="advanced")
    return raw, calls, alternative_calls


def test_failed_alternative_request_consumes_repair_capacity():
    failed = residual_vector([numeric_residual(
        requirement_id="R-OUTER", predicate="radius", expected=2000,
        measured=500, tolerance=0.5, mandatory=True, predicate_axis="outer_ref")])
    payloads = [
        _curve_clarification_payload(),
        _invalid_payload(failed, "no-loop"),
    ]
    raw, calls, alternative_calls = _run_alternative(
        payloads, trial_ready=False, should_repair_value=False)
    ledger = raw["construction_interpretation"]["repair_execution_ledger"]
    assert len(calls) == 2  # initial + curve replan; alternative is the second repair
    assert alternative_calls == ["request"]
    assert ledger["automatic_repairs"] == 2
    assert ledger["alternative_candidate_requests"] == 1
    assert ledger["alternative_candidates_selected"] == 0


def test_selected_alternative_is_counted_once_at_request_time():
    failed = residual_vector([numeric_residual(
        requirement_id="R-OUTER", predicate="radius", expected=2000,
        measured=500, tolerance=0.5, mandatory=True, predicate_axis="outer_ref")])
    payloads = [
        _curve_clarification_payload(),
        _invalid_payload(failed, "no-loop"),
    ]
    raw, calls, alternative_calls = _run_alternative(
        payloads, trial_ready=True, should_repair_value=False)
    ledger = raw["cad_generation_failure"]["repair_execution_ledger"]
    assert len(calls) == 2
    assert alternative_calls == ["request"]
    assert ledger["automatic_repairs"] == 2
    assert ledger["alternative_candidate_requests"] == 1
    assert ledger["alternative_candidates_selected"] == 1


def test_persistence_failure_does_not_trigger_alternative():
    failed = residual_vector([numeric_residual(
        requirement_id="R-OUTER", predicate="radius", expected=2000,
        measured=500, tolerance=0.5, mandatory=True, predicate_axis="outer_ref")])
    payloads = [_invalid_payload(failed, "persist", error_code="persistence_failed")]
    raw, calls, alternative_calls = _run_alternative(payloads, trial_ready=False)
    interpretation = raw.get("construction_interpretation") or raw["cad_generation_failure"]
    ledger = interpretation["repair_execution_ledger"]
    assert len(calls) == 1
    assert alternative_calls == []
    assert ledger["automatic_repairs"] == 0
    assert ledger["alternative_candidate_requests"] == 0


def test_transport_failure_does_not_trigger_alternative():
    failed = residual_vector([numeric_residual(
        requirement_id="R-OUTER", predicate="radius", expected=2000,
        measured=500, tolerance=0.5, mandatory=True, predicate_axis="outer_ref")])
    payload = _invalid_payload(failed, "transport")
    payload["transport_failed"] = True
    payload["error"] = {"code": "model_transport_failed", "message": "network"}
    raw, calls, alternative_calls = _run_alternative([payload], trial_ready=False)
    interpretation = raw.get("construction_interpretation") or raw["cad_generation_failure"]
    ledger = interpretation["repair_execution_ledger"]
    assert len(calls) == 1
    assert alternative_calls == []
    assert ledger["automatic_repairs"] == 0
    assert ledger["alternative_candidate_requests"] == 0


def test_case_ledger_survives_process_reconstruction(tmp_path):
    from app.agent_service import RepairExecutionLedger, RepairBudgetExhausted

    state_path = tmp_path / "repair-state" / "L05-C6.json"
    state_path.parent.mkdir(parents=True)
    first = RepairExecutionLedger(persist_path=state_path)
    assert first.reserve_plan_request("initial") == "initial"
    assert first.reserve_plan_request("json_format_retry") == "repair"
    assert first.automatic_repairs == 1
    assert first.json_format_retries == 1

    second = RepairExecutionLedger(persist_path=state_path)
    assert second.initial_plan_requests == 1
    assert second.actual_planning_requests == 2
    assert second.automatic_repairs == 1
    assert second.json_format_retries == 1
    # A new HTTP turn cannot reset the case budget: its first send is a repair.
    assert second.reserve_plan_request("initial") == "repair"
    assert second.automatic_repairs == 2
    with pytest.raises(RepairBudgetExhausted):
        second.reserve_plan_request("repair")
    assert second.actual_planning_requests == 3


def test_internal_json_retry_charges_before_the_second_send():
    from app.agent_service import RepairExecutionLedger, RepairBudgetExhausted

    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "deepseek"
    ledger = RepairExecutionLedger()
    with patch.object(
        RobotAgentService,
        "configured",
        new_callable=PropertyMock,
        return_value=True,
    ):
        callback, state = service._cad_construction_model_callback(
            request_budget=ledger.reserve_plan_request, planning_kind="initial")

    with patch.object(
        service, "_structured_review_text",
        side_effect=["not-json", '{"ok": true}'],
    ) as send:
        assert callback("source", {}) == {"ok": True}
    assert send.call_count == 2
    assert ledger.initial_plan_requests == 1
    assert ledger.actual_planning_requests == 2
    assert ledger.automatic_repairs == 1
    assert ledger.json_format_retries == 1
    assert state["request_attempts"] == 2

    # Next HTTP turn begins with an "initial" call, but the case baseline is
    # already consumed; its JSON retry must be blocked before the socket.
    with patch.object(
        service, "_structured_review_text", side_effect=["not-json", "not-json"],
    ) as send:
        with pytest.raises(RepairBudgetExhausted):
            callback("source", {})
    assert send.call_count == 1
    assert ledger.automatic_repairs == 2


def test_repair_budget_exception_crosses_interpreter_boundaries():
    from app.agent_service import RepairBudgetExhausted
    from app.cad_construction_interpreter import (
        interpret_construction_request,
        interpret_sketch_graph_candidates,
    )

    def exhausted(*_args, **_kwargs):
        raise RepairBudgetExhausted("no capacity")

    with pytest.raises(RepairBudgetExhausted):
        interpret_construction_request(
            SOURCE, exhausted, force_structured_model=True,
        )
    with pytest.raises(RepairBudgetExhausted):
        interpret_sketch_graph_candidates(SOURCE, exhausted)

