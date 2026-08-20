from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.drawing_store import available_drawings, preview_paths, resolve_drawing
from app.drawing_versions import DrawingVersionStore
from app.state import RobotState
from app.schemas import VelocityCommand
from pydantic import ValidationError


class DrawingStoreTest(unittest.TestCase):
    def test_version_rollback_creates_new_version_and_keeps_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = DrawingVersionStore(root / "versions.json")
            first = store.save(
                root, "court.json",
                {"creative_project_id": "project-1", "lines": [{"id": 1}]},
                "test",
            )
            restored = store.restore(first["file_name"], root, "project-1")
            self.assertIsNotNone(restored)
            self.assertNotEqual(restored["file_name"], first["file_name"])
            self.assertEqual(restored["version"], 2)
            self.assertEqual(len(store.list(first["drawing_id"])), 2)
            self.assertIsNone(store.restore(first["file_name"], root, "other-project"))

    def test_velocity_schema_matches_xline_ws3_hard_limits(self) -> None:
        command = VelocityCommand(
            client_id="test-client", linear=0.20, angular=0.40
        )
        self.assertEqual(command.linear, 0.20)
        self.assertEqual(command.angular, 0.40)
        with self.assertRaises(ValidationError):
            VelocityCommand(client_id="test-client", linear=0.21, angular=0.0)
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
        self.assertEqual(limits["max_linear_mps"], 0.20)
        self.assertEqual(limits["max_angular_rad_s"], 0.40)
        self.assertEqual(limits["max_motor_rpm"], 30.0)
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
