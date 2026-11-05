"""Decide when an execution plan must interrupt the user."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .agent_plan_models import PlanStep


_ALWAYS_CONFIRM_TOOLS = {
    "apply_cad_candidate_edit",
    "drive_robot",
    "drive_sequence",
    "set_mission",
    "execute_prepared_mission",
    "control_ln150",
    "control_printer",
    "printer_spray",
}


class InterruptionDecision(BaseModel):
    """Machine-readable decision for continue, confirm, clarify, or block."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "agent.interruption-decision.v1"
    action: Literal["continue", "confirm", "clarify", "block"]
    reason_code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=1000)
    requires_confirmation: bool = False
    user_action_required: bool = False
    evidence: dict[str, Any] = Field(default_factory=dict)


def decide_step_interruption(
    step: PlanStep,
    *,
    target_resolution: dict[str, Any] | None = None,
    preflight: dict[str, Any] | None = None,
) -> InterruptionDecision:
    """Interrupt only for true ambiguity, invalid gates, or high-risk actions."""
    target = target_resolution or {}
    gate = preflight or {}
    evidence = {
        "tool_name": step.tool_name,
        "step_risk_level": step.risk_level,
        "target_status": target.get("status"),
        "target_reason": target.get("reason"),
        "target_scoring": target.get("scoring"),
        "preflight_ready": gate.get("ready"),
        "preflight_risk_level": gate.get("risk_level"),
    }

    if target.get("status") == "needs_clarification":
        return InterruptionDecision(
            action="clarify",
            reason_code=str(target.get("reason") or "target_ambiguous"),
            message=str(
                target.get("question")
                or "修改目标存在歧义，请点选或补充说明目标。"
            ),
            user_action_required=True,
            evidence=evidence,
        )
    if gate and gate.get("ready") is not True:
        failed = [
            str(item.get("code"))
            for item in gate.get("checks") or []
            if isinstance(item, dict) and item.get("ok") is not True
        ]
        return InterruptionDecision(
            action="block",
            reason_code="preflight_failed",
            message="执行前校验未通过，已阻止该步骤。",
            user_action_required=bool(failed),
            evidence={**evidence, "failed_checks": failed},
        )
    if (
        step.tool_name in _ALWAYS_CONFIRM_TOOLS
        or step.risk_level in {"high", "critical"}
        or gate.get("requires_confirmation") is True
        or gate.get("risk_level") == "high"
    ):
        return InterruptionDecision(
            action="confirm",
            reason_code="high_risk_confirmation",
            message="该步骤会产生高风险或真实设备影响，需要用户确认。",
            requires_confirmation=True,
            user_action_required=True,
            evidence=evidence,
        )
    return InterruptionDecision(
        action="continue",
        reason_code="safe_to_continue",
        message="目标明确且风险可控，可以自动继续。",
        evidence=evidence,
    )


def apply_interruption_decision(
    step: PlanStep, decision: InterruptionDecision
) -> PlanStep:
    """Apply only the confirmation bit; clarification and blocks cannot run."""
    if decision.action in {"clarify", "block"}:
        raise ValueError(f"step cannot start: {decision.reason_code}")
    return step.model_copy(
        update={"requires_confirmation": decision.requires_confirmation}
    )
