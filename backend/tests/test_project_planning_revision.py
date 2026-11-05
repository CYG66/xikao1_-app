from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.creative_projects import CreativeProjectStore
from app.drawing_versions import DrawingVersionStore
from app.cad_revision import verify_variant_revision_for_planning
from app.creative_workflow import (
    ensure_project_plan_ready,
    prepare_project_plan,
    refresh_project_plan,
)
from app.state import robot_state


ACCEPTED = {
    "status": "passed", "review_required": False,
    "authority": "backend_measured_geometry", "source": "test_geometry_acceptance",
}


class ProjectPlanningRevisionTest(unittest.TestCase):
    def test_ready_project_restores_its_plan_when_global_preview_was_replaced(self) -> None:
        geometry = {
            "id": 1, "type": "line", "layer_id": 1,
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 1000, "y": 0, "z": 0},
        }
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create("线段", "创建线段")
            variant = store.add_variant(
                project["id"], "方案 A", [geometry], "初始方案",
                {"score": 90, "feasibility": {"ok": True, "errors": []}},
                [[[0, 0], [1, 0]]], acceptance_summary=ACCEPTED,
            )
            store.select_variant(project["id"], variant["id"])
            selected = store.get(project["id"])["variants"][0]
            source = verify_variant_revision_for_planning(selected)
            Path(directory, "line_v001.json").write_text("{}", encoding="utf-8")
            ready_planning = {
                "variant_id": variant["id"],
                "file_name": "line_v001.json",
                "source_revision": source,
                "stage": "ready",
                "validation": {"ok": True},
                "ready_for_confirmation": True,
            }
            store.set_planning(project["id"], {**ready_planning, "stage": "planning_preview"})
            store.set_planning(project["id"], ready_planning)

            def restore(file_name: str) -> bool:
                robot_state.mission_file = file_name
                robot_state.mission_stage = "ready"
                robot_state.mission_validation = {"ok": True, "errors": []}
                robot_state.mission_summary = {"segment_count": 1}
                robot_state.mission_quality = {"score": 100}
                robot_state.mission_error = ""
                return True

            with (
                patch("app.creative_workflow.get_creative_project_store", return_value=store),
                patch("app.creative_workflow.ros_adapter.prepare_mission", side_effect=restore) as submit,
                patch.dict(os.environ, {"XLINE_CAD_DIR": directory}),
                patch.object(robot_state, "mission_file", "another_project.json"),
                patch.object(robot_state, "mission_running", False),
            ):
                result = ensure_project_plan_ready(project["id"])

            self.assertTrue(result["ok"], result)
            self.assertEqual(result["code"], "project_plan_restored")
            self.assertTrue(result["planning"]["ready_for_confirmation"])
            submit.assert_called_once_with("line_v001.json")

    def test_ready_project_does_not_restore_a_stale_candidate_revision(self) -> None:
        geometry = {
            "id": 1, "type": "line", "layer_id": 1,
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 1000, "y": 0, "z": 0},
        }
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create("线段", "创建线段")
            variant = store.add_variant(
                project["id"], "方案 A", [geometry], "初始方案",
                {"score": 90, "feasibility": {"ok": True, "errors": []}},
                [[[0, 0], [1, 0]]], acceptance_summary=ACCEPTED,
            )
            store.select_variant(project["id"], variant["id"])
            Path(directory, "line_v001.json").write_text("{}", encoding="utf-8")
            stale_planning = {
                "variant_id": variant["id"],
                "file_name": "line_v001.json",
                "source_revision": {"ok": True, "sha256": "stale"},
                "stage": "ready",
                "validation": {"ok": True},
                "ready_for_confirmation": True,
            }
            store.set_planning(project["id"], {**stale_planning, "stage": "planning_preview"})
            store.set_planning(project["id"], stale_planning)
            with (
                patch("app.creative_workflow.get_creative_project_store", return_value=store),
                patch("app.creative_workflow.ros_adapter.prepare_mission") as submit,
                patch.dict(os.environ, {"XLINE_CAD_DIR": directory}),
                patch.object(robot_state, "mission_file", "another_project.json"),
                patch.object(robot_state, "mission_running", False),
            ):
                result = ensure_project_plan_ready(project["id"])

            self.assertFalse(result["ok"])
            self.assertEqual(
                result["planning"]["validation"]["reason"],
                "candidate_revision_mismatch",
            )
            submit.assert_not_called()

    def test_large_project_submits_one_partition_zone_instead_of_full_drawing(self) -> None:
        geometry = {
            "id": 1,
            "type": "polyline",
            "layer_id": 1,
            "vertices": [
                {"x": -200000, "y": -200000, "z": 0},
                {"x": 200000, "y": -200000, "z": 0},
                {"x": 200000, "y": 200000, "z": 0},
                {"x": -200000, "y": 200000, "z": 0},
            ],
            "closed": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create("大型场地", "创建400米见方的划线项目")
            variant = store.add_variant(
                project["id"],
                "大型方案",
                [geometry],
                "完整总图",
                {
                    "score": 90,
                    "feasibility": {"ok": True, "errors": []},
                    "project_scale": {
                        "requires_partitioning": True,
                        "width_m": 400.0,
                        "height_m": 400.0,
                        "suggested_rows": 8,
                        "suggested_columns": 8,
                        "suggested_zone_count": 64,
                    },
                },
                [[[-200, -200], [200, -200], [200, 200], [-200, 200]]],
                acceptance_summary=ACCEPTED,
            )
            self.assertIsNotNone(store.select_variant(project["id"], variant["id"]))
            saved_payload = {}
            versions = DrawingVersionStore(Path(directory) / "versions.json")

            with (
                patch("app.creative_workflow.get_creative_project_store", return_value=store),
                patch("app.creative_workflow.resolve_drawing", return_value=None),
                patch("app.creative_workflow.drawing_versions", versions),
                patch("app.creative_workflow.cad_directory", return_value=Path(directory) / "cad"),
                patch(
                    "app.creative_workflow.ros_adapter.prepare_mission",
                    return_value=True,
                ) as submit,
                patch.object(robot_state, "mission_stage", "planning_preview"),
            ):
                result = prepare_project_plan(project["id"])
            saved_payload.update(versions.payload(result["planning"]["file_name"]) or {})

            self.assertTrue(result["ok"], result)
            self.assertEqual(result["planning"]["partition_zone_id"], "zone-r001-c001")
            self.assertEqual(
                result["planning"]["partition_segment_id"],
                "zone-r001-c001-segment-0001",
            )
            self.assertEqual(
                result["planning"]["local_frame"]["parent_frame_id"], "map"
            )
            self.assertEqual(
                saved_payload["coordinate_contract"]["canonical_space"],
                "zone_local_mm",
            )
            self.assertEqual(
                saved_payload["coordinate_contract"]["planner_input_space"],
                "map_mm",
            )
            self.assertTrue(saved_payload["coordinate_contract"]["local_lines"])
            self.assertIn("zone-r001-c001", result["planning"]["file_name"])
            self.assertEqual(submit.call_count, 1)
            updated = store.get(project["id"])
            selected = updated["variants"][0]
            partition = selected["spatial_partition"]
            self.assertEqual(partition["schema"], "cad.spatial-partition.v1")
            self.assertTrue(partition["coverage"]["verified"])
            self.assertEqual(
                next(
                    zone for zone in partition["zones"]
                    if zone["id"] == "zone-r001-c001"
                )["status"],
                "planning",
            )

    def test_plan_binds_exact_candidate_snapshot_and_rejects_stale_binding(self) -> None:
        geometry = {
            "id": 1, "type": "line", "layer_id": 1,
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 1000, "y": 0, "z": 0},
        }
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create("线段", "创建线段")
            variant = store.add_variant(
                project["id"], "方案 A", [geometry], "初始方案",
                {"score": 90, "feasibility": {"ok": True, "errors": []}},
                [[[0, 0], [1, 0]]], acceptance_summary=ACCEPTED,
            )
            self.assertIsNotNone(store.select_variant(project["id"], variant["id"]))
            saved_payload = {}
            versions = DrawingVersionStore(Path(directory) / "versions.json")

            with (
                patch("app.creative_workflow.get_creative_project_store", return_value=store),
                patch("app.creative_workflow.resolve_drawing", return_value=None),
                patch("app.creative_workflow.drawing_versions", versions),
                patch("app.creative_workflow.cad_directory", return_value=Path(directory) / "cad"),
                patch("app.creative_workflow.layer_drawing_paths", return_value={"lines": [geometry]}),
                patch("app.creative_workflow.ros_adapter.prepare_mission", return_value=True),
                patch.object(robot_state, "mission_stage", "planning_preview"),
            ):
                planned = prepare_project_plan(project["id"])
            saved_payload.update(versions.payload(planned["planning"]["file_name"]) or {})

            self.assertTrue(planned["ok"])
            source = planned["planning"]["source_revision"]
            self.assertTrue(source["ok"])
            self.assertEqual(source["sha256"], saved_payload["cad_source_revision"]["sha256"])

            stale = dict(planned["planning"])
            stale["source_revision"] = {**source, "sha256": "stale"}
            store.set_planning(project["id"], stale)
            with patch("app.creative_workflow.get_creative_project_store", return_value=store):
                refreshed = refresh_project_plan(project["id"])

            self.assertFalse(refreshed["ok"])
            self.assertEqual(
                refreshed["planning"]["validation"]["reason"],
                "candidate_revision_mismatch",
            )
            self.assertEqual(store.get(project["id"])["status"], "planning_failed")


if __name__ == "__main__":
    unittest.main()
