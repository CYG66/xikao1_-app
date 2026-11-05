"""Persistent plan snapshots with an append-only transition event stream."""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path

from .agent_plan_models import ExecutionPlan, PlanEvent, PlanTransition


class AgentPlanStore:
    """Store validated plan snapshots while never rewriting historical events."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._plans: dict[str, ExecutionPlan] = {}
        self._events: dict[str, list[PlanEvent]] = {}
        self._load()

    def create(self, plan: ExecutionPlan) -> ExecutionPlan:
        plan = ExecutionPlan.model_validate(plan.model_dump())
        with self._lock:
            if plan.id in self._plans:
                raise ValueError("plan already exists")
            event = PlanEvent(
                id=str(uuid.uuid4()),
                plan_id=plan.id,
                sequence=1,
                plan_revision=plan.revision,
                event_type="plan_created",
                from_status=None,
                to_status=plan.status,
                message="执行计划已创建",
            )
            self._plans[plan.id] = plan
            self._events[plan.id] = [event]
            self._save()
            return plan.model_copy(deep=True)

    def get(self, plan_id: str) -> ExecutionPlan | None:
        with self._lock:
            plan = self._plans.get(plan_id)
            return plan.model_copy(deep=True) if plan is not None else None

    def events(self, plan_id: str) -> list[PlanEvent]:
        with self._lock:
            return [item.model_copy(deep=True) for item in self._events.get(plan_id, [])]

    def next_sequence(self, plan_id: str) -> int:
        with self._lock:
            if plan_id not in self._plans:
                raise ValueError("unknown plan")
            return len(self._events.get(plan_id, [])) + 1

    def commit(
        self,
        transition: PlanTransition,
        *,
        expected_revision: int,
    ) -> ExecutionPlan:
        transition = PlanTransition.model_validate(transition.model_dump())
        plan_id = transition.plan.id
        with self._lock:
            current = self._plans.get(plan_id)
            if current is None:
                raise ValueError("unknown plan")
            if current.revision != expected_revision:
                raise ValueError("stale plan revision")
            if transition.plan.revision != expected_revision + 1:
                raise ValueError("plan revision must advance exactly once")
            events = self._events.setdefault(plan_id, [])
            if transition.event.sequence != len(events) + 1:
                raise ValueError("event sequence must be append-only")
            if any(item.id == transition.event.id for item in events):
                raise ValueError("event already exists")
            self._plans[plan_id] = transition.plan
            events.append(transition.event)
            self._save()
            return transition.plan.model_copy(deep=True)

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return
        plans = payload.get("plans") if isinstance(payload, dict) else None
        events = payload.get("events") if isinstance(payload, dict) else None
        if not isinstance(plans, list) or not isinstance(events, list):
            return
        loaded_plans: dict[str, ExecutionPlan] = {}
        loaded_events: dict[str, list[PlanEvent]] = {}
        try:
            for raw in plans:
                plan = ExecutionPlan.model_validate(raw)
                loaded_plans[plan.id] = plan
            for raw in events:
                event = PlanEvent.model_validate(raw)
                if event.plan_id in loaded_plans:
                    loaded_events.setdefault(event.plan_id, []).append(event)
            for plan_id, values in loaded_events.items():
                values.sort(key=lambda item: item.sequence)
                if [item.sequence for item in values] != list(range(1, len(values) + 1)):
                    raise ValueError("invalid persisted event sequence")
        except (TypeError, ValueError):
            return
        self._plans = loaded_plans
        self._events = loaded_events

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "schema_version": "agent.plan-store.v1",
                    "plans": [
                        item.model_dump(mode="json") for item in self._plans.values()
                    ],
                    "events": [
                        event.model_dump(mode="json")
                        for values in self._events.values()
                        for event in values
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
