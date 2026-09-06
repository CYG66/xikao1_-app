from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.database import XLineDatabase


class DatabaseProjectChainTest(unittest.TestCase):
    def test_database_migrations_and_backup_are_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "xline.db"
            database = XLineDatabase(database_path)
            migration_status = database.migration_status()
            self.assertEqual(migration_status["current_version"], 3)
            self.assertEqual(len(migration_status["migrations"]), 3)
            backup = database.backup(Path(directory) / "backup.sqlite")
            self.assertTrue(backup["ok"])
            self.assertGreater(backup["size_bytes"], 0)

    def test_audit_can_be_filtered_without_exposing_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = XLineDatabase(Path(directory) / "xline.db")
            database.record_audit({
                "id": "audit-1", "at": "2026-08-19T10:00:00Z",
                "event": "tool_executed", "tool": "drive_robot", "ok": True,
                "arguments": {"api_key": "***"}, "message": "done",
            })
            database.record_audit({
                "id": "audit-2", "at": "2026-08-19T10:01:00Z",
                "event": "tool_blocked", "tool": "drive_robot", "ok": False,
                "arguments": {}, "message": "blocked",
            })
            records = database.list_audit(tool="drive_robot", ok=False)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["id"], "audit-2")

    def test_device_capabilities_are_upserted_and_decoded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = XLineDatabase(Path(directory) / "xline.db")
            database.upsert_device_capabilities(
                {
                    "vehicle": {
                        "device_id": "rover-1",
                        "model": "XLine Rover",
                        "software_version": "0.1.0",
                        "capabilities": {"manual_drive": True},
                        "motion_limits": {"max_linear_mps": 0.2},
                        "localization": {"valid": False},
                    }
                },
                {
                    "configured_topics": {"tablet_cmd_vel": "/tablet_cmd_vel"},
                    "discovered_topics": {"/cmd_vel": ["geometry_msgs/msg/Twist"]},
                    "configured_services": {"plan_path": "/plan_path"},
                    "discovered_services": {},
                    "configured_actions": {"execute_plan": "/execute_plan"},
                },
            )
            devices = database.list_device_capabilities("rover-1")
            self.assertEqual(len(devices), 1)
            self.assertTrue(devices[0]["capabilities"]["manual_drive"])
            self.assertEqual(
                devices[0]["topics"]["discovered"]["/cmd_vel"][0],
                "geometry_msgs/msg/Twist",
            )

    def test_ai_case_memory_is_project_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = XLineDatabase(Path(directory) / "xline.db")
            database.record_ai_case(
                "project-1", "planning", "prepare_project_plan",
                {"project_id": "project-1"}, {"ok": False, "message": "定位无效"},
            )
            cases = database.list_ai_cases("project-1")
            self.assertEqual(len(cases), 1)
            self.assertFalse(cases[0]["ok"])
            self.assertEqual(cases[0]["category"], "planning")

    def test_project_timeline_links_business_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = XLineDatabase(Path(directory) / "xline.db")
            project_id = "project-1"
            database.save_project({
                "id": project_id,
                "status": "executing",
                "updated_at": "2026-08-19T10:00:00Z",
            })
            database.save_design_version(
                {"file_name": "court_v001.json", "version": 1, "created_at": "1"},
                {"creative_project_id": project_id, "lines": []},
            )
            database.save_planning(
                project_id, {"file_name": "court_v001.json"}, "planning_ready", "2"
            )
            database.save_execution_task({
                "id": "mission-1",
                "project_id": project_id,
                "state": "executing",
                "created_at": "3",
                "updated_at": "3",
                "segments": [{"index": 0, "state": "completed"}],
            })

            timeline = database.project_timeline(project_id)

            self.assertEqual(len(timeline["design_versions"]), 1)
            self.assertEqual(len(timeline["planning_tasks"]), 1)
            self.assertEqual(len(timeline["execution_tasks"]), 1)
            self.assertEqual(len(timeline["execution_segments"]), 1)


if __name__ == "__main__":
    unittest.main()
