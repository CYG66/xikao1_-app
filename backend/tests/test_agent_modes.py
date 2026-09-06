from __future__ import annotations

import unittest

from app.agent_service import RobotAgentService


class AgentModeRoutingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = object.__new__(RobotAgentService)

    def test_chat_mode_does_not_run_local_design_skill(self) -> None:
        result = self.service._local_intent(
            "控制小车按半径0.5米的圆走",
            allow_design=False,
        )
        self.assertIsNone(result)

    def test_chat_mode_still_accepts_direct_stop(self) -> None:
        original = self.service._execute_safe
        self.service._execute_safe = lambda name, arguments: {
            "ok": True,
            "message": f"{name} accepted",
        }
        try:
            result = self.service._local_intent("停止", allow_design=False)
        finally:
            self.service._execute_safe = original
        self.assertEqual(result["message"], "stop_robot accepted")

    def test_chat_movement_json_is_pending_and_rejects_ink_fields(self) -> None:
        self.service._register_pending = lambda name, arguments: {
            "name": name,
            "arguments": arguments,
        }
        result = self.service._chat_json_movement(
            '{"schema_version":"1.0","task":"movement_command",'
            '"steps":[{"linear":0.03,"angular":0.0,"duration_seconds":0.5}]}'
        )
        self.assertEqual(result["pending_action"]["name"], "drive_robot")
        rejected = self.service._chat_json_movement(
            '{"schema_version":"1.0","task":"movement_command",'
            '"printer_name":"center","steps":[]}'
        )
        self.assertIn("不能包含喷墨", rejected["message"])

    def test_chat_square_request_becomes_motion_demo_not_drawing(self) -> None:
        self.service._register_pending = lambda name, arguments: {
            "name": name,
            "arguments": arguments,
        }
        result = self.service._local_intent(
            "从小车自身位置出发，走一个边长为0.5米的正方形",
            allow_design=False,
        )
        self.assertEqual(result["pending_action"]["name"], "drive_sequence")
        self.assertEqual(len(result["pending_action"]["arguments"]["steps"]), 8)
        self.assertIn("开环演示", result["message"])

    def test_mode_names_map_to_base_and_advanced(self) -> None:
        self.assertEqual(self.service.normalize_agent_mode("chat"), "base")
        self.assertEqual(self.service.normalize_agent_mode("base"), "base")
        self.assertEqual(self.service.normalize_agent_mode("work"), "advanced")
        self.assertEqual(self.service.normalize_agent_mode("advanced"), "advanced")

    def test_base_mode_has_no_project_database_tools(self) -> None:
        tools = self.service._selected_deepseek_tools(
            "设计一个篮球场并规划执行", mode="base"
        )
        names = {item["function"]["name"] for item in tools}
        self.assertNotIn("create_creative_project", names)
        self.assertNotIn("prepare_project_plan", names)
        self.assertNotIn("generate_project_report", names)

    def test_base_sequence_preserves_commands_before_and_after_turn(self) -> None:
        self.service._register_pending = lambda name, arguments: {
            "name": name,
            "arguments": arguments,
        }
        result = self.service._local_intent(
            "前进1米后左转90度再前进1米",
            allow_design=False,
        )
        self.assertEqual(result["pending_action"]["name"], "drive_sequence")
        steps = result["pending_action"]["arguments"]["steps"]
        self.assertEqual(len(steps), 3)
        self.assertEqual(steps[0]["linear"], 0.1)
        self.assertEqual(steps[1]["angular"], 0.4)
        self.assertEqual(steps[2]["linear"], 0.1)

    def test_motion_pending_action_contains_ros_motion_json(self) -> None:
        self.service.pending = {}
        result = self.service._register_pending(
            "drive_sequence",
            {"steps": [{"linear": 0.1, "angular": 0.0, "duration_seconds": 1.0}]},
        )
        self.assertEqual(result["motion_json"]["task"], "movement_command")
        self.assertEqual(len(result["motion_json"]["steps"]), 1)


if __name__ == "__main__":
    unittest.main()
