"""Evaluate persisted agent plan traces without invoking tools or models."""

from __future__ import annotations

from typing import Iterable

from .agent_plan_models import ExecutionPlan, PlanEvent


def evaluate_plan_chain(
    plan: ExecutionPlan,
    events: Iterable[PlanEvent],
    *,
    expected_terminal_status: str | None = None,
) -> dict:
    """Check revision, event, recovery, and terminal-state invariants."""
    ordered = list(events)
    sequences = [event.sequence for event in ordered]
    revisions = [event.plan_revision for event in ordered]
    event_types = [event.event_type for event in ordered]
    checks = {
        "has_creation_event": bool(ordered)
        and ordered[0].event_type == "plan_created",
        "events_match_plan": bool(ordered)
        and all(event.plan_id == plan.id for event in ordered),
        "event_sequence_contiguous": sequences == list(range(1, len(ordered) + 1)),
        "event_revisions_contiguous": revisions
        == list(range(1, len(ordered) + 1)),
        "latest_revision_matches": bool(ordered)
        and ordered[-1].plan_revision == plan.revision,
        "repair_limit_respected": (
            plan.deterministic_repair_count <= plan.deterministic_repair_limit
        ),
        "replan_limit_respected": plan.replan_count <= plan.replan_limit,
        "repair_events_match_count": event_types.count("plan_repair_started")
        == plan.deterministic_repair_count,
        "replan_events_match_count": event_types.count("plan_replan_requested")
        == plan.replan_count,
        "step_terminal_consistency": (
            plan.status != "completed"
            or all(step.status in {"verified", "skipped"} for step in plan.steps)
        ),
    }
    if expected_terminal_status is not None:
        checks["expected_terminal_status"] = plan.status == expected_terminal_status
    return {
        "schema": "agent.plan-chain-evaluation.v1",
        "plan_id": plan.id,
        "passed": all(checks.values()),
        "checks": checks,
        "summary": {
            "status": plan.status,
            "revision": plan.revision,
            "event_count": len(ordered),
            "repair_count": plan.deterministic_repair_count,
            "replan_count": plan.replan_count,
        },
    }
