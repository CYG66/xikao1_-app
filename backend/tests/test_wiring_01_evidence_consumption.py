"""Wiring-01 C2: measured source-scope evidence is consumed by later gates.

Mock boundary: only ``_structured_review_text`` (the model text outlet).  The
production executor, independent source/identity/count acceptance, commit and
isolated store are real.  No real model or network call is made.
"""
from __future__ import annotations

import json
from unittest.mock import PropertyMock, patch

import pytest

from app.agent_service import RobotAgentService
from app.cad_candidate_state import accepted_project_view, candidate_is_accepted
from app.cad_source_acceptance import extract_scoped_primitives
from app.creative_projects import CreativeProjectStore

TEXT = ("完整部件清单：\n"
        "外圆：圆，圆心(0,0)，半径1米，坐标单位米；"
        "左眼：圆，圆心(-0.35,0.35)，半径0.09米，坐标单位米；"
        "右眼：圆，圆心(0.35,0.35)，半径0.09米，坐标单位米")
POSITIVE_SOURCE = "生成一个图案。" + TEXT


def _envelope(source: str, steps: list[dict], confidence: float = .99) -> str:
    return json.dumps({
        "schema_version": "cad.construction-interpretation.v1",
        "is_construction_request": True,
        "confidence": confidence,
        "evidence_text": [source],
        "assumptions": [],
        "plan": {"units": "m", "steps": steps},
    }, ensure_ascii=False)


def _circle_steps(*, wrong_radius: bool = False, missing_last: bool = False,
                  wrong_binding: bool = False) -> list[dict]:
    specs = extract_scoped_primitives(TEXT)
    if missing_last:
        specs = specs[:-1]
    steps = []
    for i, spec in enumerate(specs):
        label = spec["subject"]
        object_id = f"r{i}"
        if wrong_binding and i == 0:
            label, object_id = "右眼", "r1"
        elif wrong_binding and i == 2:
            label, object_id = "左眼", "r2"
        elif wrong_binding and i == 1:
            label, object_id = "外圆", "r0"
        radius = spec["radius"] / 1000
        if wrong_radius and i == 0:
            radius += .2
        steps.append({
            "op": "add_circle", "step_id": f"s{i}", "output_ref": f"r{i}",
            "semantic": {"label": label, "object_id": object_id,
                         "assembly_id": "whole", "assembly_label": "图案"},
            "center": {"x": spec["center"][0] / 1000, "y": spec["center"][1] / 1000},
            "radius": radius,
        })
    return steps


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


def test_complete_scoped_positive_becomes_accepted_candidate(tmp_path):
    steps = _circle_steps()
    result, state = _run(tmp_path, POSITIVE_SOURCE,
                         [_envelope(POSITIVE_SOURCE, steps)], "三圆正例")
    assert state["outlet_calls"] == 1
    assert state["accepted_count"] == 1
    assert state["accepted"] == [True]
    assert (result["construction_commit"] or {}).get("persisted_candidate_count") == 1


@pytest.mark.parametrize("mutation", ["unknown_clause", "unknown_clause_comma",
                                      "repeated_center", "wrong_dimension",
                                      "missing_object", "wrong_binding"])
def test_bad_variant_of_the_same_positive_is_not_accepted(tmp_path, mutation):
    source = POSITIVE_SOURCE
    if mutation == "unknown_clause":
        source += "；嘴巴为一条微笑曲线"
        steps = _circle_steps()
    elif mutation == "unknown_clause_comma":
        source += "，嘴巴为一条微笑曲线"
        steps = _circle_steps()
    elif mutation == "repeated_center":
        source += "，圆心(9,9)"
        steps = _circle_steps()
    elif mutation == "wrong_dimension":
        steps = _circle_steps(wrong_radius=True)
    elif mutation == "missing_object":
        steps = _circle_steps(missing_last=True)
    else:
        steps = _circle_steps(wrong_binding=True)
    payload = _envelope(source, steps)
    result, state = _run(tmp_path, source, [payload], mutation)
    assert state["accepted_count"] == 0
    assert not any(state["accepted"])
