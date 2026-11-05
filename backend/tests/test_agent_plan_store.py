import tempfile
from pathlib import Path

import pytest

from app.agent_plan_models import ExecutionPlan, GoalSpec, PlanStep, SuccessCriterion
from app.agent_plan_orchestrator import start_plan_step
from app.agent_plan_store import AgentPlanStore


def _plan() -> ExecutionPlan:
    return ExecutionPlan(
        id="plan-1",
        status="ready",
        goal=GoalSpec(
            id="goal-1",
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


def test_store_persists_snapshot_and_append_only_events() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "plans.json"
        store = AgentPlanStore(path)
        created = store.create(_plan())
        transition = start_plan_step(
            created, "inspect", sequence=store.next_sequence(created.id)
        )
        store.commit(transition, expected_revision=created.revision)

        restored = AgentPlanStore(path)
        assert restored.get("plan-1").steps[0].status == "running"
        assert [event.event_type for event in restored.events("plan-1")] == [
            "plan_created",
            "step_started",
        ]


def test_store_rejects_stale_snapshot_commit() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = AgentPlanStore(Path(directory) / "plans.json")
        created = store.create(_plan())
        transition = start_plan_step(created, "inspect", sequence=2)
        store.commit(transition, expected_revision=1)

        with pytest.raises(ValueError, match="stale plan revision"):
            store.commit(transition, expected_revision=1)


def test_store_rejects_event_sequence_gap() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = AgentPlanStore(Path(directory) / "plans.json")
        created = store.create(_plan())
        transition = start_plan_step(created, "inspect", sequence=9)

        with pytest.raises(ValueError, match="append-only"):
            store.commit(transition, expected_revision=1)


def test_returned_event_list_cannot_mutate_store() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = AgentPlanStore(Path(directory) / "plans.json")
        store.create(_plan())
        events = store.events("plan-1")
        events.clear()

        assert len(store.events("plan-1")) == 1
