from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier
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


def test_formal_entry_accepts_a2_after_clarification_shell_project(tmp_path: Path) -> None:
    source = "新建图纸，画一个宽5米高3米的矩形"
    store = _store(tmp_path)
    shell = store.create(
        "待确认图纸", source, {"shape": "generic_2d_cad"}, {}, []
    )
    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "local"
    route = {
        "name": "drawing_design",
        "operation": "create",
        "stage": "candidate_generation",
        "selected_project_id": shell["id"],
        "decision_source": "design_confirmation_followup",
    }
    with patch("app.agent_service.get_creative_project_store", return_value=store):
        result = service._chat_impl(source, [], mode="advanced", route=route)

    assert result["ok"] is True, result.get("message")
    assert result["project_id"] == shell["id"]
    assert result["variant"]["acceptance_summary"]["status"] == "passed"
    coverage = result["variant"]["construction_record"]["source_acceptance"]["coverage_evidence"]
    operation = next(item for item in coverage["clauses"] if item["requirement"] == "新建图纸")
    assert operation["binding"]["drawing_write_proof"] == "first_candidate_write_in_commit"
    assert coverage["unresolved_fact_ids"] == []
    saved = store.get(shell["id"])
    assert sorted(item["id"] for item in saved["variants"]) == [
        result["variant"]["id"]
    ]


def test_formal_entry_completes_a2_after_clarification_and_confirmation(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "local"
    route = {
        "name": "drawing_design",
        "operation": "create",
        "decision_source": "test",
    }
    with patch("app.agent_service.get_creative_project_store", return_value=store):
        first = service._chat_impl(
            "新建图纸，画一个矩形", [], mode="advanced", route=route
        )
        project_id = first["project_id"]
        assert first["clarification"]
        assert store.get(project_id)["variants"] == []
        follow_route = {
            **route,
            "stage": "candidate_generation",
            "selected_project_id": project_id,
            "decision_source": "design_confirmation_followup",
        }
        second = service._chat_impl(
            "宽5米高3米，坐标单位米，确认生成",
            [],
            mode="advanced",
            route=follow_route,
        )
        assert second["ok"] is True
        assert second.get("variant") is None

        saved = interpret_construction_request("新建图纸，画一个宽5米高3米的矩形")
        with patch.object(
            service, "_interpret_cad_construction_plan", return_value=deepcopy(saved)
        ):
            third = service._chat_impl(
                "确认生成", [], mode="advanced", route=follow_route
            )

    assert third["ok"] is True, third.get("message")
    assert third["project_id"] == project_id
    assert third["variant"]["acceptance_summary"]["status"] == "passed"
    coverage = third["variant"]["construction_record"]["source_acceptance"]["coverage_evidence"]
    assert coverage["state"] == "complete"
    assert coverage["unresolved_fact_ids"] == []
    operation = next(item for item in coverage["clauses"] if item["requirement"] == "新建图纸")
    assert operation["binding"]["drawing_write_proof"] == "first_candidate_write_in_commit"
    saved_project = store.get(project_id)
    assert [item["id"] for item in saved_project["variants"]] == [third["variant"]["id"]]


def test_formal_entry_rejects_new_drawing_on_project_that_already_has_candidate(
    tmp_path: Path,
) -> None:
    source = "新建图纸，画一个宽5米高3米的矩形"
    store = _store(tmp_path)
    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "local"
    route = {
        "name": "drawing_design",
        "operation": "create",
        "decision_source": "test",
    }
    with patch("app.agent_service.get_creative_project_store", return_value=store):
        first = service._chat_impl(source, [], mode="advanced", route=route)
        assert first["ok"] is True
        project_id = first["project_id"]
        second_route = {
            **route,
            "stage": "candidate_generation",
            "selected_project_id": project_id,
            "decision_source": "design_confirmation_followup",
        }
        second = service._chat_impl(source, [], mode="advanced", route=second_route)

    assert second.get("ok") is not True
    assert len(store.get(project_id)["variants"]) == 1
    assert store.get(project_id)["variants"][0]["id"] == first["variant"]["id"]


def test_multi_candidate_acceptance_is_isolated_per_final_geometry(tmp_path: Path) -> None:
    source = "新建图纸，画一个宽5米高3米的矩形"
    correct = interpret_construction_request(source)
    wrong = interpret_construction_request("画一个宽6米高3米的矩形")
    interpretation = {
        **correct,
        "schema": "cad.sketchgraph-interpretation-result.v1",
        "evaluation": {
            "recommended_candidate_id": "correct",
            "candidates": [
                {
                    "candidate_id": "wrong",
                    "title": "错误尺寸",
                    "rationale": "宽度错误。",
                    "status": "valid",
                    "rank": 2,
                    "trial_result": wrong["trial_result"],
                    "graph": None,
                },
                {
                    "candidate_id": "correct",
                    "title": "正确尺寸",
                    "rationale": "符合原文尺寸。",
                    "status": "valid",
                    "rank": 1,
                    "trial_result": correct["trial_result"],
                    "graph": None,
                },
            ],
        },
    }
    committed = commit_construction_interpretation(source, interpretation, store=_store(tmp_path))

    assert committed["persisted_candidate_count"] == 2
    variants = {item["name"]: item for item in committed["variants"]}
    assert variants["正确尺寸"]["acceptance_summary"]["status"] == "passed"
    assert variants["错误尺寸"]["acceptance_summary"]["status"] == "review_required"
    wrong_coverage = variants["错误尺寸"]["construction_record"]["source_acceptance"]["coverage_evidence"]
    assert wrong_coverage["state"] == "partial"
    assert wrong_coverage["unresolved_fact_ids"]
    correct_coverage = variants["正确尺寸"]["construction_record"]["source_acceptance"]["coverage_evidence"]
    assert correct_coverage["state"] == "complete"
    assert correct_coverage["unresolved_fact_ids"] == []


def test_refresh_failure_rolls_back_new_project_and_existing_project_state(
    tmp_path: Path,
) -> None:
    source = "画一条线段从(0,0)到(5,3)，坐标单位米"
    store = _store(tmp_path)
    interpretation = interpret_construction_request(source)
    with patch(
        "app.cad_construction_commit.execute_construction_plan",
        side_effect=RuntimeError("refresh failed"),
    ):
        with pytest.raises(ConstructionCommitError):
            commit_construction_interpretation(source, interpretation, store=store)
    assert store.list() == []

    existing = store.create("当前图纸", source, {"shape": "generic_2d_cad"}, {}, [])
    with patch(
        "app.cad_construction_commit.execute_construction_plan",
        side_effect=RuntimeError("refresh failed"),
    ):
        with pytest.raises(ConstructionCommitError):
            commit_construction_interpretation(
                source, interpretation, store=store, project_id=existing["id"],
            )
    assert store.get(existing["id"]) == existing


def test_standard_template_and_free_geometry_share_constructor() -> None:
    route = {"name": "drawing_design", "operation": "create"}

    assert RobotAgentService._is_generic_cad_construction_request(
        "画一个标准篮球场", route
    ) is True
    assert RobotAgentService._is_generic_cad_construction_request(
        "画一条从(0,0)到(5,3)的线段图纸", route
    ) is True


def test_construction_commit_persists_execution_context_metadata() -> None:
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as directory:
        store = CreativeProjectStore(Path(directory) / "projects.json")
        context = {"request_id": "r1", "contract_version": "c1", "sha256": "h1"}
        interpretation = interpret_construction_request("画一个矩形，宽2米高1米，坐标单位米")
        result = commit_construction_interpretation(
            "创建矩形", interpretation, store=store,
            candidate_metadata={"execution_context": context},
        )
        variant = result["recommended_variant"]
        assert variant["execution_context"] == context
        assert variant["execution_context_hash"] == "h1"
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


def test_concurrent_first_write_on_empty_project_only_one_commit_claims_it(
    tmp_path: Path,
) -> None:
    source = "新建图纸，画一个宽5米高3米的矩形"
    store = _store(tmp_path)
    shell = store.create("待确认图纸", source, {"shape": "generic_2d_cad"}, {}, [])
    interpretation = interpret_construction_request(source)
    barrier = Barrier(2)

    def attempt() -> str:
        barrier.wait(timeout=5)
        try:
            commit_construction_interpretation(
                source,
                deepcopy(interpretation),
                store=store,
                project_id=shell["id"],
            )
            return "ok"
        except ConstructionCommitError as exc:
            return f"error:{exc}"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: attempt(), range(2)))

    assert outcomes.count("ok") == 1, outcomes
    assert any("本次请求没有创建新的可用图纸候选" in item for item in outcomes if item != "ok")
    variants = store.get(shell["id"])["variants"]
    assert len(variants) == 1
    operation = next(
        item for item in variants[0]["construction_record"]["source_acceptance"]
        ["coverage_evidence"]["clauses"] if item["requirement"] == "新建图纸"
    )
    assert operation["binding"]["drawing_write_proof"] == "first_candidate_write_in_commit"


def test_commit_rejects_write_that_returns_no_receipt(tmp_path: Path) -> None:
    source = "新建图纸，画一个宽5米高3米的矩形"
    store = _store(tmp_path)
    shell = store.create("待确认图纸", source, {"shape": "generic_2d_cad"}, {}, [])

    def unproven_write(*args, **kwargs):
        # The legacy call signature still persists geometry, but it cannot
        # prove whether this request created the candidate or reused one.
        return store.add_variant(*args, **kwargs)

    with pytest.raises(ConstructionCommitError, match="缺少可验证的存储回执"):
        commit_construction_interpretation(
            source,
            interpret_construction_request(source),
            store=store,
            project_id=shell["id"],
            add_variant=unproven_write,
            get_project=store.get,
        )
    assert len(store.get(shell["id"])["variants"]) == 1


def test_commit_rejects_receipt_that_reports_reused_candidate(tmp_path: Path) -> None:
    source = "新建图纸，画一个宽5米高3米的矩形"
    store = _store(tmp_path)
    shell = store.create("待确认图纸", source, {"shape": "generic_2d_cad"}, {}, [])
    writer = store.add_variant_with_receipt

    def reused_receipt(*args, **kwargs):
        receipt = writer(*args, **kwargs)
        receipt["created"] = False
        receipt["reused_existing"] = True
        receipt["before_variant_count"] = receipt["after_variant_count"]
        return receipt

    with patch.object(store, "add_variant_with_receipt", side_effect=reused_receipt):
        with pytest.raises(ConstructionCommitError, match="不能复用已有候选"):
            commit_construction_interpretation(
                source,
                interpret_construction_request(source),
                store=store,
                project_id=shell["id"],
            )
