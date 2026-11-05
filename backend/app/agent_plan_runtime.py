"""Strict execution-plan control around the existing chat domain executor."""

from __future__ import annotations

import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .agent_failure_policy import classify_agent_failure
from .agent_interruption_policy import decide_step_interruption
from .agent_plan_evaluation import evaluate_plan_chain
from .agent_plan_models import (
    AgentTargetRef,
    ExecutionPlan,
    GoalSpec,
    PlanStep,
    StepResult,
    SuccessCriterion,
)
from .agent_plan_orchestrator import cancel_plan, finish_plan_step, start_plan_step, await_dynamic_confirmation
from .agent_plan_recovery import (
    request_plan_replan,
    resume_plan_step_after_repair,
    start_deterministic_repair,
)
from .agent_plan_sqlite_store import SQLiteAgentPlanStore
from .tooling import TOOL_REGISTRY


@dataclass(frozen=True)
class AgentPlanSession:
    plan_id: str
    step_id: str


def _default_store_path() -> Path:
    configured = os.getenv("XLINE_AGENT_PLAN_STORE", "").strip()
    if configured:
        return Path(configured)
    root = (
        Path(tempfile.gettempdir()) / "xline-agent"
        if os.name == "nt"
        else Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))
        / "xline-agent"
    )
    return root / "agent_plans.sqlite3"


def _tool_name(route: dict[str, Any]) -> str:
    operation = str(route.get("operation") or "").strip()
    if str(route.get("tool_family") or "") == "cad" or route.get("name") == "drawing_design":
        if operation == "modify":
            return (
                "modify_drawing"
                if route.get("edit_domain") == "standalone_drawing"
                else "persist_candidate_variant"
            )
        return "persist_candidate_variant"
    name = str(route.get("name") or "").strip()
    return name if name in TOOL_REGISTRY else "agent_chat"


def _risk_level(tool_name: str) -> str:
    spec = TOOL_REGISTRY.get(tool_name)
    risk = spec.risk if spec is not None else "read"
    return {
        "read": "read_only",
        "safe_stop": "low",
        "configuration": "medium",
        "motion": "high",
        "hardware": "critical",
    }[risk]


def _targets(
    route: dict[str, Any], project_id: str | None, variant_id: str | None
) -> list[AgentTargetRef]:
    values: list[AgentTargetRef] = []
    selected_project = str(route.get("selected_project_id") or project_id or "").strip()
    selected_variant = str(route.get("selected_variant_id") or variant_id or "").strip()
    if selected_project:
        values.append(AgentTargetRef(scope="project", ids=[selected_project]))
    if selected_variant:
        values.append(AgentTargetRef(scope="variant", ids=[selected_variant]))
    selection = route.get("drawing_selection")
    if isinstance(selection, dict):
        geometry_ids = [
            str(value) for value in selection.get("geometry_ids") or [] if str(value)
        ]
        if geometry_ids:
            values.append(AgentTargetRef(scope="geometry", ids=geometry_ids))
    return values


class AgentPlanExecutionController:
    """Make the strict plan trace authoritative for each executable chat turn."""

    def __init__(self, store: SQLiteAgentPlanStore | None = None) -> None:
        self.store = store or SQLiteAgentPlanStore(_default_store_path())

    def begin(
        self,
        message: str,
        route: dict[str, Any],
        *,
        project_id: str | None = None,
        variant_id: str | None = None,
    ) -> AgentPlanSession:
        plan_id = str(uuid.uuid4())
        step_id = "execute-request"
        tool_name = _tool_name(route)
        risk = _risk_level(tool_name)
        selected_project = str(
            route.get("selected_project_id") or project_id or ""
        ).strip() or None
        criterion = SuccessCriterion(
            id="request-result-valid",
            description="请求执行结果通过工具与机器断言验证",
            metric="custom",
            operator="valid",
        )
        goal = GoalSpec(
            id=f"goal-{plan_id}",
            user_request=message,
            summary=message[:500],
            domain="cad" if tool_name in {"persist_candidate_variant", "modify_drawing"} else "conversation",
            project_id=selected_project or ("unbound-cad-project" if tool_name in {"persist_candidate_variant", "modify_drawing"} else None),
            source_variant_id=str(variant_id).strip() if variant_id else None,
            targets=_targets(route, project_id, variant_id),
            success_criteria=[criterion],
            risk_level=risk,
        )
        step = PlanStep(
            id=step_id,
            title="执行当前用户请求",
            tool_name=tool_name,
            arguments={"route": {key: route.get(key) for key in (
                "name", "operation", "tool_family", "decision_source", "edit_domain",
            )}},
            risk_level=risk,
            verification_criteria_ids=[criterion.id],
            max_attempts=2,
        )
        decision = decide_step_interruption(
            step,
            target_resolution=(
                {
                    "status": "needs_clarification",
                    "reason": "route_clarification",
                    "question": route.get("clarification_question"),
                }
                if route.get("clarification_required")
                else None
            ),
        )
        if decision.action in {"continue", "confirm"}:
            step = step.model_copy(
                update={"requires_confirmation": decision.requires_confirmation}
            )
        plan = self.store.create(
            ExecutionPlan(id=plan_id, goal=goal, status="ready", steps=[step])
        )
        if decision.action in {"continue", "confirm"}:
            transition = start_plan_step(
                plan,
                step_id,
                sequence=self.store.next_sequence(plan_id),
            )
            self.store.commit(transition, expected_revision=plan.revision)
        return AgentPlanSession(plan_id=plan_id, step_id=step_id)

    def complete(
        self, session: AgentPlanSession, result: dict[str, Any]
    ) -> dict[str, Any]:
        plan = self.store.get(session.plan_id)
        if plan is None:
            raise ValueError("execution plan disappeared")
        step = plan.steps[0]
        pending = isinstance(result.get("pending_action"), dict)
        if step.status=='running' and pending and (result.get('pending_action') or {}).get('id'):
            transition=await_dynamic_confirmation(plan,step.id,sequence=self.store.next_sequence(plan.id))
            plan=self.store.commit(transition,expected_revision=plan.revision)
            step=plan.steps[0]
        if step.status == "awaiting_confirmation" and pending:
            action_id = str((result.get("pending_action") or {}).get("id") or "")
            if action_id:
                self.store.bind_pending_action(action_id, plan.id)
            return self._attach(result, plan)
        if step.status == "awaiting_confirmation":
            transition = start_plan_step(
                plan,
                step.id,
                sequence=self.store.next_sequence(plan.id),
                confirmed=True,
            )
            plan = self.store.commit(transition, expected_revision=plan.revision)
            step = plan.steps[0]
        if step.status != "running":
            return self._attach(result, plan)

        assertions = result.get("machine_assertions")
        variant = result.get("variant")
        if not isinstance(assertions, dict) and isinstance(variant, dict):
            assertions = variant.get("machine_assertions")
        clarification_pending=bool(result.get('clarification_required') or result.get('clarification_question')
            or isinstance(result.get('clarification'),dict) and result['clarification'].get('status')=='clarification_required')
        verified = result.get("ok") is True and not clarification_pending and (
            not isinstance(assertions, dict) or assertions.get("verified") is not False
        )
        now = datetime.now(timezone.utc)
        failure_codes = (
            [str(value) for value in assertions.get("failure_codes") or []]
            if isinstance(assertions, dict)
            else []
        )
        failed_result = StepResult(
            step_id=step.id,
            attempt=step.attempt_count,
            status="failed",
            started_at=now,
            output={"machine_assertions": assertions or {}},
            verification={"request-result-valid": False},
            failure_code=failure_codes[0] if failure_codes else "request_failed",
            failure_message=str(result.get("message") or "请求执行失败")[:1000],
            retryable=True,
        )
        repair = result.get("edit_repair")
        if not isinstance(repair, dict) and isinstance(variant, dict):
            edit_plan = variant.get("edit_plan")
            if isinstance(edit_plan, dict):
                repair = edit_plan.get("assertion_recovery") or edit_plan.get("repair")
        if isinstance(repair, dict) and repair.get("attempted") is True:
            transition = start_deterministic_repair(
                plan,
                failed_result,
                sequence=self.store.next_sequence(plan.id),
                evidence=repair,
            )
            plan = self.store.commit(transition, expected_revision=plan.revision)
            transition = resume_plan_step_after_repair(
                plan,
                step.id,
                sequence=self.store.next_sequence(plan.id),
            )
            plan = self.store.commit(transition, expected_revision=plan.revision)
            step = plan.steps[0]

        final_result = (
            StepResult(
                step_id=step.id,
                attempt=step.attempt_count,
                status="verified",
                started_at=now,
                output={"machine_assertions": assertions or {}},
                verification={"request-result-valid": True},
            )
            if verified
            else failed_result.model_copy(update={"attempt": step.attempt_count})
        )
        if not verified:
            resolution = classify_agent_failure(
                failure_codes, message=str(result.get("message") or "")
            )
            if resolution.get("next_action") in {"replan", "refresh_and_replan"}:
                transition = request_plan_replan(
                    plan,
                    final_result,
                    sequence=self.store.next_sequence(plan.id),
                )
                plan = self.store.commit(transition, expected_revision=plan.revision)
                return self._attach(result, plan)
        transition = finish_plan_step(
            plan,
            final_result,
            sequence=self.store.next_sequence(plan.id),
        )
        plan = self.store.commit(transition, expected_revision=plan.revision)
        return self._attach(result, plan)

    def _attach(
        self, result: dict[str, Any], plan: ExecutionPlan
    ) -> dict[str, Any]:
        enriched = dict(result)
        evaluation = evaluate_plan_chain(plan, self.store.events(plan.id))
        enriched["execution_plan"] = {
            "id": plan.id,
            "status": plan.status,
            "revision": plan.revision,
            "step_status": plan.steps[0].status,
            "repair_count": plan.deterministic_repair_count,
            "replan_count": plan.replan_count,
            "evaluation": evaluation,
        }
        return enriched

    def complete_pending_action(
        self,
        action_id: str,
        *,
        approved: bool,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        plan_id = self.store.plan_id_for_action(action_id)
        if plan_id is None:
            return result
        plan = self.store.get(plan_id)
        if plan is None:
            self.store.unbind_pending_action(action_id)
            return result
        session = AgentPlanSession(plan_id=plan.id, step_id=plan.steps[0].id)
        try:
            if not approved:
                transition = cancel_plan(
                    plan,
                    session.step_id,
                    sequence=self.store.next_sequence(plan.id),
                )
                plan = self.store.commit(
                    transition, expected_revision=plan.revision
                )
                return self._attach(result, plan)
            return self.complete(session, result)
        finally:
            self.store.unbind_pending_action(action_id)

    def run(
        self,
        message: str,
        route: dict[str, Any],
        executor: Callable[[], dict[str, Any]],
        *,
        project_id: str | None = None,
        variant_id: str | None = None,
    ) -> dict[str, Any]:
        session = self.begin(
            message, route, project_id=project_id, variant_id=variant_id
        )
        try:
            return self.complete(session, executor())
        except Exception as error:
            plan = self.store.get(session.plan_id)
            if plan is not None and plan.steps[0].status == "running":
                now = datetime.now(timezone.utc)
                failure = StepResult(
                    step_id=session.step_id,
                    attempt=plan.steps[0].attempt_count,
                    status="failed",
                    started_at=now,
                    failure_code="executor_exception",
                    failure_message=str(error)[:1000] or "执行器异常",
                    retryable=True,
                )
                transition = finish_plan_step(
                    plan, failure, sequence=self.store.next_sequence(plan.id)
                )
                self.store.commit(transition, expected_revision=plan.revision)
            raise


agent_plan_runtime = AgentPlanExecutionController()
