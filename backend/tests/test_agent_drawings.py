from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app.agent_service import PendingAction, robot_agent
from app.creative_projects import CreativeProjectStore
from app.ros_adapter import ros_adapter
from app.state import robot_state


class AgentDrawingTest(unittest.TestCase):
    def test_deepseek_tool_call_returns_confirmable_json_preview(self) -> None:
        response = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "create_drawing",
                                    "arguments": json.dumps(
                                        {
                                            "file_name": "deepseek_line.json",
                                            "geometries": [
                                                {
                                                    "id": 1,
                                                    "type": "line",
                                                    "layer_id": 1,
                                                    "start": {"x": 0, "y": 0, "z": 0},
                                                    "end": {"x": 3000, "y": 0, "z": 0},
                                                }
                                            ],
                                        }
                                    ),
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        with (
            patch.object(robot_agent, "mode", "deepseek"),
            patch.object(robot_agent, "api_keys", {"deepseek": "test-key"}),
            patch.object(robot_agent, "_deepseek_request", return_value=response),
        ):
            result = robot_agent.chat("生成一条三米直线图纸", [])

        pending = result["pending_action"]
        self.assertEqual(pending["name"], "create_drawing")
        self.assertTrue(pending["preview_paths"])
        self.assertEqual(pending["preview_paths"][0]["points"][-1], [3.0, 0.0])

    def test_rectangle_request_creates_selected_creative_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            with patch("app.agent_service.creative_projects", store):
                result = robot_agent._local_intent("规划一个 5×3 米矩形")

            self.assertIsNotNone(result)
            self.assertIsNone(result["pending_action"])
            projects = store.list()
            self.assertEqual(len(projects), 1)
            self.assertEqual(projects[0]["status"], "ready_for_planning")
            self.assertEqual(projects[0]["requirements"]["dimensions"]["width_m"], 5.0)

    def test_deepseek_design_selection_excludes_legacy_direct_save_tools(self) -> None:
        tools = robot_agent._selected_deepseek_tools("设计一个 5x3 米矩形")
        names = {item["function"]["name"] for item in tools}

        self.assertIn("create_creative_project", names)
        self.assertIn("add_design_variant", names)
        self.assertNotIn("create_drawing", names)
        self.assertNotIn("create_rectangle_drawing", names)

    def test_confirmed_rectangle_is_saved_as_planner_json(self) -> None:
        action = PendingAction(
            name="create_rectangle_drawing",
            arguments={"width_m": 5.0, "height_m": 3.0},
            expires_at=datetime.now() + timedelta(minutes=1),
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"XLINE_CAD_DIR": directory}),
        ):
            result = robot_agent._execute_confirmed(action)
            target = Path(directory, result["file_name"])
            payload = json.loads(target.read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertEqual(target.suffix, ".json")
        self.assertEqual(payload["lines"][0]["type"], "polyline")
        self.assertTrue(payload["lines"][0]["closed"])
        self.assertEqual(payload["lines"][0]["vertices"][2]["x"], 5000.0)
        self.assertEqual(payload["lines"][0]["vertices"][2]["y"], 3000.0)

    def test_confirmed_drawing_requests_preview_planning_as_next_step(self) -> None:
        action = PendingAction(
            name="create_drawing",
            arguments={
                "file_name": "agent_preview.json",
                "geometries": [
                    {
                        "id": 1,
                        "type": "line",
                        "layer_id": 1,
                        "start": {"x": 0, "y": 0, "z": 0},
                        "end": {"x": 1000, "y": 0, "z": 0},
                    }
                ],
            },
            expires_at=datetime.now() + timedelta(minutes=1),
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"XLINE_CAD_DIR": directory}),
        ):
            result = robot_agent._execute_confirmed(action)

        self.assertTrue(result["ok"])
        self.assertEqual(result["next_action"], "plan_preview")
        self.assertTrue(result["drawing_json"]["lines"])
        self.assertTrue(result["preview_paths"])

    def test_virtual_preview_planning_never_starts_motion(self) -> None:
        with (
            patch.object(robot_state, "bridge_mode", "virtual_ros2"),
            patch.object(robot_state, "mission_running", True),
            patch.object(robot_state, "planned_paths", [{"points": [[0, 0], [1, 0]]}]),
        ):
            accepted = ros_adapter.prepare_mission("agent_preview.json")
            self.assertTrue(accepted)
            self.assertFalse(robot_state.mission_running)
            self.assertEqual(robot_state.mission_stage, "ready")
            self.assertEqual(robot_state.mission_file, "agent_preview.json")

    def test_agent_can_start_a_user_saved_drawing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            file_name = "app_drawing_user.json"
            Path(directory, file_name).write_text(
                json.dumps({"lines": []}), encoding="utf-8"
            )
            action = PendingAction(
                name="set_mission",
                arguments={"running": True, "file_name": file_name},
                expires_at=datetime.now() + timedelta(minutes=1),
            )
            with (
                patch.dict(os.environ, {"XLINE_CAD_DIR": directory}),
                patch.object(robot_state, "mission_nodes_ready", True),
                patch.object(robot_state, "control_owner", "test-client"),
                patch.object(robot_state, "control_ready", True),
                patch.object(robot_state, "localization_valid", True),
                patch.object(robot_state, "emergency_stopped", False),
                patch.object(ros_adapter, "control_mission", return_value=True) as control,
            ):
                result = robot_agent._execute_confirmed(action)

            self.assertTrue(result["ok"])
            control.assert_called_once_with(True, file_name)

    def test_agent_drive_matches_installed_vehicle_orientation(self) -> None:
        action = PendingAction(
            name="drive_robot",
            arguments={"linear": 0.1, "angular": 0.2, "duration_seconds": 0.2},
            expires_at=datetime.now() + timedelta(minutes=1),
        )
        with (
            patch.object(robot_state, "control_owner", "test-client"),
            patch.object(robot_state, "control_ready", True),
            patch.object(robot_state, "emergency_stopped", False),
            patch.object(robot_state, "mission_running", False),
            patch.object(
                ros_adapter, "publish_timed_velocity", return_value=True
            ) as publish,
        ):
            result = robot_agent._execute_confirmed(action)

        self.assertTrue(result["ok"])
        # xline_ws3 follows the standard ROS2 convention: positive
        # linear.x is forward and positive angular.z is left.
        publish.assert_called_once_with(0.1, 0.2, 0.2)

    def test_forward_distance_creates_confirmable_drive_action(self) -> None:
        result = robot_agent._local_intent("前进3米")

        self.assertTrue(result["ok"])
        action = result["pending_action"]
        self.assertEqual(action["name"], "drive_robot")
        self.assertEqual(action["arguments"], {
            "linear": 0.1,
            "angular": 0.0,
            "duration_seconds": 30.0,
        })

    def test_long_drive_is_automatically_segmented(self) -> None:
        result = robot_agent._local_intent("向前走4米")

        self.assertTrue(result["ok"])
        action = result["pending_action"]
        self.assertEqual(action["name"], "drive_sequence")
        self.assertEqual(len(action["arguments"]["steps"]), 2)
        self.assertEqual(sum(step["duration_seconds"] for step in action["arguments"]["steps"]), 40.0)

    def test_forward_distance_creates_confirmable_drive_action(self) -> None:
        result = robot_agent._local_intent("\u524d\u8fdb3\u7c73")

        self.assertTrue(result["ok"])
        action = result["pending_action"]
        self.assertEqual(action["name"], "drive_robot")
        self.assertEqual(action["arguments"], {
            "linear": 0.1,
            "angular": 0.0,
            "duration_seconds": 30.0,
        })

    def test_long_drive_unicode_input_is_automatically_segmented(self) -> None:
        result = robot_agent._local_intent("\u5411\u524d\u8d704\u7c73")

        self.assertTrue(result["ok"])
        action = result["pending_action"]
        self.assertEqual(action["name"], "drive_sequence")
        self.assertEqual(len(action["arguments"]["steps"]), 2)

    def test_stop_tool_cancels_agent_motion(self) -> None:
        with patch.object(
            ros_adapter, "stop_agent_motion", return_value=True
        ) as stop_motion:
            result = robot_agent._execute_safe("stop_robot", {})

        self.assertTrue(result["ok"])
        stop_motion.assert_called_once_with("AI stop tool requested")

    def test_timed_agent_motion_automatically_stops(self) -> None:
        with (
            patch.object(robot_state, "control_owner", "test-client"),
            patch.object(robot_state, "control_lease_expires_at", time.time() + 3),
            patch.object(robot_state, "control_ready", True),
            patch.object(robot_state, "emergency_stopped", False),
            patch.object(robot_state, "mission_running", False),
        ):
            started = ros_adapter.publish_timed_velocity(-0.05, 0.0, 0.25)
            self.assertTrue(started)
            self.assertTrue(robot_state.agent_motion_active)
            time.sleep(0.45)
            self.assertFalse(robot_state.agent_motion_active)
            self.assertEqual(robot_state.last_command.get("linear"), 0.0)

        ros_adapter.fail_safe_stop("test cleanup")

    def test_agent_rejects_unknown_drawing(self) -> None:
        action = PendingAction(
            name="set_mission",
            arguments={"running": True, "file_name": "missing.json"},
            expires_at=datetime.now() + timedelta(minutes=1),
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"XLINE_CAD_DIR": directory}),
            patch.object(robot_state, "mission_nodes_ready", True),
            patch.object(robot_state, "control_owner", "test-client"),
            patch.object(robot_state, "control_ready", True),
            patch.object(robot_state, "localization_valid", True),
            patch.object(robot_state, "emergency_stopped", False),
        ):
            result = robot_agent._execute_confirmed(action)

        self.assertFalse(result["ok"])
        self.assertIn("图纸不存在", result["message"])


if __name__ == "__main__":
    unittest.main()
