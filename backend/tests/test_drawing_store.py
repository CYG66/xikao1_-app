from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.drawing_store import (
    geometry_preview_paths,
    available_drawings,
    build_path_preview_contract,
    preview_paths,
    resolve_drawing,
)
from app.drawing_versions import DrawingVersionStore
from app.routers.drawings import drawing_preview, rollback_drawing_version
from app.state import RobotState, robot_state
from app.schemas import DrawingVersionRollbackRequest, VelocityCommand
from pydantic import ValidationError


def test_geometry_preview_paths_preserve_stable_geometry_id() -> None:
    paths = geometry_preview_paths({
        "lines": [{
            "id": 7,
            "type": "line",
            "start": {"x": 0, "y": 0},
            "end": {"x": 1000, "y": 0},
        }]
    })

    assert paths[0]["geometry_id"] == 7
    assert paths[0]["points"] == [[0.0, 0.0], [1.0, 0.0]]
    assert paths[0]["geometry_type"] == "line"
    assert paths[0]["bounds"] == {
        "min_x": 0.0, "min_y": 0.0, "max_x": 1.0, "max_y": 0.0,
    }


def test_geometry_preview_paths_preserve_selection_group_metadata() -> None:
    paths = geometry_preview_paths({
        "lines": [{
            "id": 7,
            "type": "line",
            "start": {"x": 0, "y": 0},
            "end": {"x": 1000, "y": 0},
            "template_instance": 3,
            "template_type": "basketball",
            "logical_object_id": "basketball-3",
            "object_ids": ["basketball-3", "shared-boundary"],
            "label": "篮球场边线",
        }]
    })

    assert paths[0]["template_instance"] == 3
    assert paths[0]["template_type"] == "basketball"
    assert paths[0]["logical_object_id"] == "basketball-3"
    assert paths[0]["object_ids"] == ["basketball-3", "shared-boundary"]
    assert paths[0]["label"] == "篮球场边线"


def test_curve_previews_are_visible_and_identity_preserving() -> None:
    paths = geometry_preview_paths({
        "lines": [
            {"id": 11, "type": "circle", "center": {"x": 0, "y": 0}, "radius": 1000},
            {
                "id": 12,
                "type": "arc",
                "center": {"x": 0, "y": 0},
                "radius": 2000,
                "start_angle": 0,
                "end_angle": 90,
            },
            {
                "id": 13,
                "type": "ellipse",
                "center": {"x": 0, "y": 0},
                "major_axis": {"x": 3000, "y": 0},
                "ratio": 0.5,
            },
        ]
    })

    assert [item["geometry_id"] for item in paths] == [11, 12, 13]
    assert [item["geometry_type"] for item in paths] == ["circle", "arc", "ellipse"]
    assert all(len(item["points"]) >= 9 for item in paths)
    assert all(item["bounds"]["max_x"] > item["bounds"]["min_x"] for item in paths)
    assert all(item["bounds"]["max_y"] > item["bounds"]["min_y"] for item in paths)


class DrawingStoreTest(unittest.TestCase):
    def test_path_preview_contract_separates_printing_and_ros_transition(self) -> None:
        payload = {"lines": [{
            "id": 1, "type": "line", "role": "printing",
            "start": {"x": 0, "y": 0},
            "end": {"x": 1000, "y": 0},
        }]}

        contract = build_path_preview_contract(
            payload, file_name="drawing_v001.json", source_file_name="drawing.json"
        )

        self.assertEqual(contract["contract_version"], "path-preview-1.0")
        self.assertEqual(contract["status"], "preview_ready")
        self.assertEqual(contract["file_name"], "drawing_v001.json")
        self.assertEqual(len(contract["printing_paths"]), 1)
        self.assertEqual(contract["transition_paths"], [])
        self.assertEqual(contract["transition_status"], "pending_ros2_replan")
        self.assertTrue(contract["requires_ros2_replan"])
        self.assertFalse(contract["execution_allowed"])
    def test_builtin_drawing_preview_returns_paths_without_server_error(self) -> None:
        result = drawing_preview("test_pattern.json")

        self.assertTrue(result["ok"])
        self.assertEqual(result["file_name"], "test_pattern.json")
        self.assertEqual(len(result["planned_paths"]), 3)
        self.assertEqual(result["path_metadata"], [])

    def test_version_rollback_creates_new_version_and_keeps_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = DrawingVersionStore(root / "versions.json")
            first_payload = {
                "creative_project_id": "project-1",
                "lines": [{
                    "id": 1,
                    "type": "line",
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 1000, "y": 0},
                }],
            }
            first = store.save(
                root, "court.json",
                first_payload,
                "test",
            )
            second_payload = json.loads(json.dumps(first_payload))
            second_payload["lines"][0]["end"]["x"] = 2000
            store.save(root, "court.json", second_payload, "test")
            restored = store.restore(first["file_name"], root, "project-1")
            self.assertIsNotNone(restored)
            self.assertNotEqual(restored["file_name"], first["file_name"])
            self.assertEqual(restored["version"], 3)
            self.assertEqual(restored["rollback_source_file_name"], first["file_name"])
            self.assertEqual(restored["geometry_diff"]["counts"]["modified"], 1)
            self.assertTrue(restored["path_impact"]["requires_replan"])
            self.assertEqual(len(store.list(first["drawing_id"])), 3)
            self.assertIsNone(store.restore(first["file_name"], root, "other-project"))

    def test_version_rollback_is_blocked_while_mission_runs(self) -> None:
        with patch.object(robot_state, "mission_running", True):
            result = rollback_drawing_version(
                "court_v001.json", DrawingVersionRollbackRequest()
            )

        self.assertFalse(result["ok"])
        self.assertIn("任务执行中", result["message"])

    def test_version_rollback_validates_and_verifies_geometry_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = DrawingVersionStore(root / "versions.json")
            payload = {
                "lines": [{
                    "id": 1, "type": "line",
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 1000, "y": 0},
                }],
            }
            first = store.save(root, "verified.json", payload, "test")
            with (
                patch("app.routers.drawings.drawing_versions", store),
                patch("app.routers.drawings._cad_directory", return_value=root),
                patch.object(robot_state, "mission_running", False),
            ):
                result = rollback_drawing_version(
                    first["file_name"], DrawingVersionRollbackRequest()
                )
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["rollback_verification"]["verified"])
        self.assertEqual(result["rollback_verification"]["status"], "success")

    def test_velocity_schema_matches_app_control_limits(self) -> None:
        command = VelocityCommand(
            client_id="test-client", linear=1.0, angular=0.40
        )
        self.assertEqual(command.linear, 1.0)
        self.assertEqual(command.angular, 0.40)
        with self.assertRaises(ValidationError):
            VelocityCommand(client_id="test-client", linear=1.01, angular=0.0)
        with self.assertRaises(ValidationError):
            VelocityCommand(client_id="test-client", linear=0.0, angular=0.41)

    def test_snapshot_exposes_real_robot_capability_flags(self) -> None:
        state = RobotState(
            localization_valid=True,
            ln150_ready=False,
            printer_ready=True,
        )

        snapshot = state.snapshot()

        self.assertTrue(snapshot["localization_valid"])
        self.assertFalse(snapshot["ln150_ready"])
        self.assertTrue(snapshot["printer_ready"])
        self.assertEqual(snapshot["schema_version"], "1.0")
        self.assertTrue(snapshot["vehicle"]["localization"]["valid"])
        self.assertFalse(snapshot["vehicle"]["capabilities"]["path_execution"])
        limits = snapshot["vehicle"]["motion_limits"]
        self.assertEqual(limits["max_linear_mps"], 1.0)
        self.assertEqual(limits["default_linear_mps"], 0.1)
        self.assertEqual(limits["max_angular_rad_s"], 0.40)
        self.assertEqual(limits["max_motor_rpm"], 500.0)
        self.assertEqual(limits["cmd_vel_timeout_sec"], 0.5)
        self.assertEqual(limits["limit_source"], "app_control_policy")
        self.assertFalse(limits["runtime_fixed_velocity_clamp"])
        self.assertEqual(limits["wheel_radius_m"], 0.09115)
        self.assertEqual(limits["wheel_base_m"], 0.255)

    def test_previews_every_geometry_supported_by_planner(self) -> None:
        payload = {
            "lines": [
                {"type": "line", "start": {"x": 0, "y": 0}, "end": {"x": 1000, "y": 0}},
                {
                    "type": "polyline",
                    "closed": True,
                    "vertices": [
                        {"x": 0, "y": 0},
                        {"x": 1000, "y": 0},
                        {"x": 1000, "y": 1000},
                    ],
                },
                {"type": "circle", "center": {"x": 0, "y": 0}, "radius": 1000},
                {
                    "type": "arc",
                    "center": {"x": 0, "y": 0},
                    "radius": 1000,
                    "start_angle": 0,
                    "end_angle": 90,
                },
                {
                    "type": "ellipse",
                    "center": {"x": 0, "y": 0},
                    "major_axis": {"x": 2000, "y": 0},
                    "ratio": 0.5,
                },
                {
                    "type": "spline",
                    "degree": 2,
                    "control_points": [
                        {"x": 0, "y": 0},
                        {"x": 500, "y": 1000},
                        {"x": 1000, "y": 0},
                    ],
                },
                {
                    "type": "text",
                    "position": {"x": 1000, "y": 2000},
                    "content": "XLine",
                    "height": 100,
                    "rotation": 0,
                },
            ]
        }

        paths = preview_paths(payload)

        self.assertEqual(len(paths), 7)
        self.assertEqual(paths[0], [[0.0, 0.0], [1.0, 0.0]])
        self.assertEqual(paths[1][0], paths[1][-1])
        self.assertGreater(len(paths[2]), 32)
        self.assertAlmostEqual(paths[3][-1][0], 0.0, places=6)
        self.assertAlmostEqual(paths[3][-1][1], 1.0, places=6)
        self.assertAlmostEqual(max(point[0] for point in paths[4]), 2.0, places=6)
        self.assertGreater(len(paths[5]), 32)
        self.assertEqual(paths[5][0], [0.0, 0.0])
        self.assertEqual(paths[5][-1], [1.0, 0.0])
        self.assertEqual(paths[6][0], [1.0, 2.0])
        self.assertGreater(paths[6][1][0], paths[6][0][0])

    def test_lists_and_resolves_user_saved_drawings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app_drawing_123.json").write_text(
                json.dumps({"lines": []}), encoding="utf-8"
            )
            (root / "notes.txt").write_text("ignored", encoding="utf-8")
            with patch.dict(os.environ, {"XLINE_CAD_DIR": directory}):
                self.assertEqual(available_drawings(), ["app_drawing_123.json"])
                self.assertEqual(
                    resolve_drawing("app_drawing_123.json"),
                    root / "app_drawing_123.json",
                )
                self.assertIsNone(resolve_drawing("../app_drawing_123.json"))
                self.assertIsNone(resolve_drawing("missing.json"))


if __name__ == "__main__":
    unittest.main()
