from __future__ import annotations

import unittest
from unittest.mock import patch

from app.state import robot_state
from app.tooling import (
    OPENAI_TOOLS,
    authorize_emergency_stop,
    authorize_tool,
    tool_catalog,
    validate_tool_arguments,
)


class ToolingSafetyTest(unittest.TestCase):
    def test_all_model_tools_are_strict(self) -> None:
        self.assertTrue(OPENAI_TOOLS)
        for tool in OPENAI_TOOLS:
            self.assertTrue(tool["strict"])
            self.assertFalse(tool["parameters"]["additionalProperties"])
        catalog = tool_catalog()
        self.assertEqual({item["name"] for item in catalog}, {item["name"] for item in OPENAI_TOOLS})
        self.assertTrue(any(item["risk"] == "motion" for item in catalog))

    def test_unknown_and_extra_arguments_are_rejected(self) -> None:
        validated, _ = validate_tool_arguments("missing_tool", {})
        self.assertIsNone(validated)

    def test_creative_project_tools_use_strict_schema(self) -> None:
        validated, error = validate_tool_arguments(
            "create_creative_project",
            {"name": "停车场", "prompt": "画一个 5x3 米矩形", "constraints": {}},
        )
        self.assertEqual(error, "")
        self.assertEqual(validated["name"], "停车场")

        invalid, _ = validate_tool_arguments(
            "update_creative_project",
            {"project_id": "p1", "requirements": {}, "unexpected": True},
        )
        self.assertIsNone(invalid)

        variant, error = validate_tool_arguments("add_design_variant", {
            "project_id": "p1", "name": "A", "rationale": "短路径",
            "geometries": [{
                "id": 1, "type": "line", "layer_id": 1,
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 1000, "y": 0, "z": 0},
            }],
        })
        self.assertEqual(error, "")
        self.assertEqual(variant["geometries"][0]["type"], "line")

        plan, error = validate_tool_arguments(
            "prepare_project_plan", {"project_id": "p1"}
        )
        self.assertEqual(error, "")
        self.assertEqual(plan["project_id"], "p1")

        recovery, error = validate_tool_arguments(
            "assess_project_recovery", {"project_id": "p1"}
        )
        self.assertEqual(error, "")
        self.assertEqual(recovery["project_id"], "p1")

        report, error = validate_tool_arguments(
            "generate_project_report", {"project_id": "p1"}
        )
        self.assertEqual(error, "")
        self.assertEqual(report["project_id"], "p1")
        validated, _ = validate_tool_arguments(
            "drive_robot",
            {"linear": 0.1, "angular": 0.1, "duration_seconds": 0.2, "extra": 1},
        )
        self.assertIsNone(validated)

    def test_motion_limits_are_rejected_before_execution(self) -> None:
        validated, _ = validate_tool_arguments(
            "drive_robot",
            {"linear": 0.21, "angular": 0.0, "duration_seconds": 0.2},
        )
        self.assertIsNone(validated)

    def test_create_drawing_accepts_only_xline_ws3_geometry_schema(self) -> None:
        validated, error = validate_tool_arguments(
            "create_drawing",
            {
                "file_name": "agent_line.json",
                "geometries": [
                    {
                        "id": 1,
                        "type": "line",
                        "layer_id": 1,
                        "start": {"x": 0, "y": 0, "z": 0},
                        "end": {"x": 5000, "y": 0, "z": 0},
                    }
                ],
            },
        )
        self.assertEqual(error, "")
        self.assertEqual(validated["geometries"][0]["type"], "line")

        invalid, _ = validate_tool_arguments(
            "create_drawing",
            {
                "file_name": "unsafe.json",
                "geometries": [{"id": 1, "type": "rectangle", "width": 5}],
            },
        )
        self.assertIsNone(invalid)

        validated, error = validate_tool_arguments(
            "create_drawing",
            {
                "file_name": "agent_text.json",
                "geometries": [
                    {
                        "id": 1,
                        "type": "text",
                        "position": {"x": 0, "y": 0, "z": 0},
                        "content": "停车位 A01",
                        "height": 80,
                    },
                    {
                        "id": 2,
                        "type": "ellipse",
                        "center": {"x": 0, "y": 0, "z": 0},
                        "major_axis": {"x": 1000, "y": 0, "z": 0},
                        "ratio": 0.5,
                        "start_angle": 0,
                        "end_angle": 180,
                    },
                ],
            },
        )
        self.assertEqual(error, "")
        self.assertEqual(validated["geometries"][0]["type"], "text")
        self.assertEqual(validated["geometries"][1]["end_angle"], 180.0)

    def test_drive_requires_owner_ready_runtime_and_released_estop(self) -> None:
        arguments = {"linear": 0.1, "angular": 0.0, "duration_seconds": 0.2}
        with patch.object(robot_state, "control_owner", None):
            self.assertFalse(authorize_tool("drive_robot", arguments, confirmed=True).allowed)
        with (
            patch.object(robot_state, "control_owner", "owner"),
            patch.object(robot_state, "control_ready", True),
            patch.object(robot_state, "emergency_stopped", True),
        ):
            self.assertFalse(authorize_tool("drive_robot", arguments, confirmed=True).allowed)

    def test_mission_requires_fresh_localization(self) -> None:
        arguments = {"running": True, "file_name": "task.json"}
        with (
            patch.object(robot_state, "control_owner", "owner"),
            patch.object(robot_state, "control_ready", True),
            patch.object(robot_state, "mission_nodes_ready", True),
            patch.object(robot_state, "localization_valid", False),
            patch.object(robot_state, "emergency_stopped", False),
        ):
            decision = authorize_tool("set_mission", arguments, confirmed=True)
        self.assertFalse(decision.allowed)
        self.assertIn("定位无效", decision.message)

    def test_prepared_mission_requires_ready_stage_and_matching_file(self) -> None:
        arguments = {"file_name": "agent_path.json"}
        with (
            patch.object(robot_state, "control_owner", "owner"),
            patch.object(robot_state, "control_ready", True),
            patch.object(robot_state, "mission_nodes_ready", True),
            patch.object(robot_state, "localization_valid", True),
            patch.object(robot_state, "emergency_stopped", False),
            patch.object(robot_state, "mission_stage", "planning_preview"),
        ):
            decision = authorize_tool(
                "execute_prepared_mission", arguments, confirmed=True
            )
        self.assertFalse(decision.allowed)
        self.assertIn("尚未完成", decision.message)

        with (
            patch.object(robot_state, "control_owner", "owner"),
            patch.object(robot_state, "control_ready", True),
            patch.object(robot_state, "mission_nodes_ready", True),
            patch.object(robot_state, "localization_valid", True),
            patch.object(robot_state, "emergency_stopped", False),
            patch.object(robot_state, "mission_stage", "ready"),
            patch.object(robot_state, "mission_file", "other.json"),
        ):
            decision = authorize_tool(
                "execute_prepared_mission", arguments, confirmed=True
            )
        self.assertFalse(decision.allowed)
        self.assertIn("不一致", decision.message)

    def test_client_cannot_use_another_clients_control_lease(self) -> None:
        arguments = {"linear": 0.0, "angular": 0.1, "duration_seconds": 0.2}
        with patch.object(robot_state, "control_owner", "owner-a"):
            decision = authorize_tool(
                "drive_robot", arguments, confirmed=True, client_id="owner-b"
            )
        self.assertFalse(decision.allowed)

    def test_relative_mode_blocks_ln150_tool(self) -> None:
        with (
            patch.object(robot_state, "control_owner", "owner"),
            patch.object(robot_state, "ln150_ready", True),
            patch.object(robot_state, "localization_source", "odom_imu_relative"),
        ):
            decision = authorize_tool(
                "control_ln150", {"command_type": 1}, confirmed=True
            )
        self.assertFalse(decision.allowed)

    def test_estop_release_requires_matching_owner_and_ready_runtime(self) -> None:
        with (
            patch.object(robot_state, "control_owner", "owner"),
            patch.object(robot_state, "control_ready", True),
        ):
            self.assertTrue(authorize_emergency_stop(False, "owner").allowed)
            self.assertFalse(authorize_emergency_stop(False, "other").allowed)
        self.assertTrue(authorize_emergency_stop(True, None).allowed)


if __name__ == "__main__":
    unittest.main()
