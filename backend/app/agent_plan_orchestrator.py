"""Pure single-step state machine for goal-driven agent plans."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .agent_plan_models import (
    ExecutionPlan,
    PlanEvent,
    PlanStep,
    PlanTransition,
    StepResult,
)


_TERMINAL_PLAN_STATES = {"completed", "failed", "rolled_back", "cancelled"}
_SUCCESS_STEP_STATES = {"verified", "skipped"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validated_plan(plan: ExecutionPlan) -> ExecutionPlan:
    return ExecutionPlan.model_validate(plan.model_dump())


def _step_index(plan: ExecutionPlan, step_id: str) -> int:
    for index, step in enumerate(plan.steps):
        if step.id == step_id:
            return index
    raise ValueError(f"unknown plan step: {step_id}")


def _replace_step(
    plan: ExecutionPlan,
    index: int,
    step: PlanStep,
    *,
    status: str,
) -> ExecutionPlan:
    payload = plan.model_dump()
    payload["steps"][index] = step.model_dump()
    payload["status"] = status
    payload["revision"] = plan.revision + 1
    payload["updated_at"] = _utc_now()
    return ExecutionPlan.model_validate(payload)


def _event(
    plan: ExecutionPlan,
    *,
    sequence: int,
    event_type: str,
    step_id: str,
    from_status: str,
    to_status: str,
    message: str,
    data: dict | None = None,
) -> PlanEvent:
    return PlanEvent.model_validate({
        "id": str(uuid.uuid4()),
        "plan_id": plan.id,
        "sequence": sequence,
        "plan_revision": plan.revision,
        "event_type": event_type,
        "step_id": step_id,
        "from_status": from_status,
        "to_status": to_status,
        "message": message,
        "data": data or {},
    })


def start_plan_step(
    plan: ExecutionPlan,
    step_id: str,
    *,
    sequence: int,
    confirmed: bool = False,
) -> PlanTransition:
    """Move one ready step to confirmation or running without executing a tool."""
    plan = _validated_plan(plan)
    if plan.status in _TERMINAL_PLAN_STATES:
        raise ValueError("terminal plan cannot start another step")
    index = _step_index(plan, step_id)
    step = plan.steps[index]
    if step.status not in {"pending", "awaiting_confirmation"}:
        raise ValueError("only pending or awaiting-confirmation step can start")
    by_id = {item.id: item for item in plan.steps}
    if any(by_id[item].status not in _SUCCESS_STEP_STATES for item in step.depends_on):
        raise ValueError("step dependencies are not verified")

    previous_status = step.status
    if step.requires_confirmation and not confirmed:
        if step.status == "awaiting_confirmation":
            raise ValueError("step is already awaiting confirmation")
        updated_step = step.model_copy(update={"status": "awaiting_confirmation"})
        updated_plan = _replace_step(
            plan, index, updated_step, status="awaiting_confirmation"
        )
        event = _event(
            updated_plan,
            sequence=sequence,
            event_type="step_awaiting_confirmation",
            step_id=step_id,
            from_status=previous_status,
            to_status="awaiting_confirmation",
            message=f"步骤“{step.title}”等待用户确认",
        )
        return PlanTransition(plan=updated_plan, event=event)

    if step.attempt_count >= step.max_attempts:
        raise ValueError("step attempt limit reached")
    updated_step = step.model_copy(
        update={"status": "running", "attempt_count": step.attempt_count + 1}
    )
    updated_plan = _replace_step(plan, index, updated_step, status="running")
    event = _event(
        updated_plan,
        sequence=sequence,
        event_type="step_started",
        step_id=step_id,
        from_status=previous_status,
        to_status="running",
        message=f"开始步骤“{step.title}”",
        data={"attempt": updated_step.attempt_count},
    )
    return PlanTransition(plan=updated_plan, event=event)


def await_dynamic_confirmation(plan: ExecutionPlan, step_id: str, *, sequence: int) -> PlanTransition:
    """Pause a running step when domain preflight discovers confirmation risk."""
    plan=_validated_plan(plan)
    index=_step_index(plan,step_id);step=plan.steps[index]
    if plan.status in _TERMINAL_PLAN_STATES or step.status!='running':
        raise ValueError('only a running step may request dynamic confirmation')
    updated=_replace_step(plan,index,step.model_copy(update={
        'status':'awaiting_confirmation','requires_confirmation':True}),status='awaiting_confirmation')
    return PlanTransition(plan=updated,event=_event(updated,sequence=sequence,
        event_type='step_awaiting_confirmation',step_id=step_id,from_status='running',
        to_status='awaiting_confirmation',message=f'步骤“{step.title}”经预检后等待用户确认'))


def finish_plan_step(
    plan: ExecutionPlan,
    result: StepResult,
    *,
    sequence: int,
) -> PlanTransition:
    """Apply one verified execution result and derive the next plan state."""
    plan = _validated_plan(plan)
    if plan.status in _TERMINAL_PLAN_STATES:
        raise ValueError("terminal plan cannot accept a step result")
    index = _step_index(plan, result.step_id)
    step = plan.steps[index]
    if step.status != "running":
        raise ValueError("step result requires a running step")
    if result.attempt != step.attempt_count:
        raise ValueError("step result attempt does not match running attempt")

    event_type = {
        "verified": "step_verified",
        "failed": "step_failed",
        "rolled_back": "step_rolled_back",
        "skipped": "step_skipped",
    }[result.status]
    updated_step = step.model_copy(update={"status": result.status})
    provisional_status = {
        "failed": "failed",
        "rolled_back": "rolled_back",
    }.get(result.status, "ready")
    updated_plan = _replace_step(
        plan, index, updated_step, status=provisional_status
    )
    if result.status in _SUCCESS_STEP_STATES and all(
        item.status in _SUCCESS_STEP_STATES for item in updated_plan.steps
    ):
        payload = updated_plan.model_dump()
        payload["status"] = "completed"
        updated_plan = ExecutionPlan.model_validate(payload)
    event = _event(
        updated_plan,
        sequence=sequence,
        event_type=event_type,
        step_id=step.id,
        from_status="running",
        to_status=result.status,
        message=(
            f"步骤“{step.title}”验证通过"
            if result.status == "verified"
            else result.failure_message
            or f"步骤“{step.title}”状态变更为 {result.status}"
        ),
        data={"result": result.model_dump(mode="json")},
    )
    return PlanTransition(plan=updated_plan, event=event)


def cancel_plan(
    plan: ExecutionPlan,
    step_id: str,
    *,
    sequence: int,
    message: str = "用户取消执行",
) -> PlanTransition:
    """Cancel a non-terminal plan without executing its pending step."""
    plan = _validated_plan(plan)
    if plan.status in _TERMINAL_PLAN_STATES:
        raise ValueError("terminal plan cannot be cancelled again")
    index = _step_index(plan, step_id)
    step = plan.steps[index]
    updated_step = step.model_copy(update={"status": "skipped"})
    updated_plan = _replace_step(plan, index, updated_step, status="cancelled")
    event = _event(
        updated_plan,
        sequence=sequence,
        event_type="plan_cancelled",
        step_id=step_id,
        from_status=plan.status,
        to_status="cancelled",
        message=message,
    )
    return PlanTransition(plan=updated_plan, event=event)
