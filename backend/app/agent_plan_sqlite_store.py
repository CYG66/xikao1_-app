"""Transactional SQLite persistence for agent plans and append-only events."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .agent_plan_models import ExecutionPlan, PlanEvent, PlanTransition


class SQLiteAgentPlanStore:
    """Persist plans atomically with optimistic revision and event ordering."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_plans (
                    plan_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_plan_events (
                    event_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    plan_revision INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(plan_id) REFERENCES agent_plans(plan_id),
                    UNIQUE(plan_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_plan_events_plan
                    ON agent_plan_events(plan_id, sequence);
                CREATE TABLE IF NOT EXISTS agent_plan_pending_actions (
                    action_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(plan_id) REFERENCES agent_plans(plan_id)
                );
                """
            )

    @staticmethod
    def _dump(value: ExecutionPlan | PlanEvent) -> str:
        return json.dumps(
            value.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def create(self, plan: ExecutionPlan) -> ExecutionPlan:
        plan = ExecutionPlan.model_validate(plan.model_dump())
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
        with self._lock, self._connection() as connection:
            try:
                connection.execute(
                    """INSERT INTO agent_plans
                    (plan_id, revision, status, payload_json, updated_at)
                    VALUES (?, ?, ?, ?, ?)""",
                    (
                        plan.id,
                        plan.revision,
                        plan.status,
                        self._dump(plan),
                        plan.updated_at.isoformat(),
                    ),
                )
                connection.execute(
                    """INSERT INTO agent_plan_events
                    (event_id, plan_id, sequence, plan_revision, event_type,
                     payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event.id,
                        event.plan_id,
                        event.sequence,
                        event.plan_revision,
                        event.event_type,
                        self._dump(event),
                        event.created_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("plan already exists") from exc
        return plan.model_copy(deep=True)

    def get(self, plan_id: str) -> ExecutionPlan | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM agent_plans WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
        if row is None:
            return None
        return ExecutionPlan.model_validate_json(row["payload_json"])

    def events(self, plan_id: str) -> list[PlanEvent]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """SELECT payload_json FROM agent_plan_events
                WHERE plan_id = ? ORDER BY sequence""",
                (plan_id,),
            ).fetchall()
        return [PlanEvent.model_validate_json(row["payload_json"]) for row in rows]

    def next_sequence(self, plan_id: str) -> int:
        with self._lock, self._connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM agent_plans WHERE plan_id = ?", (plan_id,)
            ).fetchone()
            if exists is None:
                raise ValueError("unknown plan")
            row = connection.execute(
                """SELECT COALESCE(MAX(sequence), 0) AS maximum
                FROM agent_plan_events WHERE plan_id = ?""",
                (plan_id,),
            ).fetchone()
        return int(row["maximum"]) + 1

    def bind_pending_action(self, action_id: str, plan_id: str) -> None:
        if not action_id:
            raise ValueError("pending action id is required")
        with self._lock, self._connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM agent_plans WHERE plan_id = ?", (plan_id,)
            ).fetchone()
            if exists is None:
                raise ValueError("unknown plan")
            connection.execute(
                """INSERT INTO agent_plan_pending_actions (action_id, plan_id)
                VALUES (?, ?)
                ON CONFLICT(action_id) DO UPDATE SET plan_id = excluded.plan_id""",
                (action_id, plan_id),
            )

    def plan_id_for_action(self, action_id: str) -> str | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT plan_id FROM agent_plan_pending_actions WHERE action_id = ?",
                (action_id,),
            ).fetchone()
        return str(row["plan_id"]) if row is not None else None

    def unbind_pending_action(self, action_id: str) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                "DELETE FROM agent_plan_pending_actions WHERE action_id = ?",
                (action_id,),
            )

    def commit(
        self,
        transition: PlanTransition,
        *,
        expected_revision: int,
    ) -> ExecutionPlan:
        transition = PlanTransition.model_validate(transition.model_dump())
        plan = transition.plan
        event = transition.event
        if plan.revision != expected_revision + 1:
            raise ValueError("plan revision must advance exactly once")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    "SELECT revision FROM agent_plans WHERE plan_id = ?",
                    (plan.id,),
                ).fetchone()
                if current is None:
                    raise ValueError("unknown plan")
                if int(current["revision"]) != expected_revision:
                    raise ValueError("stale plan revision")
                sequence = connection.execute(
                    """SELECT COALESCE(MAX(sequence), 0) AS maximum
                    FROM agent_plan_events WHERE plan_id = ?""",
                    (plan.id,),
                ).fetchone()
                if event.sequence != int(sequence["maximum"]) + 1:
                    raise ValueError("event sequence must be append-only")
                connection.execute(
                    """UPDATE agent_plans
                    SET revision = ?, status = ?, payload_json = ?, updated_at = ?
                    WHERE plan_id = ? AND revision = ?""",
                    (
                        plan.revision,
                        plan.status,
                        self._dump(plan),
                        plan.updated_at.isoformat(),
                        plan.id,
                        expected_revision,
                    ),
                )
                connection.execute(
                    """INSERT INTO agent_plan_events
                    (event_id, plan_id, sequence, plan_revision, event_type,
                     payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event.id,
                        event.plan_id,
                        event.sequence,
                        event.plan_revision,
                        event.event_type,
                        self._dump(event),
                        event.created_at.isoformat(),
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise ValueError("event already exists or is out of order") from exc
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
        return plan.model_copy(deep=True)
