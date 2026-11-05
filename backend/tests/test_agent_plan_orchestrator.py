from datetime import datetime, timezone

import pytest

from app.agent_plan_models import (
    ExecutionPlan,
    GoalSpec,
    PlanStep,
    StepResult,
    SuccessCriterion,
)
from app.agent_plan_orchestrator import finish_plan_step, start_plan_step


def _plan(*, confirmation: bool = False) -> ExecutionPlan:
    goal = GoalSpec(
        id="goal-1",
        user_request="检查图纸后修改中心圆",
        summary="修改并验证中心圆",
        domain="cad",
        project_id="project-1",
        success_criteria=[
            SuccessCriterion(
                id="valid",
                description="修改结果有效",
                metric="topology",
                operator="valid",
            )
        ],
    )
    return ExecutionPlan(
        id="plan-1",
        status="ready",
        goal=goal,
        steps=[
            PlanStep(
                id="inspect",
                title="检查图纸",
                tool_name="inspect_drawing",
                verification_criteria_ids=["valid"],
            ),
            PlanStep(
                id="edit",
                title="修改中心圆",
                tool_name="modify_drawing",
                depends_on=["inspect"],
                requires_confirmation=confirmation,
                verification_criteria_ids=["valid"],
            ),
        ],
    )


def _result(step_id: str, attempt: int = 1) -> StepResult:
    return StepResult(
        step_id=step_id,
        attempt=attempt,
        status="verified",
        started_at=datetime.now(timezone.utc),
        verification={"valid": True},
    )


def test_single_step_moves_from_pending_to_running_to_verified() -> None:
    plan = _plan()
    started = start_plan_step(plan, "inspect", sequence=2)
    finished = finish_plan_step(started.plan, _result("inspect"), sequence=3)

    assert plan.steps[0].status == "pending"
    assert started.plan.steps[0].status == "running"
    assert started.plan.steps[0].attempt_count == 1
    assert finished.plan.steps[0].status == "verified"
    assert finished.plan.status == "ready"
    assert started.event.event_type == "step_started"
    assert finished.event.event_type == "step_verified"


def test_dependency_blocks_later_step() -> None:
    with pytest.raises(ValueError, match="dependencies are not verified"):
        start_plan_step(_plan(), "edit", sequence=2)


def test_confirmation_is_a_separate_state_transition() -> None:
    first = start_plan_step(_plan(confirmation=True), "inspect", sequence=2)
    verified = finish_plan_step(first.plan, _result("inspect"), sequence=3)
    waiting = start_plan_step(verified.plan, "edit", sequence=4)
    started = start_plan_step(waiting.plan, "edit", sequence=5, confirmed=True)

    assert waiting.plan.status == "awaiting_confirmation"
    assert waiting.plan.steps[1].status == "awaiting_confirmation"
    assert started.plan.steps[1].status == "running"
    assert started.event.from_status == "awaiting_confirmation"


def test_last_verified_step_completes_plan() -> None:
    first = start_plan_step(_plan(), "inspect", sequence=2)
    verified = finish_plan_step(first.plan, _result("inspect"), sequence=3)
    second = start_plan_step(verified.plan, "edit", sequence=4)
    completed = finish_plan_step(second.plan, _result("edit"), sequence=5)

    assert completed.plan.status == "completed"
    assert completed.plan.revision == 5


def test_failed_result_fails_plan_and_preserves_failure_event() -> None:
    started = start_plan_step(_plan(), "inspect", sequence=2)
    failed = finish_plan_step(
        started.plan,
        StepResult(
            step_id="inspect",
            attempt=1,
            status="failed",
            started_at=datetime.now(timezone.utc),
            failure_code="validation_failed",
            failure_message="图纸检查未通过",
            retryable=True,
        ),
        sequence=3,
    )

    assert failed.plan.status == "failed"
    assert failed.event.event_type == "step_failed"
    assert failed.event.data["result"]["retryable"] is True


def test_result_attempt_must_match_running_attempt() -> None:
    started = start_plan_step(_plan(), "inspect", sequence=2)
    with pytest.raises(ValueError, match="attempt does not match"):
        finish_plan_step(started.plan, _result("inspect", attempt=2), sequence=3)
