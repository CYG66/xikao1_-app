from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app.task_store import AgentTaskStore
from app.mission_ledger import MissionLedgerStore


class AgentTaskStoreTest(unittest.TestCase):
    def test_execution_context_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.json"
            context = {"request_id": "r1", "conversation_id": "c1", "sha256": "h"}
            AgentTaskStore(path).create_pending(
                "ctx-task", "drive_robot", {"linear": 0.1},
                datetime.now() + timedelta(minutes=2), execution_context=context,
            )
            restored = AgentTaskStore(path).get("ctx-task")
            self.assertEqual(restored["execution_context"], context)

    def test_legacy_pending_without_context_remains_identifiable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.json"
            AgentTaskStore(path).create_pending(
                "legacy", "drive_robot", {"linear": 0.1}, datetime.now() + timedelta(minutes=2),
            )
            restored = AgentTaskStore(path).get("legacy")
            self.assertIsNone(restored.get("execution_context"))

    def test_task_lifecycle_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.json"
            store = AgentTaskStore(path)
            store.create_pending("task-1", "drive_robot", {"linear": 0.1}, datetime.now() + timedelta(minutes=2))
            store.transition("task-1", "executing", "confirmed")
            store.transition("task-1", "completed", "done", {"ok": True})

            restored = AgentTaskStore(path).get("task-1")
            self.assertIsNotNone(restored)
            self.assertEqual(restored["state"], "completed")
            self.assertEqual(restored["result"], {"ok": True})
            self.assertEqual(len(restored["events"]), 3)

    def test_restart_marks_executing_task_interrupted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.json"
            # Recovery authorization is an explicit prerequisite; do not rely
            # on the ambient non-production default enabling recovery.
            with patch.dict(os.environ, {"XLINE_STARTUP_RECOVERY_MODE": "authorized"}):
                store = AgentTaskStore(path)
                store.create_pending("task-2", "set_mission", {"running": True}, datetime.now() + timedelta(minutes=2))
                store.transition("task-2", "executing", "confirmed")

                restored = AgentTaskStore(path).get("task-2")
                self.assertEqual(restored["state"], "interrupted")
                self.assertIn("不会自动恢复", restored["events"][-1]["message"])

    def test_restart_keeps_executing_task_when_recovery_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.json"
            with patch.dict(os.environ, {"XLINE_STARTUP_RECOVERY_MODE": "disabled"}):
                store = AgentTaskStore(path)
                store.create_pending("task-2", "set_mission", {"running": True}, datetime.now() + timedelta(minutes=2))
                store.transition("task-2", "executing", "confirmed")

                restored = AgentTaskStore(path).get("task-2")
                self.assertEqual(restored["state"], "executing")
                self.assertNotIn("不会自动恢复", restored["events"][-1]["message"])

    def test_operator_can_cancel_task_while_waiting_for_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentTaskStore(Path(directory) / "tasks.json")
            store.create_pending(
                "task-stop",
                "drive_robot",
                {"linear": 0.1},
                datetime.now() + timedelta(minutes=2),
            )
            store.transition("task-stop", "executing", "confirmed")
            store.transition("task-stop", "verifying", "checking telemetry")
            store.transition("task-stop", "awaiting_verification", "still moving")

            cancelled = store.transition(
                "task-stop",
                "cancelled",
                "已按你的要求停止小车运动。",
                {"ok": True, "message": "已按你的要求停止小车运动。"},
            )

            self.assertEqual(cancelled["state"], "cancelled")
            self.assertEqual(cancelled["result"]["ok"], True)

    def test_expired_confirmation_is_not_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.json"
            store = AgentTaskStore(path)
            store.create_pending("task-3", "control_ln150", {}, datetime.now() - timedelta(seconds=1))

            self.assertEqual(store.recoverable_pending(), [])
            self.assertEqual(store.get("task-3")["state"], "expired")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "1.0")

    def test_mission_ledger_persists_planned_and_actual_trajectories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            store = MissionLedgerStore(path)
            mission = store.create(
                "drawing.json", {}, [{"id": 1}], lambda _: "printing",
                planned_paths=[{"points": [[0.0, 0.0], [1.0, 0.0]]}],
            )
            store.set_actual_trace(mission["id"], [[0.0, 0.1], [1.0, 0.1]])

            restored = MissionLedgerStore(path).get(mission["id"])
            self.assertEqual(restored["planned_paths"][0]["points"][-1], [1.0, 0.0])
            self.assertEqual(restored["actual_trace"][-1], [1.0, 0.1])


if __name__ == "__main__":
    unittest.main()
