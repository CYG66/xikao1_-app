import pytest

from app.agent_interruption_policy import (
    apply_interruption_decision,
    decide_step_interruption,
)
from app.agent_plan_models import PlanStep
from app.agent_plan_orchestrator import start_plan_step
from app.agent_plan_models import ExecutionPlan, GoalSpec, SuccessCriterion


def _step(tool_name: str = "modify_drawing", *, risk: str = "low") -> PlanStep:
    return PlanStep(
        id="step-1",
        title="修改图纸",
        tool_name=tool_name,
        risk_level=risk,
        verification_criteria_ids=["valid"],
    )


def _plan(step: PlanStep) -> ExecutionPlan:
    return ExecutionPlan(
        id="plan-interruption",
        status="ready",
        goal=GoalSpec(
            id="goal-interruption",
            user_request="修改明确选中的线段",
            summary="修改并验证",
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
        steps=[step],
    )


def test_low_risk_draft_cad_with_authoritative_target_continues() -> None:
    decision = decide_step_interruption(
        _step(),
        target_resolution={"status": "resolved", "confidence": 1.0},
        preflight={"ready": True, "risk_level": "low"},
    )
    prepared = apply_interruption_decision(_step(), decision)
    started = start_plan_step(_plan(prepared), "step-1", sequence=1)

    assert decision.action == "continue"
    assert prepared.requires_confirmation is False
    assert started.plan.steps[0].status == "running"


def test_medium_warning_does_not_interrupt_when_preflight_is_ready() -> None:
    decision = decide_step_interruption(
        _step(risk="medium"),
        target_resolution={"status": "resolved"},
        preflight={"ready": True, "risk_level": "medium", "warnings": ["幅度较大"]},
    )

    assert decision.action == "continue"


def test_high_risk_cad_requires_confirmation() -> None:
    decision = decide_step_interruption(
        _step(),
        target_resolution={"status": "resolved"},
        preflight={
            "ready": True,
            "risk_level": "high",
            "requires_confirmation": True,
        },
    )
    prepared = apply_interruption_decision(_step(), decision)
    waiting = start_plan_step(_plan(prepared), "step-1", sequence=1)

    assert decision.action == "confirm"
    assert waiting.plan.status == "awaiting_confirmation"


def test_motion_and_hardware_always_require_confirmation() -> None:
    for tool_name in ("drive_robot", "execute_prepared_mission", "control_ln150"):
        decision = decide_step_interruption(_step(tool_name))
        assert decision.action == "confirm", tool_name


def test_true_target_ambiguity_requires_clarification() -> None:
    decision = decide_step_interruption(
        _step(),
        target_resolution={
            "status": "needs_clarification",
            "reason": "target_score_margin_too_small",
            "question": "请选择上方或下方球场。",
            "scoring": {"margin": 0.05, "minimum_margin": 0.15},
        },
    )

    assert decision.action == "clarify"
    assert decision.user_action_required is True
    with pytest.raises(ValueError, match="target_score_margin_too_small"):
        apply_interruption_decision(_step(), decision)


def test_failed_preflight_blocks_instead_of_requesting_confirmation() -> None:
    decision = decide_step_interruption(
        _step(),
        target_resolution={"status": "resolved"},
        preflight={
            "ready": False,
            "checks": [{"code": "non_target_integrity", "ok": False}],
        },
    )

    assert decision.action == "block"
    assert decision.evidence["failed_checks"] == ["non_target_integrity"]
