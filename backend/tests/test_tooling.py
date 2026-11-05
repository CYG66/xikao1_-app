from __future__ import annotations

import unittest
from unittest.mock import patch

from app.state import robot_state
from app.agent_policy import agent_tool_allowed
from app.tooling import (
    OPENAI_TOOLS,
    TOOL_REGISTRY,
    authorize_emergency_stop,
    authorize_tool,
    tool_catalog,
    validate_tool_arguments,
    validate_tool_configuration,
)


class ToolingSafetyTest(unittest.TestCase):
    def test_current_tool_configuration_is_consistent(self) -> None:
        validate_tool_configuration()

    def test_removed_tool_is_rejected_in_each_policy(self) -> None:
        for group in ("base_tools", "advanced_tools", "safe_tools"):
            with self.subTest(group=group), self.assertRaisesRegex(ValueError, "retired_tool"):
                validate_tool_configuration(**{group: {"retired_tool"}})

    def test_confirmation_tool_cannot_be_marked_safe(self) -> None:
        with self.assertRaisesRegex(ValueError, "confirmation-required"):
            validate_tool_configuration(safe_tools={"execute_prepared_mission"})

    def test_draft_cad_tools_use_risk_driven_confirmation(self) -> None:
        catalog = {item["name"]: item for item in tool_catalog()}
        self.assertNotIn("create_drawing", catalog)
        self.assertNotIn("create_drawing", TOOL_REGISTRY)
        self.assertFalse(agent_tool_allowed("create_drawing", "advanced"))
        self.assertNotIn(
            "create_drawing",
            {item["name"] for item in OPENAI_TOOLS},
        )
        for name in ("modify_drawing",):
            self.assertFalse(catalog[name]["requires_confirmation"], name)
        self.assertTrue(TOOL_REGISTRY["apply_cad_candidate_edit"].requires_confirmation)
        self.assertTrue(TOOL_REGISTRY["execute_prepared_mission"].requires_confirmation)

    def test_all_model_tools_are_strict(self) -> None:
        self.assertTrue(OPENAI_TOOLS)
        for tool in OPENAI_TOOLS:
            self.assertTrue(tool["strict"])
            self.assertFalse(tool["parameters"]["additionalProperties"])
        catalog = tool_catalog()
        self.assertEqual({item["name"] for item in catalog}, {item["name"] for item in OPENAI_TOOLS})
        self.assertTrue(any(item["risk"] == "motion" for item in catalog))
        names = {item["name"] for item in catalog}
        self.assertTrue({
            "inspect_drawing", "list_elements", "diff_drawing", "validate_drawing", "snapshot_drawing",
        }.issubset(names))

    def test_list_elements_has_strict_filters(self) -> None:
        validated, error = validate_tool_arguments(
            "list_elements",
            {"geometries": [{
                "id": 1, "type": "line", "layer_id": 1,
                "start": {"x": 0, "y": 0}, "end": {"x": 1, "y": 0},
            }], "instance_ids": [1], "semantic": "外框"},
        )
        self.assertEqual(error, "")
        self.assertEqual(validated["instance_ids"], [1])
        invalid, _ = validate_tool_arguments(
            "list_elements", {"geometries": [], "unknown": True}
        )
        self.assertIsNone(invalid)

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
        self.assertIsNone(variant)
        self.assertIn("add_design_variant", error)

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
            {"linear": 1.01, "angular": 0.0, "duration_seconds": 0.2},
        )
        self.assertIsNone(validated)

    def test_cad_geometry_tools_accept_only_xline_ws3_geometry_schema(self) -> None:
        validated, error = validate_tool_arguments(
            "check_drawing_feasibility",
            {
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
        self.assertEqual(validated["logical_objects"], [])
        self.assertEqual(
            validated["topology"],
            {
                "schema_version": "cad.topology.v1",
                "shared_geometries": [],
                "relations": [],
            },
        )

        invalid, _ = validate_tool_arguments(
            "check_drawing_feasibility",
            {
                "geometries": [{"id": 1, "type": "rectangle", "width": 5}],
            },
        )
        self.assertIsNone(invalid)

        validated, error = validate_tool_arguments(
            "check_drawing_feasibility",
            {
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

    def test_drawing_schema_accepts_shared_logical_object_topology(self) -> None:
        validated, error = validate_tool_arguments(
            "check_drawing_feasibility",
            {
                "geometries": [
                    {"id": 1, "type": "line", "start": {"x": 0, "y": 0},
                     "end": {"x": 0, "y": 5000}},
                    {"id": 2, "type": "line", "start": {"x": 2500, "y": 0},
                     "end": {"x": 2500, "y": 5000}},
                    {"id": 3, "type": "line", "start": {"x": 5000, "y": 0},
                     "end": {"x": 5000, "y": 5000}},
                ],
                "logical_objects": [
                    {"object_id": "parking-space-1", "object_type": "parking_space",
                     "label": "左侧车位", "geometry_refs": [1, 2]},
                    {"object_id": "parking-space-2", "object_type": "parking_space",
                     "label": "右侧车位", "geometry_refs": [2, 3]},
                ],
                "topology": {
                    "shared_geometries": [{
                        "geometry_id": 2,
                        "object_ids": ["parking-space-1", "parking-space-2"],
                        "relation": "shared_boundary",
                    }],
                    "relations": [
                        {"source_object_id": "parking-space-1",
                         "target_object_id": "parking-space-2", "relation": "left_of"},
                        {"source_object_id": "parking-space-1",
                         "target_object_id": "parking-space-2", "relation": "adjacent"},
                    ],
                },
            },
        )

        self.assertEqual(error, "")
        self.assertEqual(validated["logical_objects"][1]["label"], "右侧车位")
        self.assertEqual(
            validated["topology"]["shared_geometries"][0]["geometry_id"], 2
        )

    def test_drawing_schema_rejects_dangling_logical_references(self) -> None:
        geometry = {
            "id": 1, "type": "line", "start": {"x": 0, "y": 0},
            "end": {"x": 1000, "y": 0},
        }
        validated, error = validate_tool_arguments("check_drawing_feasibility", {
            "geometries": [geometry],
            "logical_objects": [{
                "object_id": "object-1", "object_type": "room",
                "label": "房间", "geometry_refs": [9],
            }],
        })
        self.assertIsNone(validated)
        self.assertIn("references missing geometries", error)

        validated, error = validate_tool_arguments("check_drawing_feasibility", {
            "geometries": [geometry],
            "logical_objects": [{
                "object_id": "object-1", "object_type": "room",
                "label": "房间", "geometry_refs": [1],
            }],
            "topology": {"shared_geometries": [], "relations": [{
                "source_object_id": "object-1",
                "target_object_id": "missing-object",
                "relation": "adjacent",
            }]},
        })
        self.assertIsNone(validated)
        self.assertIn("references missing objects", error)

        validated, error = validate_tool_arguments("check_drawing_feasibility", {
            "geometries": [geometry],
            "logical_objects": [
                {"object_id": "object-1", "object_type": "room",
                 "label": "房间1", "geometry_refs": [1]},
                {"object_id": "object-2", "object_type": "room",
                 "label": "房间2", "geometry_refs": [1]},
            ],
        })
        self.assertIsNone(validated)
        self.assertIn("must be declared in topology", error)

    def test_modify_drawing_requires_typed_target_and_patch(self) -> None:
        validated, error = validate_tool_arguments(
            "modify_drawing",
            {
                "source_file_name": "court.json",
                "target": {
                    "scope": "geometry",
                    "geometry_ids": [3],
                    "instance_ids": [],
                },
                "operations": [{
                    "op": "update",
                    "geometry_id": 3,
                    "patch": {"radius": 3600},
                }],
            },
        )

        self.assertEqual(error, "")
        self.assertEqual(validated["target"]["geometry_ids"], [3])
        self.assertEqual(validated["operations"][0]["geometry_id"], 3)
        self.assertEqual(validated["operations"][0]["patch"]["radius"], 3600.0)

        missing_target, _ = validate_tool_arguments(
            "modify_drawing",
            {
                "source_file_name": "court.json",
                "operations": [{
                    "op": "update", "geometry_id": 3, "patch": {"radius": 3600}
                }],
            },
        )
        missing_id, _ = validate_tool_arguments(
            "modify_drawing",
            {
                "source_file_name": "court.json",
                "target": {"scope": "geometry", "geometry_ids": [3]},
                "operations": [{"op": "update", "patch": {"radius": 3600}}],
            },
        )
        identity_patch, _ = validate_tool_arguments(
            "modify_drawing",
            {
                "source_file_name": "court.json",
                "target": {"scope": "geometry", "geometry_ids": [3]},
                "operations": [{
                    "op": "update", "geometry_id": 3, "patch": {"id": 4}
                }],
            },
        )

        self.assertIsNone(missing_target)
        self.assertIsNone(missing_id)
        self.assertIsNone(identity_patch)

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

    def test_estop_release_requires_matching_owner_ros_and_can(self) -> None:
        with (
            patch.object(robot_state, "control_owner", "owner"),
            patch.object(robot_state, "ros_available", True),
            patch.object(robot_state, "drive_device_connected", True),
            patch.object(robot_state, "control_ready", False),
        ):
            self.assertTrue(authorize_emergency_stop(False, "owner").allowed)
            self.assertFalse(authorize_emergency_stop(False, "other").allowed)
            with patch.object(robot_state, "ros_available", False):
                self.assertFalse(authorize_emergency_stop(False, "owner").allowed)
            with patch.object(robot_state, "drive_device_connected", False):
                self.assertFalse(authorize_emergency_stop(False, "owner").allowed)
        self.assertTrue(authorize_emergency_stop(True, None).allowed)


if __name__ == "__main__":
    unittest.main()
