from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.agent_plan_models import (
    AgentTargetRef,
    ExecutionPlan,
    GoalSpec,
    PlanStep,
    StepResult,
    SuccessCriterion,
)


def _goal() -> GoalSpec:
    target = AgentTargetRef(
        scope="logical_object", ids=["center-circle"], label="中心圆"
    )
    return GoalSpec(
        id="goal-1",
        user_request="把中心圆半径扩大一倍，其他图元保持不变",
        summary="扩大中心圆",
        domain="cad",
        project_id="project-1",
        source_variant_id="variant-1",
        source_version=3,
        source_sha256="a" * 64,
        targets=[target],
        success_criteria=[
            SuccessCriterion(
                id="radius-doubled",
                description="中心圆半径变为原来的两倍",
                metric="dimension",
                operator="eq",
                expected={"factor": 2.0},
                target=target,
                tolerance=0.001,
            )
        ],
        invariants=[
            SuccessCriterion(
                id="others-unchanged",
                description="非目标图元保持不变",
                metric="non_target_unchanged",
                operator="unchanged",
                target=AgentTargetRef(scope="variant", ids=["variant-1"]),
            )
        ],
    )


def test_goal_spec_captures_target_success_and_invariant() -> None:
    goal = _goal()

    assert goal.targets[0].label == "中心圆"
    assert goal.success_criteria[0].expected == {"factor": 2.0}
    assert goal.invariants[0].operator == "unchanged"


def test_cad_goal_requires_project_binding() -> None:
    with pytest.raises(ValidationError, match="CAD goal requires project_id"):
        GoalSpec(
            id="goal-1",
            user_request="画一个圆",
            summary="画圆",
            domain="cad",
            success_criteria=[
                SuccessCriterion(
                    id="circle-created",
                    description="圆已创建",
                    metric="geometry_count",
                    operator="eq",
                    expected=1,
                )
            ],
        )


def test_goal_rejects_duplicate_criterion_ids() -> None:
    goal = _goal().model_dump()
    goal["invariants"][0]["id"] = "radius-doubled"

    with pytest.raises(ValidationError, match="criterion IDs must be unique"):
        GoalSpec.model_validate(goal)


def test_plan_rejects_forward_dependency() -> None:
    with pytest.raises(ValidationError, match="earlier steps"):
        ExecutionPlan(
            id="plan-1",
            goal=_goal(),
            steps=[
                PlanStep(
                    id="verify",
                    title="验证",
                    tool_name="validate",
                    depends_on=["edit"],
                ),
                PlanStep(id="edit", title="修改", tool_name="modify_drawing"),
            ],
        )


def test_plan_rejects_unknown_verification_criterion() -> None:
    with pytest.raises(ValidationError, match="unknown verification criterion"):
        ExecutionPlan(
            id="plan-1",
            goal=_goal(),
            steps=[
                PlanStep(
                    id="edit",
                    title="修改",
                    tool_name="modify_drawing",
                    verification_criteria_ids=["missing-check"],
                )
            ],
        )


def test_completed_plan_requires_terminal_steps() -> None:
    with pytest.raises(ValidationError, match="all steps verified or skipped"):
        ExecutionPlan(
            id="plan-1",
            goal=_goal(),
            status="completed",
            steps=[PlanStep(id="edit", title="修改", tool_name="modify_drawing")],
        )


def test_valid_ordered_plan_supports_one_repair_and_one_replan() -> None:
    plan = ExecutionPlan(
        id="plan-1",
        goal=_goal(),
        status="ready",
        steps=[
            PlanStep(
                id="edit",
                title="修改中心圆",
                tool_name="modify_drawing",
                verification_criteria_ids=["radius-doubled", "others-unchanged"],
            ),
            PlanStep(
                id="verify",
                title="复核修改",
                tool_name="validate_drawing",
                depends_on=["edit"],
                verification_criteria_ids=["radius-doubled", "others-unchanged"],
            ),
        ],
    )

    assert plan.deterministic_repair_limit == 1
    assert plan.replan_limit == 1


def test_failed_step_result_requires_failure_details() -> None:
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError, match="requires failure_code"):
        StepResult(
            step_id="edit",
            attempt=1,
            status="failed",
            started_at=now,
        )


def test_verified_step_result_rejects_failed_check() -> None:
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError, match="failed checks"):
        StepResult(
            step_id="verify",
            attempt=1,
            status="verified",
            started_at=now,
            verification={"radius-doubled": True, "others-unchanged": False},
        )


def test_verified_step_result_rejects_failure_details() -> None:
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError, match="only failed result"):
        StepResult(
            step_id="verify",
            attempt=1,
            status="verified",
            started_at=now,
            failure_code="unexpected",
        )


def test_step_result_rejects_negative_duration() -> None:
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError, match="cannot precede"):
        StepResult(
            step_id="verify",
            attempt=1,
            status="verified",
            started_at=now,
            finished_at=now - timedelta(seconds=1),
        )
