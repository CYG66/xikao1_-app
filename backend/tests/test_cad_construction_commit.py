from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.agent_service import RobotAgentService
from app.cad_construction_commit import (
    ConstructionCommitError,
    commit_construction_interpretation,
)
from app.cad_construction_interpreter import interpret_construction_request
from app.creative_projects import CreativeProjectStore


def _store(tmp_path: Path) -> CreativeProjectStore:
    return CreativeProjectStore(tmp_path / "projects.json")


def test_candidate_source_snapshot_survives_project_revision_and_restart(tmp_path):
    from app.cad_requirement_ledger import project_requirement_ledger
    store=_store(tmp_path)
    original="画一个矩形"
    followup="宽5米高3米，左下角(0,0)，坐标单位米"
    ledger=project_requirement_ledger(original,[followup])
    project=store.create("矩形",original,requirements={"shape":"generic_2d_cad",
        "dimensions":{"width_m":5,"height_m":3},"source_followups":[followup],
        "requirement_ledger":ledger},missing_parameters=[])
    interpretation=interpret_construction_request("画一个矩形，"+followup)
    committed=commit_construction_interpretation(original,interpretation,store=store,project_id=project["id"])
    saved=store.get(committed["project_id"])["variants"][0]["construction_record"]["requirement_ledger"]
    assert [s["text"] for s in saved["sources"]]==[original,followup]
    later=project_requirement_ledger(original,[followup,"宽度改成6米"],previous=ledger)
    store.update(project["id"],requirements={"requirement_ledger":later})
    restored=_store(tmp_path).get(project["id"])
    assert restored["requirements"]["requirement_ledger"]["revision_sha256"]!=ledger["revision_sha256"]
    assert restored["variants"][0]["construction_record"]["requirement_ledger"]==saved


def test_verified_construction_is_persisted_with_audit_record(
    tmp_path: Path,
) -> None:
    source = "画一条线段从(0,0)到(5,3)，坐标单位米"
    interpretation = interpret_construction_request(source)
    store = _store(tmp_path)

    committed = commit_construction_interpretation(
        source, interpretation, store=store
    )

    assert committed["persisted_candidate_count"] == 1
    project = store.get(committed["project_id"])
    assert project is not None
    assert project["status"] == "designing"
    variant = project["variants"][0]
    from app.cad_construction import construction_geometry_bounds
    assert construction_geometry_bounds(variant["geometries"]) == construction_geometry_bounds(
        interpretation["trial_result"]["geometries"]
    )
    assert variant["preview_paths"]
    assert variant["construction_record"]["schema"] == "cad.construction-record.v1"
    assert variant["construction_record"]["assertions"]["ok"] is True
    assert variant["logical_object_validation"]["verified"] is True
    snapshot=variant["construction_record"]["requirement_ledger"]
    assert snapshot["sources"][0]["text"]==source
    restored=_store(tmp_path).get(committed["project_id"])
    assert restored["variants"][0]["construction_record"]["requirement_ledger"]==snapshot


def test_invalid_interpretation_never_creates_project(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(ConstructionCommitError):
        commit_construction_interpretation(
            "画一个好看的复杂轮廓",
            {"status": "clarification_required"},
            store=store,
        )

    assert store.list() == []


def test_confirmed_construction_stays_in_existing_project(tmp_path: Path) -> None:
    store = _store(tmp_path)
    project = store.create("当前图纸", "画一条线段从(0,0)到(5,3)，坐标单位米",
                           {"shape": "generic_2d_cad"}, {}, [])
    interpretation = interpret_construction_request(project["original_prompt"])
    committed = commit_construction_interpretation(
        project["original_prompt"], interpretation, store=store, project_id=project["id"],
    )
    assert committed["project_id"] == project["id"]
    assert len(store.list()) == 1
    assert store.get(project["id"])["status"] == "designing"
    assert store.get(project["id"])["original_prompt"] == project["original_prompt"]


def test_existing_project_is_preserved_when_candidate_write_fails(tmp_path: Path) -> None:
    store = _store(tmp_path)
    project = store.create("当前图纸", "画一条线段从(0,0)到(5,3)，坐标单位米",
                           {"shape": "generic_2d_cad"}, {}, [])
    interpretation = interpret_construction_request(project["original_prompt"])
    with patch.object(store, "add_variant", side_effect=ValueError("write rejected")):
        with pytest.raises(ConstructionCommitError):
            commit_construction_interpretation(
                project["original_prompt"], interpretation, store=store, project_id=project["id"],
            )
    assert store.get(project["id"]) == project


def test_multiple_verified_candidates_are_committed_and_recommendation_is_kept(
    tmp_path: Path,
) -> None:
    first = interpret_construction_request("画一条线段从(0,0)到(5,3)，坐标单位米")
    second = interpret_construction_request("画一条线段从(0,0)到(8,0)，坐标单位米")
    interpretation = {
        "schema": "cad.sketchgraph-interpretation-result.v1",
        "status": "ready",
        "parser": "structured_model",
        "confidence": 0.91,
        "evidence_text": ["比较两个线段方案"],
        "assumptions": [],
        "normalization_facts": [],
        "deterministic_repairs": [],
        "acceptance_summary": {
            "status": "passed", "review_required": False,
            "authority": "backend_measured_geometry", "verified_checks": 2,
        },
        "evaluation": {
            "recommended_candidate_id": "long-line",
            "candidates": [
                {
                    "candidate_id": "short-line",
                    "title": "短线方案",
                    "rationale": "较短的直接连接。",
                    "status": "valid",
                    "rank": 2,
                    "trial_result": first["trial_result"],
                    "graph": None,
                },
                {
                    "candidate_id": "long-line",
                    "title": "长线方案",
                    "rationale": "较长的直接连接。",
                    "status": "valid",
                    "rank": 1,
                    "trial_result": second["trial_result"],
                    "graph": None,
                },
            ],
        },
    }

    committed = commit_construction_interpretation(
        "比较两个线段方案", interpretation, store=_store(tmp_path)
    )

    assert committed["persisted_candidate_count"] == 2
    assert committed["recommended_variant"]["name"] == "长线方案"
    assert len(committed["variants"]) == 2


def test_chat_formalizes_non_template_rule_construction(tmp_path: Path) -> None:
    store = _store(tmp_path)
    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "local"
    route = {
        "name": "drawing_design",
        "operation": "create",
        "decision_source": "test",
        "clarification_required": False,
    }

    with patch("app.agent_service.get_creative_project_store", return_value=store):
        result = service._chat_impl(
            "画一条线段从(0,0)到(5,3)，坐标单位米",
            [],
            mode="advanced",
            route=route,
        )

    assert result["ok"] is True
    assert result["project_id"]
    assert result["project"]["status"] == "designing"
    assert result["variant"]["construction_record"]["assertions"]["ok"] is True
    assert result["preview_paths"]
    assert result["next_action"] == "select_design_variant"


def test_standard_template_and_free_geometry_share_constructor() -> None:
    route = {"name": "drawing_design", "operation": "create"}

    assert RobotAgentService._is_generic_cad_construction_request(
        "画一个标准篮球场", route
    ) is True
    assert RobotAgentService._is_generic_cad_construction_request(
        "画一条从(0,0)到(5,3)的线段图纸", route
    ) is True


def test_formal_constructor_returns_guided_question_for_incomplete_curve_request() -> None:
    service = object.__new__(RobotAgentService)
    service.mode = "local"
    service.api_keys = {}
    route = {"name": "drawing_design", "operation": "create"}

    result = service._formal_cad_construction(
        "绘画一个大小不超过5m的爱心", route, mode="advanced"
    )

    assert result is not None
    assert result["ok"] is False
    assert result["clarification"]["question_key"] == "curve_constraints"
    assert "示例：" in result["message"]
