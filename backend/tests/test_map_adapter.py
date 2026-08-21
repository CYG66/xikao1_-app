from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.ros_adapter import (
    RobotBackendNode,
    classify_planned_segment,
    planner_cad_path,
    planned_ink_fingerprint,
)
from app.state import robot_state


class PlannerCadPathTest(unittest.TestCase):
    def test_planner_uses_absolute_xline_cad_path(self) -> None:
        with patch.dict(os.environ, {"XLINE_CAD_DIR": "/tmp/xline-cad"}):
            path = planner_cad_path("circle_0500.json")

        self.assertEqual(path, str(Path("/tmp/xline-cad/circle_0500.json").resolve()))


def marker(
    marker_type: int,
    marker_id: int,
    *,
    namespace: str = "path_lines",
    blue: float = 1.0,
    text: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        action=0,
        type=marker_type,
        id=marker_id,
        ns=namespace,
        text=text,
        header=SimpleNamespace(frame_id="map"),
        pose=SimpleNamespace(position=SimpleNamespace(x=1.0, y=2.0)),
        scale=SimpleNamespace(x=0.03, z=0.3),
        color=SimpleNamespace(r=1.0 if blue < 0.8 else 0.0, g=0.5, b=blue, a=1.0),
        points=[SimpleNamespace(x=0.0, y=0.0), SimpleNamespace(x=1.0, y=1.0)],
    )


class MapAdapterTest(unittest.TestCase):
    def test_xline_ws3_segment_schema_distinguishes_travel_and_printing(self) -> None:
        printing = {
            "type": "line",
            "layer_id": 1,
            "work": True,
            "start": {"x": 0, "y": 0},
            "end": {"x": 1000, "y": 0},
            "ink": {"enabled": True, "mode": "solid", "printer": "center"},
        }
        travel = {
            "type": "line",
            "layer_id": 1_000_000,
            "work": False,
            "ink": {"enabled": False, "mode": "solid", "printer": "center"},
        }
        self.assertEqual(classify_planned_segment(printing), "printing")
        self.assertEqual(classify_planned_segment(travel), "travel")
        self.assertIsNone(planned_ink_fingerprint(travel))

        reversed_printing = {
            **printing,
            "id": 99,
            "start": printing["end"],
            "end": printing["start"],
        }
        self.assertEqual(
            planned_ink_fingerprint(printing),
            planned_ink_fingerprint(reversed_printing),
        )

    def test_null_ink_on_travel_segment_does_not_raise(self) -> None:
        travel = {
            "type": "line",
            "layer_id": 1_000_000,
            "work": False,
            "ink": None,
        }
        self.assertIsNone(planned_ink_fingerprint(travel))

    def test_xline_ws3_paths_and_text_markers_are_preserved(self) -> None:
        message = SimpleNamespace(
            markers=[
                marker(4, 1, blue=1.0),
                marker(4, 2, blue=0.0),
                marker(9, 3, namespace="path_texts", text="A-01"),
            ]
        )

        RobotBackendNode._handle_paths(object(), message)

        self.assertEqual(
            [item["route_type"] for item in robot_state.planned_paths],
            ["drawing", "transition"],
        )
        self.assertEqual(robot_state.path_annotations[0]["text"], "A-01")
        self.assertEqual(robot_state.path_annotations[0]["frame_id"], "map")
        self.assertGreater(robot_state.last_paths_update_at, 0)


if __name__ == "__main__":
    unittest.main()
