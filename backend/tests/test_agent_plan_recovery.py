from datetime import datetime, timezone

import pytest

from app.agent_plan_models import (
    ExecutionPlan,
    GoalSpec,
    PlanStep,
    StepResult,
    SuccessCriterion,
)
from app.agent_plan_orchestrator import start_plan_step
from app.agent_plan_recovery import (
    apply_replanned_steps,
    decide_plan_recovery,
    request_plan_replan,
    start_deterministic_repair,
)


def _running_plan() -> ExecutionPlan:
    plan = ExecutionPlan(
        id="plan-recovery-1",
        status="ready",
        goal=GoalSpec(
            id="goal-recovery-1",
            user_request="移动第二条线",
            summary="移动并验证目标",
            domain="cad",
            project_id="project-1",
            success_criteria=[
                SuccessCriterion(
                    id="valid",
                    description="结果有效",
                    metric="topology",
                    operator="valid",
                )
            ],
        ),
        steps=[
            PlanStep(
                id="edit",
                title="修改图纸",
                tool_name="modify_drawing",
                verification_criteria_ids=["valid"],
            )
        ],
    )
    return start_plan_step(plan, "edit", sequence=1).plan


def _failed_result(*codes: str) -> StepResult:
    return StepResult(
        step_id="edit",
        attempt=1,
        status="failed",
        started_at=datetime.now(timezone.utc),
        output={"machine_assertions": {"failure_codes": list(codes)}},
        verification={"valid": False},
        failure_code=codes[0] if codes else "execution_failed",
        failure_message="修改验证失败",
    )


def test_deterministic_repair_is_preferred_when_proven_available() -> None:
    decision = decide_plan_recovery(
        _running_plan(),
        _failed_result("target_scope", "non_target_integrity", "edit_plan"),
        deterministic_repair_available=True,
    )

    assert decision.action == "deterministic_repair"
    assert decision.user_action_required is False
    assert decision.repair_remaining == 1


def test_replan_is_selected_for_plan_mismatch() -> None:
    decision = decide_plan_recovery(
        _running_plan(), _failed_result("preview_exact")
    )

    assert decision.action == "replan"
    assert decision.replan_remaining == 1


def test_ambiguous_target_requires_user_instead_of_guessing() -> None:
    decision = decide_plan_recovery(
        _running_plan(), _failed_result("target_resolved")
    )

    assert decision.action == "ask_user"
    assert decision.user_action_required is True


def test_repair_transition_increments_once_and_preserves_running_step() -> None:
    plan = _running_plan()
    result = _failed_result("target_scope", "edit_plan")
    transition = start_deterministic_repair(
        plan, result, sequence=2, evidence={"strategy": "restore"}
    )

    assert transition.plan.status == "repairing"
    assert transition.plan.deterministic_repair_count == 1
    assert transition.plan.steps[0].status == "running"
    assert transition.event.event_type == "plan_repair_started"
    with pytest.raises(ValueError, match="repair limit reached"):
        start_deterministic_repair(
            transition.plan, result, sequence=3
        )


def test_replan_transition_cannot_be_requested_twice() -> None:
    plan = _running_plan()
    result = _failed_result("preview_exact")
    transition = request_plan_replan(plan, result, sequence=2)

    assert transition.plan.status == "replanning"
    assert transition.plan.replan_count == 1
    assert transition.event.event_type == "plan_replan_requested"
    with pytest.raises(ValueError, match="replan limit reached"):
        request_plan_replan(transition.plan, result, sequence=3)


def test_authorized_replan_replaces_failed_step_tail_and_returns_ready() -> None:
    plan = _running_plan()
    requested = request_plan_replan(
        plan, _failed_result("preview_exact"), sequence=2
    )
    replacement = PlanStep(
        id="edit-replanned",
        title="按最新源图重新修改",
        tool_name="modify_drawing",
        verification_criteria_ids=["valid"],
    )

    applied = apply_replanned_steps(
        requested.plan, "edit", [replacement], sequence=3
    )

    assert applied.plan.status == "ready"
    assert applied.plan.replan_count == 1
    assert [step.id for step in applied.plan.steps] == ["edit-replanned"]
    assert applied.plan.steps[0].attempt_count == 0
    assert applied.event.event_type == "plan_replanned"
