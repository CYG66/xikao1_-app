import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.agent_plan_evaluation import evaluate_plan_chain
from app.agent_plan_models import (
    ExecutionPlan,
    GoalSpec,
    PlanStep,
    StepResult,
    SuccessCriterion,
)
from app.agent_plan_orchestrator import finish_plan_step, start_plan_step
from app.agent_plan_recovery import (
    apply_replanned_steps,
    request_plan_replan,
    start_deterministic_repair,
)
from app.agent_plan_sqlite_store import SQLiteAgentPlanStore


def _plan(plan_id: str) -> ExecutionPlan:
    return ExecutionPlan(
        id=plan_id,
        status="ready",
        goal=GoalSpec(
            id=f"goal-{plan_id}",
            user_request="修改并验证图纸",
            summary="修改并验证图纸",
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
                max_attempts=2,
            )
        ],
    )


def _result(status: str, *, attempt: int = 1) -> StepResult:
    now = datetime.now(timezone.utc)
    if status == "failed":
        return StepResult(
            step_id="edit",
            attempt=attempt,
            status="failed",
            started_at=now,
            output={
                "machine_assertions": {
                    "failure_codes": ["target_scope_mismatch"]
                }
            },
            failure_code="target_scope_mismatch",
            failure_message="目标范围不一致",
            retryable=True,
        )
    return StepResult(
        step_id="edit",
        attempt=attempt,
        status="verified",
        started_at=now,
        verification={"valid": True},
    )


def _commit(store: SQLiteAgentPlanStore, transition) -> ExecutionPlan:
    return store.commit(
        transition,
        expected_revision=transition.plan.revision - 1,
    )


def test_complete_task_chain_passes_after_persistence_reload() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = SQLiteAgentPlanStore(Path(directory) / "plans.sqlite3")
        plan = store.create(_plan("chain-complete"))
        plan = _commit(
            store,
            start_plan_step(plan, "edit", sequence=store.next_sequence(plan.id)),
        )
        plan = _commit(
            store,
            finish_plan_step(plan, _result("verified"), sequence=3),
        )

        reopened = SQLiteAgentPlanStore(store.path)
        persisted = reopened.get(plan.id)
        assert persisted is not None
        evaluation = evaluate_plan_chain(
            persisted,
            reopened.events(plan.id),
            expected_terminal_status="completed",
        )
        assert evaluation["passed"] is True
        assert evaluation["summary"]["event_count"] == 3


def test_repair_chain_is_recorded_once_and_evaluates_cleanly() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = SQLiteAgentPlanStore(Path(directory) / "plans.sqlite3")
        plan = store.create(_plan("chain-repair"))
        plan = _commit(store, start_plan_step(plan, "edit", sequence=2))
        plan = _commit(
            store,
            start_deterministic_repair(
                plan,
                _result("failed"),
                sequence=3,
                evidence={"repair": "restore_target_scope"},
            ),
        )

        evaluation = evaluate_plan_chain(plan, store.events(plan.id))
        assert evaluation["passed"] is True
        assert evaluation["summary"]["repair_count"] == 1
        assert store.events(plan.id)[-1].event_type == "plan_repair_started"


def test_replan_chain_replaces_step_and_completes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = SQLiteAgentPlanStore(Path(directory) / "plans.sqlite3")
        plan = store.create(_plan("chain-replan"))
        plan = _commit(store, start_plan_step(plan, "edit", sequence=2))
        plan = _commit(
            store,
            request_plan_replan(plan, _result("failed"), sequence=3),
        )
        replacement = PlanStep(
            id="edit-v2",
            title="重新修改图纸",
            tool_name="modify_drawing",
            verification_criteria_ids=["valid"],
        )
        plan = _commit(
            store,
            apply_replanned_steps(plan, "edit", [replacement], sequence=4),
        )
        plan = _commit(store, start_plan_step(plan, "edit-v2", sequence=5))
        verified = _result("verified").model_copy(update={"step_id": "edit-v2"})
        plan = _commit(store, finish_plan_step(plan, verified, sequence=6))

        evaluation = evaluate_plan_chain(
            plan,
            store.events(plan.id),
            expected_terminal_status="completed",
        )
        assert evaluation["passed"] is True
        assert evaluation["summary"]["replan_count"] == 1
        assert [event.event_type for event in store.events(plan.id)][2:4] == [
            "plan_replan_requested",
            "plan_replanned",
        ]


def test_chain_evaluation_detects_missing_or_tampered_event() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = SQLiteAgentPlanStore(Path(directory) / "plans.sqlite3")
        plan = store.create(_plan("chain-invalid"))
        plan = _commit(store, start_plan_step(plan, "edit", sequence=2))
        plan = _commit(store, finish_plan_step(plan, _result("verified"), sequence=3))

        events = store.events(plan.id)
        evaluation = evaluate_plan_chain(plan, [events[0], events[2]])
        assert evaluation["passed"] is False
        assert evaluation["checks"]["event_sequence_contiguous"] is False
        assert evaluation["checks"]["event_revisions_contiguous"] is False

        foreign_event = events[0].model_copy(update={"plan_id": "another-plan"})
        foreign = evaluate_plan_chain(plan, [foreign_event, *events[1:]])
        assert foreign["passed"] is False
        assert foreign["checks"]["events_match_plan"] is False
