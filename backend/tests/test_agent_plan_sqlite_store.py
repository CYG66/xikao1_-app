import tempfile
from pathlib import Path

import pytest

from app.agent_plan_models import ExecutionPlan, GoalSpec, PlanStep, SuccessCriterion
from app.agent_plan_orchestrator import start_plan_step
from app.agent_plan_sqlite_store import SQLiteAgentPlanStore


def _plan(plan_id: str = "plan-sqlite") -> ExecutionPlan:
    return ExecutionPlan(
        id=plan_id,
        status="ready",
        goal=GoalSpec(
            id=f"goal-{plan_id}",
            user_request="检查图纸",
            summary="检查图纸",
            domain="cad",
            project_id="project-1",
            success_criteria=[
                SuccessCriterion(
                    id="valid",
                    description="图纸有效",
                    metric="topology",
                    operator="valid",
                )
            ],
        ),
        steps=[PlanStep(id="inspect", title="检查", tool_name="inspect_drawing")],
    )


def test_sqlite_store_survives_reopen_and_preserves_events() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "plans.sqlite3"
        store = SQLiteAgentPlanStore(path)
        created = store.create(_plan())
        transition = start_plan_step(
            created,
            "inspect",
            sequence=store.next_sequence(created.id),
        )
        store.commit(transition, expected_revision=created.revision)

        reopened = SQLiteAgentPlanStore(path)
        restored = reopened.get(created.id)
        assert restored is not None
        assert restored.revision == 2
        assert restored.steps[0].status == "running"
        assert [event.event_type for event in reopened.events(created.id)] == [
            "plan_created",
            "step_started",
        ]


def test_sqlite_store_rejects_stale_cross_instance_commit() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "plans.sqlite3"
        first = SQLiteAgentPlanStore(path)
        second = SQLiteAgentPlanStore(path)
        created = first.create(_plan())
        stale_copy = second.get(created.id)
        assert stale_copy is not None

        accepted = start_plan_step(created, "inspect", sequence=2)
        first.commit(accepted, expected_revision=1)
        stale = start_plan_step(stale_copy, "inspect", sequence=2)

        with pytest.raises(ValueError, match="stale plan revision"):
            second.commit(stale, expected_revision=1)

        assert len(first.events(created.id)) == 2


def test_sqlite_store_rejects_sequence_gap_and_duplicate_plan() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = SQLiteAgentPlanStore(Path(directory) / "plans.sqlite3")
        created = store.create(_plan())
        transition = start_plan_step(created, "inspect", sequence=9)

        with pytest.raises(ValueError, match="append-only"):
            store.commit(transition, expected_revision=1)
        with pytest.raises(ValueError, match="plan already exists"):
            store.create(_plan())

        assert store.next_sequence(created.id) == 2
        assert len(store.events(created.id)) == 1


def test_sqlite_store_returns_detached_models() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = SQLiteAgentPlanStore(Path(directory) / "plans.sqlite3")
        created = store.create(_plan())
        events = store.events(created.id)
        events.clear()
        restored = store.get(created.id)
        assert restored is not None
        restored.steps[0].status = "failed"

        assert len(store.events(created.id)) == 1
        assert store.get(created.id).steps[0].status == "pending"


def test_sqlite_store_persists_pending_action_binding() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "plans.sqlite3"
        store = SQLiteAgentPlanStore(path)
        created = store.create(_plan())
        store.bind_pending_action("action-1", created.id)

        reopened = SQLiteAgentPlanStore(path)
        assert reopened.plan_id_for_action("action-1") == created.id
        reopened.unbind_pending_action("action-1")
        assert store.plan_id_for_action("action-1") is None
