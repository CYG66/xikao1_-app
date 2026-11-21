"""Wiring-03A: project-toolbar candidate exit must match accepted/draft state."""
from __future__ import annotations

import json
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import PropertyMock, patch

from app.agent_service import RobotAgentService
from app.cad_candidate_state import candidate_is_reviewable_draft
from app.cad_source_acceptance import extract_scoped_primitives
from app.creative_projects import CreativeProjectStore
from app.routers import projects

TEXT = (
    "完整部件清单：\n"
    "外圆：圆，圆心(0,0)，半径1米，坐标单位米；"
    "左眼：圆，圆心(-0.35,0.35)，半径0.09米，坐标单位米；"
    "右眼：圆，圆心(0.35,0.35)，半径0.09米，坐标单位米"
)
POSITIVE_SOURCE = "生成一个图案。" + TEXT


def _steps() -> list[dict]:
    specs = extract_scoped_primitives(TEXT)
    result = []
    for index, spec in enumerate(specs):
        result.append({
            "op": "add_circle",
            "step_id": f"s{index}",
            "output_ref": f"r{index}",
            "semantic": {
                "label": spec["subject"],
                "object_id": f"r{index}",
                "assembly_id": "whole",
                "assembly_label": "图案",
            },
            "center": {"x": spec["center"][0] / 1000, "y": spec["center"][1] / 1000},
            "radius": spec["radius"] / 1000,
        })
    return result


def _envelope(source: str) -> str:
    return json.dumps({
        "schema_version": "cad.construction-interpretation.v1",
        "is_construction_request": True,
        "confidence": 0.99,
        "evidence_text": [source],
        "assumptions": [],
        "plan": {"units": "m", "steps": _steps()},
    }, ensure_ascii=False)


def _run_service(source: str, name: str):
    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "deepseek"
    store = CreativeProjectStore(Path(tempfile.mkdtemp()) / "projects.json")
    project = store.create(
        name,
        source,
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

    def outlet(messages, **_kwargs):
        calls.append(messages[-1]["content"])
        return _envelope(source)

    with patch("app.agent_service.get_creative_project_store", return_value=store), \
         patch.object(
             RobotAgentService,
             "configured",
             new_callable=PropertyMock,
             return_value=True,
         ), \
         patch.object(service, "_structured_review_text", side_effect=outlet):
        raw = service._formal_cad_construction(source, route, mode="advanced")
    return raw, project["id"], len(calls)


def _route(raw: dict, project_id: str) -> dict:
    with patch.object(
        projects.robot_agent,
        "generate_project_candidate",
        return_value=deepcopy(raw),
    ):
        return projects.generate_creative_project_candidate(project_id)


def test_accepted_candidate_stays_deliverable():
    raw, project_id, model_calls = _run_service(POSITIVE_SOURCE, "accepted")
    assert model_calls == 1
    assert raw["variant"]["acceptance_summary"]["status"] == "passed"

    routed = _route(raw, project_id)

    assert routed["ok"] is True
    assert routed["next_action"] == "select_design_variant"
    assert routed["candidate_visibility"] == {
        "status": "visible",
        "scope": "project",
    }
    assert routed["variant"]["id"] == raw["variant"]["id"]
    assert [item["id"] for item in routed["variants"]] == [raw["variant"]["id"]]
    assert [item["id"] for item in routed["project"]["variants"]] == [raw["variant"]["id"]]
    assert routed["preview_paths"]
    assert routed["drawing_json"] is not None
    assert routed.get("draft_preview") is None
    assert [item["kind"] for item in routed["tool_results"]] == ["candidate_commit"]


def test_review_required_draft_has_preview_but_no_formal_candidate():
    raw, project_id, model_calls = _run_service(
        POSITIVE_SOURCE + "；嘴巴为一条微笑曲线",
        "review_required",
    )
    assert model_calls == 1
    assert raw["variant"]["acceptance_summary"]["status"] == "review_required"
    assert candidate_is_reviewable_draft(raw["variant"]) is True

    routed = _route(raw, project_id)

    assert routed["ok"] is True
    assert routed["next_action"] == "review_cad_draft"
    assert routed["candidate_visibility"] == {
        "status": "draft_review",
        "scope": "project",
    }
    assert routed["variant"] is None
    assert routed["variants"] == []
    assert routed["preview_paths"] == []
    assert routed["drawing_json"] is None
    assert routed["construction_commit"] is None
    assert routed["project"]["variants"] == []
    assert routed["tool_results"] == []
    draft = routed["draft_preview"]
    assert draft["variant_id"] == raw["variant"]["id"]
    assert draft["status"] == "review_required"
    assert draft["selectable"] is False
    assert draft["construction_authorized"] is False
    assert draft["acceptance_summary"]["review_required"] is True
    assert len(draft["preview_paths"]) == len(raw["preview_paths"]) > 0


def test_no_candidate_does_not_claim_selection_success():
    raw = {
        "ok": True,
        "message": "候选写入失败",
        "next_action": "select_design_variant",
        "variant": None,
        "variants": [{"id": "stale-draft"}],
        "preview_paths": [{"path": "stale.svg"}],
        "drawing_json": {"lines": [{"x1": 0, "y1": 0, "x2": 1, "y2": 1}]},
        "construction_commit": {"recommended_candidate_id": "stale-draft"},
        "project": {"id": "p1", "variants": [{"id": "stale-draft"}]},
        "project_id": "p1",
        "tool_results": [{"ok": True, "kind": "candidate_commit", "variant_id": "stale-draft"}],
    }

    routed = _route(raw, "p1")

    assert routed["ok"] is False
    assert routed["next_action"] == "review_acceptance"
    assert routed["variant"] is None
    assert routed["variants"] == []
    assert routed["preview_paths"] == []
    assert routed["drawing_json"] is None
    assert routed["tool_results"] == []
    assert routed.get("draft_preview") is None
    assert "stale-draft" not in json.dumps(routed, ensure_ascii=False)


def test_no_candidate_keeps_original_retry_error():
    raw = {
        "ok": False,
        "message": "模型输出超时，请重试",
        "next_action": "retry_candidate_generation",
        "variant": None,
        "variants": [],
        "preview_paths": [],
        "drawing_json": None,
        "project": {"id": "p2", "variants": []},
        "project_id": "p2",
        "tool_results": [],
    }

    routed = _route(raw, "p2")

    assert routed["ok"] is False
    assert routed["next_action"] == "retry_candidate_generation"
    assert routed["message"] == "模型输出超时，请重试"
    assert routed["variant"] is None
    assert routed["variants"] == []

