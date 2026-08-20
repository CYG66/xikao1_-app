from __future__ import annotations

import tempfile
import unittest
import json
import os
from pathlib import Path
from unittest.mock import patch

from app.creative_projects import CreativeProjectStore
from app.creative_workflow import (
    CreativeProjectSynchronizer,
    prepare_project_recovery,
    project_recovery_assessment,
    refresh_project_execution,
)
from app.state import robot_state


class CreativeExecutionTest(unittest.TestCase):
    def _project_store(self, directory: str) -> tuple[CreativeProjectStore, str]:
        store = CreativeProjectStore(Path(directory) / "projects.json")
        project = store.create("标线", "画一条线")
        variant = store.add_variant(
            project["id"], "方案 A", [{"id": 1}], "测试", {"score": 90}, []
        )
        store.select_variant(project["id"], variant["id"])
        store.set_planning(project["id"], {
            "stage": "planning_preview", "validation": {}, "file_name": "line_v001.json"
        })
        store.set_planning(project["id"], {
            "stage": "ready", "validation": {"ok": True}, "file_name": "line_v001.json"
        })
        store.set_execution(project["id"], {
            "stage": "pending_confirmation", "file_name": "line_v001.json", "action_id": "action-1"
        })
        return store, project["id"]

    def test_execution_refresh_persists_checkpoints_and_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, project_id = self._project_store(directory)
            mission = {"state": "executing", "oscillation_events": [{"reversals": 4}]}
            with (
                patch("app.creative_workflow.creative_projects", store),
                patch("app.creative_workflow.mission_ledger.get", return_value=mission),
                patch.object(robot_state, "mission_file", "line_v001.json"),
                patch.object(robot_state, "mission_ledger_id", "mission-1"),
                patch.object(robot_state, "mission_stage", "executing"),
                patch.object(robot_state, "mission_running", True),
                patch.object(robot_state, "mission_paused", False),
                patch.object(robot_state, "mission_completed", 2),
                patch.object(robot_state, "mission_total", 5),
                patch.object(robot_state, "mission_current_id", 3),
                patch.object(robot_state, "mission_last_verified_id", 2),
                patch.object(robot_state, "mission_checkpoint", {"ok": True}),
                patch.object(robot_state, "mission_segment_verification", {"ok": True}),
                patch.object(robot_state, "oscillation_detected", True),
                patch.object(robot_state, "mission_error", ""),
            ):
                result = refresh_project_execution(project_id)

            self.assertTrue(result["ok"])
            self.assertEqual(result["execution"]["progress"], 0.4)
            self.assertEqual(result["execution"]["oscillation_event_count"], 1)
            self.assertFalse(result["execution"]["auto_resume_allowed"])
            self.assertEqual(store.get(project_id)["status"], "executing")

    def test_recovery_never_allows_automatic_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, project_id = self._project_store(directory)
            with (
                patch("app.creative_workflow.creative_projects", store),
                patch("app.creative_workflow.mission_ledger.get", return_value={"state": "failed"}),
                patch.object(robot_state, "mission_file", "line_v001.json"),
                patch.object(robot_state, "mission_ledger_id", "mission-1"),
                patch.object(robot_state, "mission_stage", "failed"),
                patch.object(robot_state, "mission_running", False),
                patch.object(robot_state, "mission_paused", False),
                patch.object(robot_state, "mission_completed", 1),
                patch.object(robot_state, "mission_total", 5),
                patch.object(robot_state, "mission_error", "定位丢失"),
            ):
                result = project_recovery_assessment(project_id)

            self.assertTrue(result["ok"])
            self.assertFalse(result["recovery"]["auto_resume_allowed"])
            self.assertTrue(result["recovery"]["resume_requires_replanning"])
            self.assertTrue(result["recovery"]["resume_requires_user_confirmation"])

    def test_recovery_replans_only_unfinished_printing_segments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, project_id = self._project_store(directory)
            store.set_execution(project_id, {
                "stage": "failed", "mission_id": "mission-1", "file_name": "line_v001.json"
            })
            completed = {
                "id": 1, "type": "line", "work": True, "layer_id": 1,
                "ink": {"enabled": True, "printer": "center"},
                "start": {"x": 0, "y": 0, "z": 0}, "end": {"x": 1000, "y": 0, "z": 0},
            }
            remaining = {
                "id": 2, "type": "line", "work": True, "layer_id": 1,
                "ink": {"enabled": True, "printer": "center"},
                "start": {"x": 1000, "y": 0, "z": 0}, "end": {"x": 2000, "y": 0, "z": 0},
            }
            mission = {
                "id": "mission-1", "file_name": "line_v001.json",
                "segments": [
                    {"kind": "printing", "state": "completed"},
                    {"kind": "printing", "state": "failed"},
                ],
                "planned_segments": [completed, remaining],
            }
            with (
                patch("app.creative_workflow.creative_projects", store),
                patch("app.creative_workflow.mission_ledger.get", return_value=mission),
                patch("app.creative_workflow.ros_adapter.prepare_mission", return_value=True),
                patch.object(robot_state, "mission_running", False),
                patch.object(robot_state, "mission_paused", False),
                patch.object(robot_state, "mission_stage", "planning_preview"),
                patch.dict(os.environ, {"XLINE_CAD_DIR": directory}),
            ):
                result = prepare_project_recovery(project_id)

            self.assertTrue(result["ok"])
            payload = json.loads(Path(directory, result["planning"]["file_name"]).read_text(encoding="utf-8"))
            self.assertEqual([item["id"] for item in payload["lines"]], [2])
            self.assertEqual(payload["completed_printing_segment_ids"], [1])
            self.assertTrue(result["planning"]["recovery"]["manual_inspection_required"])

    def test_sync_returns_cancelled_confirmation_to_planning_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, project_id = self._project_store(directory)
            sync = CreativeProjectSynchronizer()
            with (
                patch("app.creative_workflow.creative_projects", store),
                patch("app.creative_workflow.agent_tasks.get", return_value={"state": "cancelled"}),
            ):
                sync.sync_once()

            project = store.get(project_id)
            self.assertEqual(project["status"], "planning_ready")
            self.assertEqual(project["execution"]["stage"], "confirmation_cancelled")

    def test_sync_marks_interrupted_mission_recoverable_without_motion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, project_id = self._project_store(directory)
            store.set_execution(project_id, {
                "stage": "executing", "mission_id": "mission-1",
                "file_name": "line_v001.json",
            })
            mission = {
                "id": "mission-1", "state": "interrupted",
                "file_name": "line_v001.json",
                "segments": [
                    {"segment_id": 10, "state": "completed"},
                    {"segment_id": 11, "state": "interrupted"},
                ],
            }
            sync = CreativeProjectSynchronizer()
            with (
                patch("app.creative_workflow.creative_projects", store),
                patch("app.creative_workflow.mission_ledger.get", return_value=mission),
            ):
                sync.sync_once()

            project = store.get(project_id)
            self.assertEqual(project["status"], "execution_failed")
            self.assertEqual(project["execution"]["last_verified_segment_id"], 10)
            self.assertFalse(project["execution"]["auto_resume_allowed"])
            self.assertTrue(project["execution"]["recovery_required"])


if __name__ == "__main__":
    unittest.main()
