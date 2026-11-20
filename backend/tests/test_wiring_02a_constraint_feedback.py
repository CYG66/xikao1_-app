"""Wiring-02A: solver diagnostics reach the actual repair model input.

Only the model text outlet is mocked.  The real executor, interpreter, repair
loop and isolated project store run.  No real model call is made.
"""
from __future__ import annotations

import json
from unittest.mock import PropertyMock, patch

import pytest

from app.agent_service import RobotAgentService
from app.cad_construction import ConstructionPlanError, execute_construction_plan
from app.creative_projects import CreativeProjectStore

SOURCE = "生成三个圆，圆心(0,0)、圆心(10,0)、圆心(3,0)，半径均为1米，坐标单位米。"
PLAN = {
    "schema_version": "cad.construction-plan.v1",
    "units": "m",
    "steps": [
        {
            "op": "add_circle", "step_id": f"s-{ref}", "output_ref": ref,
            "semantic": {"label": ref, "object_id": ref,
                         "assembly_id": "whole", "assembly_label": "图案"},
            "center": {"x": x, "y": 0}, "radius": 1,
        }
        for ref, x in (("A", 0), ("B", 10), ("C", 3))
    ],
    "constraints": [
        {"kind": "concentric", "constraint_id": "c-a",
         "target_ref": "C", "reference_ref": "A"},
        {"kind": "concentric", "constraint_id": "c-b",
         "target_ref": "C", "reference_ref": "B"},
    ],
}
ENVELOPE = json.dumps({
    "schema_version": "cad.construction-interpretation.v1",
    "is_construction_request": True,
    "confidence": 0.99,
    "evidence_text": [SOURCE],
    "assumptions": [],
    "plan": PLAN,
}, ensure_ascii=False)


def test_executor_error_keeps_existing_solver_diagnostics():
    with pytest.raises(ConstructionPlanError) as failure:
        execute_construction_plan(PLAN)
    details = failure.value.details or {}
    assert failure.value.code == "constraint_residual_exceeded"
    assert failure.value.constraint_id == "c-a"
    assert details["category"] == "constraint_unsatisfied"
    assert len(details["reports"]) == 2
    assert len(details["failed_constraints"]) == 1
    failed = details["failed_constraints"][0]
    assert failed["constraint_id"] == "c-a"
    assert failed["residual"] == pytest.approx(10000.0)
    assert failed["tolerance"] == pytest.approx(1.0)
    assert failed["metric"] == "distance_mm"


def test_diagnostics_reach_second_model_repair_input_and_no_candidate(tmp_path):
    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "deepseek"
    store = CreativeProjectStore(tmp_path / "projects.json")
    project = store.create(
        "constraint-feedback", SOURCE,
        requirements={"shape": "generic_2d_cad"}, missing_parameters=[],
    )
    route = {
        "name": "drawing_design", "operation": "create",
        "stage": "candidate_generation", "selected_project_id": project["id"],
    }
    calls: list[str] = []

    def outlet(messages, **_kwargs):
        calls.append(messages[-1]["content"])
        return ENVELOPE

    with patch("app.agent_service.get_creative_project_store", return_value=store), \
         patch.object(RobotAgentService, "configured", new_callable=PropertyMock,
                      return_value=True), \
         patch.object(service, "_structured_review_text", side_effect=outlet):
        result = service._formal_cad_construction(SOURCE, route, mode="advanced")

    assert len(calls) == 2
    repair_prompt = calls[1]
    feedback_start = repair_prompt.find("\n后端试算反馈")
    feedback_end = repair_prompt.find("\n前次未通过", feedback_start)
    feedback = repair_prompt[feedback_start:feedback_end if feedback_end >= 0 else None]
    assert feedback_start >= 0
    assert '"failed_constraints"' in feedback
    assert '"reports"' in feedback
    assert '"residual": 10000.0' in feedback
    assert '"tolerance": 1.0' in feedback
    assert '"constraint_id": "c-a"' in feedback

    reloaded = CreativeProjectStore(tmp_path / "projects.json").get(project["id"]) or {}
    assert not (reloaded.get("variants") or [])
    assert result.get("ok") is False
