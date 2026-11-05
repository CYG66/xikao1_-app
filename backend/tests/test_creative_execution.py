from __future__ import annotations

import tempfile
import unittest
import json
import os
from pathlib import Path
from unittest.mock import patch

from app.creative_projects import CreativeProjectStore
from app.drawing_versions import DrawingVersionStore
from app.routers.projects import delete_creative_project
from app.creative_workflow import (
    CreativeProjectSynchronizer,
    prepare_project_recovery,
    project_recovery_assessment,
    exit_project_plan,
    refresh_project_plan,
    refresh_project_execution,
    resume_project_execution,
    stop_project_before_deletion,
)
from app.state import robot_state


ACCEPTED = {"status": "passed", "review_required": False}


class CreativeExecutionTest(unittest.TestCase):
    def _project_store(self, directory: str) -> tuple[CreativeProjectStore, str]:
        store = CreativeProjectStore(Path(directory) / "projects.json")
        project = store.create("标线", "画一条线")
        variant = store.add_variant(
            project["id"], "方案 A", [{"id": 1}], "测试", {"score": 90}, [],
            acceptance_summary=ACCEPTED,
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

    def test_paused_project_is_cancelled_before_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, project_id = self._project_store(directory)
            store.set_execution(project_id, {
                "stage": "executing", "file_name": "line_v001.json"
            })
            store.set_execution(project_id, {
                "stage": "paused", "file_name": "line_v001.json"
            })
            with (
                patch("app.creative_workflow.get_creative_project_store", return_value=store),
                patch(
                    "app.creative_workflow.ros_adapter.control_mission_action",
                    return_value=True,
                ) as cancel,
                patch.object(robot_state, "mission_file", "line_v001.json"),
                patch.object(robot_state, "mission_running", True),
                patch.object(robot_state, "mission_paused", True),
            ):
                result = stop_project_before_deletion(project_id)

            self.assertTrue(result["ok"])
            self.assertEqual(store.get(project_id)["status"], "cancelled")
            cancel.assert_called_once_with("cancel", "line_v001.json")
            self.assertTrue(store.delete(project_id))

    def test_exit_plan_discards_preview_and_returns_candidate_to_design(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, project_id = self._project_store(directory)
            with (
                patch("app.creative_workflow.get_creative_project_store", return_value=store),
                patch(
                    "app.creative_workflow.ros_adapter.control_mission_action",
                    return_value=True,
                ) as cancel,
                patch.object(robot_state, "mission_file", "line_v001.json"),
                patch.object(robot_state, "mission_running", False),
                patch.object(robot_state, "mission_paused", False),
            ):
                result = exit_project_plan(project_id)

            self.assertTrue(result["ok"])
            updated = store.get(project_id)
            self.assertEqual(updated["status"], "designing")
            self.assertNotIn("selected_variant_id", updated)
            self.assertNotIn("planning", updated)
            self.assertNotIn("execution", updated)
            self.assertEqual(
                updated["design_base_variant_id"],
                updated["variants"][0]["id"],
            )
            self.assertEqual(
                updated["iteration_history"][-1]["planning"]["stage"],
                "cancelled",
            )
            cancel.assert_called_once_with("cancel", "line_v001.json")

    def test_exit_plan_never_cancels_a_running_mission(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, project_id = self._project_store(directory)
            with (
                patch("app.creative_workflow.get_creative_project_store", return_value=store),
                patch(
                    "app.creative_workflow.ros_adapter.control_mission_action",
                    return_value=True,
                ) as cancel,
                patch.object(robot_state, "mission_file", "line_v001.json"),
                patch.object(robot_state, "mission_running", True),
                patch.object(robot_state, "mission_paused", False),
            ):
                result = exit_project_plan(project_id)

            self.assertFalse(result["ok"])
            self.assertEqual(store.get(project_id)["status"], "pending_execution")
            cancel.assert_not_called()

    def test_running_project_remains_protected_from_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, project_id = self._project_store(directory)
            store.set_execution(project_id, {
                "stage": "executing", "file_name": "line_v001.json"
            })
            with patch("app.creative_workflow.get_creative_project_store", return_value=store):
                result = stop_project_before_deletion(project_id)

            self.assertFalse(result["ok"])
            self.assertIn("正在执行", result["message"])
            self.assertIsNotNone(store.get(project_id))

    def test_delete_endpoint_removes_paused_project_after_safe_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, project_id = self._project_store(directory)
            store.set_execution(project_id, {
                "stage": "executing", "file_name": "line_v001.json"
            })
            store.set_execution(project_id, {
                "stage": "paused", "file_name": "line_v001.json"
            })
            with (
                patch("app.routers.projects.get_creative_project_store", return_value=store),
                patch("app.creative_workflow.get_creative_project_store", return_value=store),
                patch(
                    "app.creative_workflow.ros_adapter.control_mission_action",
                    return_value=True,
                ),
                patch.object(robot_state, "mission_file", "line_v001.json"),
                patch.object(robot_state, "mission_running", True),
                patch.object(robot_state, "mission_paused", True),
            ):
                result = delete_creative_project(project_id)

            self.assertTrue(result["ok"])
            self.assertIsNone(store.get(project_id))

    def test_execution_refresh_persists_checkpoints_and_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, project_id = self._project_store(directory)
            mission = {"state": "executing", "oscillation_events": [{"reversals": 4}]}
            with (
                patch("app.creative_workflow.get_creative_project_store", return_value=store),
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

    def test_completed_partition_zone_advances_project_to_next_zone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create("分区标线", "画一条100米长线")
            variant = store.add_variant(
                project["id"],
                "分区方案",
                [
                    {
                        "id": 1,
                        "type": "line",
                        "layer_id": 1,
                        "start": {"x": 0, "y": 0, "z": 0},
                        "end": {"x": 100000, "y": 0, "z": 0},
                    }
                ],
                "两个施工区",
                {
                    "score": 90,
                    "feasibility": {"ok": True, "errors": []},
                    "project_scale": {
                        "requires_partitioning": True,
                        "suggested_rows": 1,
                        "suggested_columns": 2,
                        "work_zone_size_m": 50.0,
                    },
                },
                [],
                acceptance_summary=ACCEPTED,
            )
            store.select_variant(project["id"], variant["id"])
            store.set_planning(project["id"], {
                "variant_id": variant["id"],
                "partition_zone_id": "zone-r001-c001",
                "stage": "planning_preview",
                "validation": {},
                "file_name": "zone-1.json",
            })
            store.set_planning(project["id"], {
                "variant_id": variant["id"],
                "partition_zone_id": "zone-r001-c001",
                "stage": "ready",
                "validation": {"ok": True},
                "file_name": "zone-1.json",
            })
            store.set_execution(project["id"], {
                "stage": "pending_confirmation",
                "file_name": "zone-1.json",
            })
            store.set_execution(project["id"], {
                "stage": "executing",
                "file_name": "zone-1.json",
            })
            with (
                patch("app.creative_workflow.get_creative_project_store", return_value=store),
                patch("app.creative_workflow.mission_ledger.get", return_value={"state": "completed"}),
                patch.object(robot_state, "mission_file", "zone-1.json"),
                patch.object(robot_state, "mission_stage", "completed"),
                patch.object(robot_state, "mission_running", False),
                patch.object(robot_state, "mission_paused", False),
                patch.object(robot_state, "mission_completed", 1),
                patch.object(robot_state, "mission_total", 1),
                patch.object(robot_state, "mission_error", ""),
            ):
                result = refresh_project_execution(project["id"])

            self.assertTrue(result["ok"])
            self.assertEqual(result["execution"]["stage"], "zone_completed")
            self.assertTrue(result["execution"]["next_zone_required"])
            updated = store.get(project["id"])
            self.assertEqual(updated["status"], "ready_for_planning")
            partition = updated["variants"][0]["spatial_partition"]
            self.assertEqual(partition["summary"]["completed_zone_count"], 1)
            self.assertEqual(partition["summary"]["remaining_zone_count"], 1)

    def test_completed_partition_segment_advances_inside_same_zone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create("密集标线", "生成101条标线")
            geometries = [
                {
                    "id": index,
                    "type": "line",
                    "layer_id": 1,
                    "start": {"x": 0, "y": index * 10, "z": 0},
                    "end": {"x": 1000, "y": index * 10, "z": 0},
                }
                for index in range(1, 102)
            ]
            variant = store.add_variant(
                project["id"],
                "密集分段方案",
                geometries,
                "单区两段",
                {
                    "score": 90,
                    "feasibility": {"ok": True, "errors": []},
                    "project_scale": {
                        "requires_partitioning": True,
                        "suggested_rows": 1,
                        "suggested_columns": 1,
                        "work_zone_size_m": 50.0,
                    },
                },
                [],
                acceptance_summary=ACCEPTED,
            )
            store.select_variant(project["id"], variant["id"])
            first_segment = "zone-r001-c001-segment-0001"
            for planning in (
                {
                    "variant_id": variant["id"],
                    "partition_zone_id": "zone-r001-c001",
                    "partition_segment_id": first_segment,
                    "stage": "planning_preview",
                    "validation": {},
                    "file_name": "segment-1.json",
                },
                {
                    "variant_id": variant["id"],
                    "partition_zone_id": "zone-r001-c001",
                    "partition_segment_id": first_segment,
                    "stage": "ready",
                    "validation": {"ok": True},
                    "file_name": "segment-1.json",
                },
            ):
                store.set_planning(project["id"], planning)
            store.set_execution(project["id"], {
                "stage": "pending_confirmation", "file_name": "segment-1.json"
            })
            store.set_execution(project["id"], {
                "stage": "executing", "file_name": "segment-1.json"
            })
            with (
                patch("app.creative_workflow.get_creative_project_store", return_value=store),
                patch("app.creative_workflow.mission_ledger.get", return_value={"state": "completed"}),
                patch.object(robot_state, "mission_file", "segment-1.json"),
                patch.object(robot_state, "mission_stage", "completed"),
                patch.object(robot_state, "mission_running", False),
                patch.object(robot_state, "mission_paused", False),
                patch.object(robot_state, "mission_completed", 100),
                patch.object(robot_state, "mission_total", 100),
                patch.object(robot_state, "mission_error", ""),
            ):
                result = refresh_project_execution(project["id"])

            self.assertEqual(result["execution"]["stage"], "segment_completed")
            self.assertTrue(result["execution"]["next_segment_required"])
            updated = store.get(project["id"])
            self.assertEqual(updated["status"], "ready_for_planning")
            partition = updated["variants"][0]["spatial_partition"]
            self.assertEqual(
                partition["summary"]["completed_execution_segment_count"], 1
            )
            self.assertEqual(
                partition["summary"]["remaining_execution_segment_count"], 1
            )

    def test_recovery_never_allows_automatic_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, project_id = self._project_store(directory)
            with (
                patch("app.creative_workflow.get_creative_project_store", return_value=store),
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

    def test_paused_project_can_resume_after_emergency_is_released(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, project_id = self._project_store(directory)
            store.set_execution(project_id, {
                "stage": "executing", "file_name": "line_v001.json"
            })
            store.set_execution(project_id, {
                "stage": "paused", "file_name": "line_v001.json"
            })
            with (
                patch("app.creative_workflow.get_creative_project_store", return_value=store),
                patch(
                    "app.creative_workflow.ros_adapter.control_mission_action",
                    return_value=True,
                ) as resume,
                patch.object(robot_state, "mission_file", "line_v001.json"),
                patch.object(robot_state, "mission_running", True),
                patch.object(robot_state, "mission_paused", True),
                patch.object(robot_state, "mission_stage", "paused"),
                patch.object(robot_state, "emergency_stopped", False),
                patch.object(robot_state, "control_ready", True),
                patch.object(robot_state, "localization_valid", True),
                patch.object(robot_state, "mission_required_printers", []),
                patch.object(robot_state, "mission_error", "Emergency stop is active"),
                patch.object(robot_state, "oscillation_detected", False),
            ):
                assessment = project_recovery_assessment(project_id)
                self.assertTrue(assessment["recovery"]["can_resume_current_mission"])
                self.assertFalse(assessment["recovery"]["resume_requires_replanning"])
                result = resume_project_execution(project_id)

            self.assertTrue(result["ok"])
            resume.assert_called_once_with("resume", "line_v001.json")

    def test_paused_project_does_not_resume_while_emergency_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, project_id = self._project_store(directory)
            store.set_execution(project_id, {
                "stage": "executing", "file_name": "line_v001.json"
            })
            store.set_execution(project_id, {
                "stage": "paused", "file_name": "line_v001.json"
            })
            with (
                patch("app.creative_workflow.get_creative_project_store", return_value=store),
                patch(
                    "app.creative_workflow.ros_adapter.control_mission_action"
                ) as resume,
                patch.object(robot_state, "mission_file", "line_v001.json"),
                patch.object(robot_state, "mission_running", True),
                patch.object(robot_state, "mission_paused", True),
                patch.object(robot_state, "mission_stage", "paused"),
                patch.object(robot_state, "emergency_stopped", True),
                patch.object(robot_state, "control_ready", False),
                patch.object(robot_state, "localization_valid", True),
                patch.object(robot_state, "mission_required_printers", []),
                patch.object(robot_state, "mission_error", "Emergency stop is active"),
                patch.object(robot_state, "oscillation_detected", False),
            ):
                result = resume_project_execution(project_id)

            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "project_resume_not_ready")
            resume.assert_not_called()

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
            versions = DrawingVersionStore(Path(directory) / "versions.json")
            with (
                patch("app.creative_workflow.get_creative_project_store", return_value=store),
                patch("app.creative_workflow.drawing_versions", versions),
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
            self.assertTrue(result["planning"]["source_revision"]["ok"])

            recovery_file = result["planning"]["file_name"]
            with (
                patch("app.creative_workflow.get_creative_project_store", return_value=store),
                patch.object(robot_state, "mission_file", recovery_file),
                patch.object(robot_state, "mission_stage", "ready"),
                patch.object(
                    robot_state,
                    "mission_validation",
                    {"ok": True, "errors": []},
                ),
                patch.object(robot_state, "mission_summary", {"segment_count": 1}),
                patch.object(robot_state, "mission_quality", {"score": 100}),
                patch.object(robot_state, "mission_error", ""),
            ):
                refreshed = refresh_project_plan(project_id)

            self.assertTrue(refreshed["ok"], refreshed)
            self.assertTrue(refreshed["planning"]["ready_for_confirmation"])
            self.assertIn("recovery", refreshed["planning"])
            self.assertEqual(store.get(project_id)["status"], "planning_ready")

    def test_sync_returns_cancelled_confirmation_to_planning_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, project_id = self._project_store(directory)
            sync = CreativeProjectSynchronizer()
            with (
                patch("app.creative_workflow.get_creative_project_store", return_value=store),
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
                patch("app.creative_workflow.get_creative_project_store", return_value=store),
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
