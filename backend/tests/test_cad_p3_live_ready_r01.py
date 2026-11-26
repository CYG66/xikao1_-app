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


def _invalid_payload(vector: dict, tag: str = "a") -> dict:
    return {
        "schema": "cad.construction-interpretation-result.v1",
        "status": "invalid",
        "parser": "structured_model",
        "provider_attempted": True,
        "confidence": 0.4,
        "plan": {"units": "m", "steps": [], "attempt_tag": tag},
        "rejected_plan": {"units": "m", "steps": [], "attempt_tag": tag},
        "residual_vector": vector,
        "construction_error": {
            "code": f"radius_mismatch_{tag}",
            "details": {"affected_output_refs": ["outer_ref"]},
        },
        "error": {"code": f"radius_mismatch_{tag}", "message": f"外圆半径错误 {tag}"},
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
