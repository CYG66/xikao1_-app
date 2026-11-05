"""Pure recovery decisions and transitions for failed plan step results."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .agent_failure_policy import classify_agent_failure
from .agent_plan_models import (
    ExecutionPlan,
    PlanEvent,
    PlanStep,
    PlanTransition,
    StepResult,
)


class PlanRecoveryDecision(BaseModel):
    """Bounded action selected after a failed step verification."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "agent.plan-recovery-decision.v1"
    action: Literal["deterministic_repair", "replan", "ask_user", "fail"]
    category: str
    reason: str
    user_action_required: bool
    repair_remaining: int
    replan_remaining: int
    failure_codes: list[str]


def _failure_codes(result: StepResult) -> list[str]:
    assertions = result.output.get("machine_assertions")
    values = assertions.get("failure_codes") if isinstance(assertions, dict) else []
    codes = {str(value) for value in values or [] if value}
    if result.failure_code:
        codes.add(result.failure_code)
    return sorted(codes)


def decide_plan_recovery(
    plan: ExecutionPlan,
    result: StepResult,
    *,
    deterministic_repair_available: bool = False,
) -> PlanRecoveryDecision:
    """Choose a bounded recovery action without executing it."""
    if result.status != "failed":
        raise ValueError("recovery decision requires a failed step result")
    codes = _failure_codes(result)
    policy = classify_agent_failure(codes, message=result.failure_message or "")
    repair_remaining = max(
        0, plan.deterministic_repair_limit - plan.deterministic_repair_count
    )
    replan_remaining = max(0, plan.replan_limit - plan.replan_count)

    if deterministic_repair_available and repair_remaining:
        action = "deterministic_repair"
        reason = "存在经过机器断言证明的确定性修复，且修复次数未超限。"
        user_action_required = False
    elif policy["next_action"] in {"replan", "refresh_and_replan"} and replan_remaining:
        action = "replan"
        reason = "当前结果与计划或版本不一致，请求基于权威源重新规划一次。"
        user_action_required = False
    elif policy["user_action_required"]:
        action = "ask_user"
        reason = str(policy["guidance"])
        user_action_required = True
    else:
        action = "fail"
        reason = (
            "自动恢复次数已用尽。"
            if not repair_remaining and not replan_remaining
            else str(policy["guidance"])
        )
        user_action_required = False

    return PlanRecoveryDecision(
        action=action,
        category=str(policy["category"]),
        reason=reason,
        user_action_required=user_action_required,
        repair_remaining=repair_remaining,
        replan_remaining=replan_remaining,
        failure_codes=codes,
    )


def _recovery_transition(
    plan: ExecutionPlan,
    result: StepResult,
    *,
    sequence: int,
    action: Literal["deterministic_repair", "replan"],
    evidence: dict[str, Any] | None = None,
) -> PlanTransition:
    if result.status != "failed":
        raise ValueError("recovery transition requires a failed step result")
    step = next((item for item in plan.steps if item.id == result.step_id), None)
    if step is None:
        raise ValueError(f"unknown plan step: {result.step_id}")
    if step.status != "running":
        raise ValueError("recovery must be selected before failure is finalized")
    if result.attempt != step.attempt_count:
        raise ValueError("step result attempt does not match running attempt")

    payload = plan.model_dump()
    if action == "deterministic_repair":
        if plan.deterministic_repair_count >= plan.deterministic_repair_limit:
            raise ValueError("deterministic repair limit reached")
        payload["deterministic_repair_count"] += 1
        payload["status"] = "repairing"
        event_type = "plan_repair_started"
        message = f"步骤“{step.title}”开始一次确定性修复"
    else:
        if plan.replan_count >= plan.replan_limit:
            raise ValueError("replan limit reached")
        payload["replan_count"] += 1
        payload["status"] = "replanning"
        event_type = "plan_replan_requested"
        message = f"步骤“{step.title}”请求一次重新规划"
    payload["revision"] += 1
    payload["updated_at"] = datetime.now(timezone.utc)
    updated = ExecutionPlan.model_validate(payload)
    event = PlanEvent(
        id=str(uuid.uuid4()),
        plan_id=updated.id,
        sequence=sequence,
        plan_revision=updated.revision,
        event_type=event_type,
        step_id=step.id,
        from_status=plan.status,
        to_status=updated.status,
        message=message,
        data={
            "failure_codes": _failure_codes(result),
            "evidence": evidence or {},
        },
    )
    return PlanTransition(plan=updated, event=event)


def start_deterministic_repair(
    plan: ExecutionPlan,
    result: StepResult,
    *,
    sequence: int,
    evidence: dict[str, Any] | None = None,
) -> PlanTransition:
    return _recovery_transition(
        plan,
        result,
        sequence=sequence,
        action="deterministic_repair",
        evidence=evidence,
    )


def resume_plan_step_after_repair(
    plan: ExecutionPlan,
    step_id: str,
    *,
    sequence: int,
) -> PlanTransition:
    """Resume the same running attempt after its one deterministic repair."""
    if plan.status != "repairing" or plan.deterministic_repair_count != 1:
        raise ValueError("plan is not awaiting deterministic repair verification")
    step = next((item for item in plan.steps if item.id == step_id), None)
    if step is None:
        raise ValueError(f"unknown plan step: {step_id}")
    if step.status != "running":
        raise ValueError("repaired step must remain running")
    payload = plan.model_dump()
    payload["status"] = "running"
    payload["revision"] += 1
    payload["updated_at"] = datetime.now(timezone.utc)
    updated = ExecutionPlan.model_validate(payload)
    event = PlanEvent(
        id=str(uuid.uuid4()),
        plan_id=updated.id,
        sequence=sequence,
        plan_revision=updated.revision,
        event_type="step_started",
        step_id=step.id,
        from_status="repairing",
        to_status="running",
        message=f"步骤“{step.title}”完成确定性修复，开始复核",
        data={"attempt": step.attempt_count, "resumed_after_repair": True},
    )
    return PlanTransition(plan=updated, event=event)


def request_plan_replan(
    plan: ExecutionPlan,
    result: StepResult,
    *,
    sequence: int,
) -> PlanTransition:
    return _recovery_transition(
        plan,
        result,
        sequence=sequence,
        action="replan",
    )


def apply_replanned_steps(
    plan: ExecutionPlan,
    failed_step_id: str,
    replacement_steps: list[PlanStep],
    *,
    sequence: int,
) -> PlanTransition:
    """Replace the failed step and its tail after one authorized replan."""
    if plan.status != "replanning" or plan.replan_count != 1:
        raise ValueError("plan is not awaiting its authorized replan result")
    if not replacement_steps:
        raise ValueError("replan requires at least one replacement step")
    index = next(
        (offset for offset, step in enumerate(plan.steps) if step.id == failed_step_id),
        None,
    )
    if index is None:
        raise ValueError(f"unknown plan step: {failed_step_id}")
    if any(step.status != "verified" for step in plan.steps[:index]):
        raise ValueError("replan cannot replace steps before unverified dependencies")
    normalized = [
        step.model_copy(update={"status": "pending", "attempt_count": 0})
        for step in replacement_steps
    ]
    payload = plan.model_dump()
    payload["steps"] = [
        *[step.model_dump() for step in plan.steps[:index]],
        *[step.model_dump() for step in normalized],
    ]
    payload["status"] = "ready"
    payload["revision"] += 1
    payload["updated_at"] = datetime.now(timezone.utc)
    updated = ExecutionPlan.model_validate(payload)
    event = PlanEvent(
        id=str(uuid.uuid4()),
        plan_id=updated.id,
        sequence=sequence,
        plan_revision=updated.revision,
        event_type="plan_replanned",
        step_id=failed_step_id,
        from_status="replanning",
        to_status="ready",
        message="重新规划完成，等待执行替换后的步骤",
        data={"replacement_step_ids": [step.id for step in normalized]},
    )
    return PlanTransition(plan=updated, event=event)
