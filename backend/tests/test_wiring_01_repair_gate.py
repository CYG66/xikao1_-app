"""Wiring-01 C1: determined object-count failure enters the existing repair loop.

Mock boundary: only ``_structured_review_text`` (the model text outlet).  The
production repair loop, executor, independent acceptance, commit and isolated
store are real.  No real model or network call is made.
"""
from __future__ import annotations

import json
from unittest.mock import PropertyMock, patch

from app.agent_service import RobotAgentService
from app.cad_candidate_state import accepted_project_view, candidate_is_accepted
from app.creative_projects import CreativeProjectStore

COUNT_SOURCE = "两个立方体并排，画等轴投影"


def _envelope(source: str, steps: list[dict], confidence: float = .99) -> str:
    return json.dumps({
        "schema_version": "cad.construction-interpretation.v1",
        "is_construction_request": True,
        "confidence": confidence,
        "evidence_text": [source],
        "assumptions": [],
        "plan": {"units": "m", "steps": steps},
    }, ensure_ascii=False)


def _cube(ref: str, x: float) -> dict:
    return {
        "op": "add_polyline", "step_id": ref, "output_ref": ref,
        "semantic": {"label": "立方体", "object_id": ref,
                     "assembly_id": "whole", "assembly_label": "图案"},
        "closed": True,
        "vertices": [{"x": x, "y": 0}, {"x": x + 1, "y": -.5},
                     {"x": x + 2, "y": 0}, {"x": x + 2, "y": 2},
                     {"x": x + 1, "y": 2.5}, {"x": x, "y": 2}],
    }


def _run(tmp_path, source: str, payloads, name: str):
    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "deepseek"
    store = CreativeProjectStore(tmp_path / "projects.json")
    project = store.create(name, source, requirements={"shape": "generic_2d_cad"},
                           missing_parameters=[])
    route = {"name": "drawing_design", "operation": "create",
             "stage": "candidate_generation", "selected_project_id": project["id"]}
    with patch("app.agent_service.get_creative_project_store", return_value=store), \
         patch.object(RobotAgentService, "configured", new_callable=PropertyMock,
                      return_value=True), \
         patch.object(service, "_structured_review_text", side_effect=payloads) as outlet:
        result = service._formal_cad_construction(source, route, mode="advanced")
    reloaded = CreativeProjectStore(tmp_path / "projects.json").get(project["id"]) or {}
    variants = reloaded.get("variants") or []
    return result, {
        "outlet_calls": outlet.call_count,
        "draft_count": len(variants),
        "accepted_count": len((accepted_project_view(reloaded) or {}).get("variants") or []),
        "accepted": [candidate_is_accepted(v) for v in variants],
    }


def test_determined_missing_object_enters_existing_bounded_repair(tmp_path):
    bad = _envelope(COUNT_SOURCE, [_cube("cube-1", 0)])
    good = _envelope(COUNT_SOURCE, [_cube("cube-1", 0), _cube("cube-2", 4)])
    result, state = _run(tmp_path, COUNT_SOURCE, [bad, good], "立方体数量")
    assert state["outlet_calls"] == 2
    recovery = (result["construction_commit"] or {})["recovery"]
    assert recovery["repair_count"] == 1
    assert recovery["max_repairs"] == 2
    first = recovery["attempts"][0]
    assert first["status"] == "invalid"
    assert first["error"]["code"] == "object_count_mismatch"
    assert first["error"]["details"]["reason"] == "missing_object"
    assert first["error"]["details"]["expected_count"] == 2
    assert first["error"]["details"]["actual_count"] == 1
