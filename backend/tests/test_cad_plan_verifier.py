from copy import deepcopy
from datetime import datetime, timezone

from app.agent_plan_models import (
    ExecutionPlan,
    GoalSpec,
    PlanStep,
    SuccessCriterion,
)
from app.agent_plan_orchestrator import finish_plan_step, start_plan_step
from app.cad_edit_contract import build_cad_edit_contract
from app.cad_edit_plan import build_cad_edit_plan
from app.cad_edit_preview import build_cad_edit_preview
from app.cad_plan_verifier import verify_cad_plan_step
from app.incremental_cad import edit_candidate_geometries


def _source() -> list[dict]:
    return [
        {
            "id": 1,
            "type": "line",
            "template_instance": 1,
            "start": {"x": 0, "y": 0},
            "end": {"x": 1000, "y": 0},
        },
        {
            "id": 2,
            "type": "line",
            "template_instance": 2,
            "start": {"x": 3000, "y": 0},
            "end": {"x": 4000, "y": 0},
        },
    ]


def _running_plan() -> ExecutionPlan:
    goal = GoalSpec(
        id="goal-cad-1",
        user_request="把第二条线向右移动一米",
        summary="移动并验证第二条线",
        domain="cad",
        project_id="project-1",
        success_criteria=[
            SuccessCriterion(
                id="target_changed",
                description="目标图元按要求变化",
                metric="position",
                operator="valid",
            ),
            SuccessCriterion(
                id="others_unchanged",
                description="非目标图元保持不变",
                metric="non_target_unchanged",
                operator="valid",
            ),
        ],
    )
    plan = ExecutionPlan(
        id="plan-cad-1",
        status="ready",
        goal=goal,
        steps=[
            PlanStep(
                id="edit-line-2",
                title="移动第二条线",
                tool_name="modify_drawing",
                verification_criteria_ids=[
                    "target_changed",
                    "others_unchanged",
                ],
            )
        ],
    )
    return start_plan_step(plan, "edit-line-2", sequence=1).plan


def _edit_artifacts(source: list[dict], target: list[dict]) -> tuple[dict, dict, dict]:
    edit = {
        "operation": "translate",
        "instance": 2,
        "dx_mm": 1000.0,
        "dy_mm": 0.0,
        "project_id": "project-1",
        "parent_variant_id": "variant-1",
    }
    contract = build_cad_edit_contract(edit, source_text="第二条线向右移动一米")
    return (
        contract,
        build_cad_edit_plan(source, target, contract),
        build_cad_edit_preview(source, target, contract),
    )


def test_verified_candidate_becomes_verified_step_result() -> None:
    source = _source()
    target, error = edit_candidate_geometries(
        source,
        {"operation": "translate", "instance": 2, "dx_mm": 1000, "dy_mm": 0},
    )
    assert error is None
    contract, edit_plan, preview = _edit_artifacts(source, target or [])

    verification = verify_cad_plan_step(
        step=_running_plan().steps[0],
        source=source,
        candidate=target or [],
        contract=contract,
        edit_plan=edit_plan,
        edit_preview=preview,
        started_at=datetime.now(timezone.utc),
    )

    assert verification.step_result.status == "verified"
    assert verification.step_result.verification["target_changed"] is True
    assert verification.geometry_diff["counts"]["modified"] == 1
    assert verification.rollback_evidence is None


def test_non_target_drift_fails_closed_with_rollback_evidence() -> None:
    source = _source()
    target, error = edit_candidate_geometries(
        source,
        {"operation": "translate", "instance": 2, "dx_mm": 1000, "dy_mm": 0},
    )
    assert error is None
    drifted = deepcopy(target or [])
    drifted[0]["end"]["x"] += 50
    contract, edit_plan, preview = _edit_artifacts(source, drifted)

    verification = verify_cad_plan_step(
        step=_running_plan().steps[0],
        source=source,
        candidate=drifted,
        contract=contract,
        edit_plan=edit_plan,
        edit_preview=preview,
        started_at=datetime.now(timezone.utc),
    )

    assert verification.step_result.status == "failed"
    assert verification.step_result.verification["others_unchanged"] is False
    assert "target_scope" in verification.machine_assertions["failure_codes"]
    assert verification.rollback_evidence is not None
    assert verification.rollback_evidence["candidate_discarded"] is True
    assert verification.rollback_evidence["persisted"] is False
    assert (
        verification.rollback_evidence["source_before_sha256"]
        == verification.rollback_evidence["source_after_sha256"]
    )


def test_plan_state_machine_accepts_cad_verification_result() -> None:
    source = _source()
    target, error = edit_candidate_geometries(
        source,
        {"operation": "translate", "instance": 2, "dx_mm": 1000, "dy_mm": 0},
    )
    assert error is None
    contract, edit_plan, preview = _edit_artifacts(source, target or [])
    plan = _running_plan()
    verification = verify_cad_plan_step(
        step=plan.steps[0],
        source=source,
        candidate=target or [],
        contract=contract,
        edit_plan=edit_plan,
        edit_preview=preview,
        started_at=datetime.now(timezone.utc),
    )

    transition = finish_plan_step(plan, verification.step_result, sequence=2)

    assert transition.plan.status == "completed"
    assert transition.plan.steps[0].status == "verified"
    assert transition.event.event_type == "step_verified"
