from __future__ import annotations

import unittest
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from app.agent_service import PendingAction, RobotAgentService
from app.request_context import agent_user_scope


class AgentModeRoutingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = object.__new__(RobotAgentService)
        self.service.pending = {}

    def test_unconfigured_provider_message_is_not_openai_specific(self) -> None:
        service = object.__new__(RobotAgentService)
        service.pending = {}
        service.mode = "deepseek"
        service.api_keys = {}
        route = {"name": "general_question", "decision_source": "fallback"}
        with (
            patch.object(service, "_structured_cad_edit_fallback", return_value=route),
            patch.object(service, "_apply_incremental_candidate_chain", return_value=None),
            patch.object(service, "_apply_constrained_candidate_addition", return_value=None),
            patch.object(service, "_apply_incremental_candidate_edit", return_value=None),
            patch.object(service, "_apply_drawing_layout_followup", return_value=None),
            patch.object(service, "_deterministic_design_confirmation", return_value=None),
        ):
            result = service.chat("你好", [], mode="advanced", route=route)

        self.assertFalse(result["ok"])
        self.assertFalse(result["configured"])
        self.assertIn("当前 AI 服务", result["message"])
        self.assertNotIn("OPENAI_API_KEY", result["message"])

    def test_advanced_cad_pipeline_keeps_create_out_of_edit_handlers(self) -> None:
        service = object.__new__(RobotAgentService)
        route = {
            "name": "drawing_design",
            "operation": "create",
            "decision_source": "model",
        }
        constructed = {"ok": True, "message": "constructed", "preview_paths": []}
        with (
            patch.object(service, "_structured_cad_edit_fallback", return_value=route),
            patch.object(service, "_apply_incremental_candidate_chain") as chain,
            patch.object(service, "_apply_constrained_candidate_addition") as constrained,
            patch.object(service, "_apply_incremental_candidate_edit") as edit,
            patch.object(service, "_apply_relative_template_addition") as relative,
            patch.object(service, "_apply_drawing_layout_followup") as layout,
            patch.object(service, "_formal_cad_construction", return_value=constructed),
            patch.object(service, "_deterministic_design_confirmation") as template,
        ):
            resolved_route, result = service._run_advanced_cad_pipeline(
                "绘制半圆拱门", [], route, mode="advanced"
            )

        self.assertIs(resolved_route, route)
        self.assertIs(result, constructed)
        chain.assert_not_called()
        constrained.assert_not_called()
        edit.assert_not_called()
        relative.assert_not_called()
        layout.assert_not_called()
        template.assert_not_called()

    def test_advanced_cad_pipeline_returns_constrained_edit_result(self) -> None:
        service = object.__new__(RobotAgentService)
        route = {
            "name": "drawing_design",
            "operation": "modify",
            "decision_source": "constrained_cad_addition",
        }
        constrained_result = {"ok": True, "message": "constraint applied"}
        with (
            patch.object(service, "_structured_cad_edit_fallback", return_value=route),
            patch.object(service, "_apply_incremental_candidate_chain", return_value=None),
            patch.object(
                service,
                "_apply_constrained_candidate_addition",
                return_value=constrained_result,
            ),
            patch.object(service, "_apply_incremental_candidate_edit") as edit,
            patch.object(service, "_formal_cad_construction") as construction,
        ):
            _, result = service._run_advanced_cad_pipeline(
                "添加一个相切圆", [], route, mode="advanced"
            )

        self.assertIs(result, constrained_result)
        edit.assert_not_called()
        construction.assert_not_called()

    def test_cad_edit_dispatch_does_not_probe_unselected_handlers(self) -> None:
        service = object.__new__(RobotAgentService)
        route = {
            "operation": "modify",
            "decision_source": "drawing_layout_followup",
        }
        expected = {"ok": True, "message": "layout updated"}
        with (
            patch.object(service, "_apply_incremental_candidate_chain") as chain,
            patch.object(service, "_apply_constrained_candidate_addition") as constrained,
            patch.object(service, "_apply_incremental_candidate_edit") as incremental,
            patch.object(service, "_apply_relative_template_addition") as relative,
            patch.object(
                service, "_apply_drawing_layout_followup", return_value=expected,
            ) as layout,
        ):
            result = service._apply_cad_edit_commands("改成左右排列", route)

        self.assertIs(result, expected)
        layout.assert_called_once_with("改成左右排列", route)
        chain.assert_not_called()
        constrained.assert_not_called()
        incremental.assert_not_called()
        relative.assert_not_called()

    def test_base_circle_runs_motion_skill_not_design_skill(self) -> None:
        result = self.service._local_intent(
            "控制小车按半径0.5米的圆走",
            allow_design=False,
        )
        self.assertIn("圆周运动演示", result["message"])
        self.assertNotIn("图纸", result["message"])
        self.assertIsNotNone(result["pending_action"])

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

    @patch("app.agent_service.agent_tasks.transition")
    @patch("app.agent_service.build_action_preflight")
    def test_emergency_stop_failure_preserves_motion_for_reconfirmation(
        self,
        preflight: MagicMock,
        transition: MagicMock,
    ) -> None:
        self.service.pending["original-action"] = PendingAction(
            name="drive_sequence",
            arguments={
                "steps": [
                    {"linear": 0.1, "angular": 0.0, "duration_seconds": 1.0}
                ]
            },
            expires_at=datetime.now() + timedelta(minutes=1),
            mode="base",
        )
        preflight.return_value = {
            "ready": False,
            "checks": [{
                "code": "emergency_stop",
                "label": "急停状态",
                "ok": False,
                "detail": "急停仍处于锁定状态",
            }],
        }
        self.service._register_pending = MagicMock(return_value={
            "id": "retry-action",
            "name": "drive_sequence",
            "arguments": self.service.pending["original-action"].arguments,
            "preflight": preflight.return_value,
        })

        result = self.service.confirm("original-action", True)

        self.assertFalse(result["ok"])
        self.assertTrue(result["retryable"])
        self.assertEqual(result["pending_action"]["id"], "retry-action")
        self.assertTrue(result["pending_action"]["retryable_preflight"])
        self.assertEqual(
            result["pending_action"]["retry_reason_codes"],
            ["emergency_stop"],
        )
        self.assertIn("动作已保留", result["message"])
        self.service._register_pending.assert_called_once_with(
            "drive_sequence",
            {
                "steps": [
                    {"linear": 0.1, "angular": 0.0, "duration_seconds": 1.0}
                ]
            },
            mode="base",
        )
        transition.assert_called_once()

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

    def test_base_unitless_square_request_routes_to_confirmed_motion_demo(self) -> None:
        self.service._register_pending = lambda name, arguments, mode="base": {
            "name": name,
            "arguments": arguments,
        }
        message = "控制小车走一个边长为1的正方形"

        route = self.service.resolve_intent(message, mode="base")
        result = self.service.chat(message, [], mode="base", route=route)

        self.assertEqual(route["name"], "motion_control")
        self.assertEqual(route["decision_source"], "base_rectangular_motion_request")
        self.assertTrue(route["safety_confirmation_required"])
        self.assertEqual(result["pending_action"]["name"], "drive_sequence")
        self.assertEqual(len(result["pending_action"]["arguments"]["steps"]), 8)
        self.assertIn("开环演示", result["message"])
        self.assertNotIn("切换进阶模式", result["message"])
        self.assertNotIn("printer", str(result["pending_action"]).lower())

    def test_base_equilateral_triangle_returns_preview_and_confirmation(self) -> None:
        service = object.__new__(RobotAgentService)
        service.pending = {}
        service._register_pending = lambda name, arguments, mode="base": {
            "name": name,
            "arguments": arguments,
            "motion_json": {
                "schema_version": "1.0",
                "task": "movement_command",
                "steps": arguments["steps"],
            },
        }
        message = "控制小车走一个边长为1m的等边三角形"

        route = service.resolve_intent(message, mode="base")
        result = service.chat(message, [], mode="base", route=route)

        self.assertEqual(route["name"], "motion_control")
        self.assertEqual(route["decision_source"], "base_polygonal_motion_request")
        self.assertFalse(route["clarification_required"])
        self.assertEqual(result["pending_action"]["name"], "drive_sequence")
        steps = result["pending_action"]["arguments"]["steps"]
        self.assertEqual(len(steps), 6)
        self.assertEqual([step["linear"] for step in steps[::2]], [0.1] * 3)
        self.assertEqual([step["angular"] for step in steps[1::2]], [0.4] * 3)
        self.assertIn("运动路径预览", result["message"])
        self.assertIn("累计误差", result["message"])
        self.assertIn("确认执行", result["message"])
        self.assertNotIn("切换进阶模式", result["message"])

    def test_base_drawing_request_does_not_become_rover_motion(self) -> None:
        message = "设计一个边长为1米的正方形图纸"

        route = self.service.resolve_intent(message, mode="base")

        self.assertEqual(route["name"], "drawing_design")
        self.assertNotEqual(route.get("decision_source"), "base_rectangular_motion_request")

    def test_base_circle_request_returns_real_confirmation_action(self) -> None:
        self.service._register_pending = lambda name, arguments, mode="base": {
            "name": name,
            "arguments": arguments,
        }
        route = self.service.route_intent(
            "以线速度 0.15 m/s、角速度 0.3 rad/s 走一圈",
            mode="base",
        )
        result = self.service._local_intent(
            "以线速度 0.15 m/s、角速度 0.3 rad/s 走一圈",
            allow_design=False,
            mode="base",
        )

        self.assertEqual(route["name"], "motion_control")
        self.assertEqual(result["pending_action"]["name"], "drive_robot")
        self.assertAlmostEqual(
            result["pending_action"]["arguments"]["duration_seconds"],
            20.944,
            places=3,
        )
        self.assertIn("未接入障碍检测", result["message"])
        self.assertIn("确认执行", result["message"])

    def test_base_circle_rejects_unsafe_velocity(self) -> None:
        self.service._register_pending = lambda *args, **kwargs: self.fail(
            "unsafe circle must not create a pending action"
        )
        result = self.service._local_intent(
            "以线速度 2 m/s、角速度 0.3 rad/s 走一圈",
            allow_design=False,
            mode="base",
        )
        self.assertIsNone(result["pending_action"])
        self.assertIn("安全限制", result["message"])

    def test_circle_speed_answer_uses_previous_radius(self) -> None:
        service = object.__new__(RobotAgentService)
        service._register_pending = lambda name, arguments, mode="base": {
            "name": name,
            "arguments": arguments,
        }
        history = [
            {
                "role": "user",
                "content": "让小车画半径 0.5 米的圆",
            },
            {
                "role": "assistant",
                "content": (
                    "画半径 0.5 米的圆建议走图形任务链。请确认一点："
                    "圆周速度希望多少（例如 0.15 m/s 慢速演示）？"
                ),
            },
        ]

        route = service.resolve_intent(
            "0.15 m/s 慢速演示", mode="base", history=history
        )
        result = service.chat(
            "0.15 m/s，逆时针", history, mode="base", route=route
        )

        self.assertEqual(
            route["decision_source"], "circular_motion_parameter_followup"
        )
        self.assertFalse(route["clarification_required"])
        self.assertEqual(result["pending_action"]["name"], "drive_robot")
        self.assertEqual(result["pending_action"]["arguments"]["linear"], 0.15)
        self.assertEqual(result["pending_action"]["arguments"]["angular"], 0.3)
        self.assertIn("确认执行", result["message"])

    def test_circle_speed_and_radius_answer_is_not_routed_to_status_query(self) -> None:
        service = object.__new__(RobotAgentService)
        service._register_pending = lambda name, arguments, mode="base": {
            "name": name,
            "arguments": arguments,
            "motion_json": {"task": "movement_command", "steps": [arguments]},
        }
        history = [{
            "role": "assistant",
            "content": "请同时提供圆周运动的线速度和角速度，或提供线速度与半径。",
        }]

        route = service.resolve_intent(
            "线速度1m/s 半径1m",
            mode="base",
            history=history,
        )
        result = service.chat(
            "线速度1m/s 半径1m",
            history,
            mode="base",
            route=route,
        )

        self.assertEqual(route["name"], "motion_control")
        self.assertEqual(route["decision_source"], "circular_motion_parameter_followup")
        self.assertFalse(route["clarification_required"])
        self.assertIsNone(result["pending_action"])
        self.assertIn("安全限制", result["message"])

    def test_circle_direction_followup_generates_preview_and_confirmation(self) -> None:
        service = object.__new__(RobotAgentService)
        service.pending = {}
        service._register_pending = lambda name, arguments, mode="base": {
            "name": name,
            "arguments": arguments,
            "motion_json": {"task": "movement_command", "steps": [arguments]},
        }
        history = [
            {"role": "user", "content": "线速度0.3m/s 半径1m"},
            {
                "role": "assistant",
                "content": "请只确认运动方向：顺时针还是逆时针？",
            },
        ]

        route = service.resolve_intent("顺时针", mode="base", history=history)
        result = service.chat("顺时针", history, mode="base", route=route)

        self.assertEqual(route["name"], "motion_control")
        self.assertEqual(route["decision_source"], "circular_motion_parameter_followup")
        self.assertFalse(route["clarification_required"])
        self.assertEqual(result["pending_action"]["name"], "drive_robot")
        self.assertEqual(result["pending_action"]["arguments"]["linear"], 0.3)
        self.assertEqual(result["pending_action"]["arguments"]["angular"], -0.3)
        self.assertIn("确认执行", result["message"])

    def test_circle_followup_prefers_latest_user_speed_over_stale_assistant_text(self) -> None:
        service = object.__new__(RobotAgentService)
        service.pending = {}
        history = [
            {"role": "user", "content": "让小车画半径1米的圆"},
            {"role": "assistant", "content": "已识别圆周运动参数：线速度 0m/s。"},
            {"role": "user", "content": "线速度0.3m/s"},
            {"role": "assistant", "content": "请只确认运动方向：顺时针还是逆时针？"},
        ]

        route = service.resolve_intent("顺时针", mode="base", history=history)
        self.assertEqual(route["decision_source"], "circular_motion_parameter_followup")
        self.assertIn("线速度 0.3 m/s", route["resolved_message"])

        service.pending = {}
        service._register_pending = lambda name, arguments, mode="base": {
            "name": name,
            "arguments": arguments,
            "motion_json": {"task": "movement_command", "steps": [arguments]},
        }
        result = service.chat("顺时针", history, mode="base", route=route)
        self.assertEqual(result["pending_action"]["arguments"]["linear"], 0.3)
        self.assertIn("确认执行", result["message"])

    def test_base_circle_request_uses_safe_default_speed(self) -> None:
        service = object.__new__(RobotAgentService)
        service.pending = {}
        route = service.resolve_intent(
            "让小车画半径0.5米的圆", mode="base", history=[]
        )
        result = service.chat(
            "让小车画半径0.5米的圆", [], mode="base", route=route
        )

        self.assertEqual(route["name"], "motion_control")
        self.assertEqual(route["decision_source"], "base_circular_motion_request")
        self.assertIn("半径 0.5 米", result["message"])
        self.assertIn("0.15 m/s", result["message"])
        self.assertIn("默认逆时针", result["message"])
        self.assertEqual(result["pending_action"]["name"], "drive_robot")
        self.assertEqual(result["pending_action"]["arguments"]["linear"], 0.15)
        self.assertEqual(result["pending_action"]["arguments"]["angular"], 0.3)

    def test_base_circle_radius_without_unit_defaults_to_meters(self) -> None:
        service = object.__new__(RobotAgentService)
        service.pending = {}
        message = "控制小车走一个半径为0.5的圆"

        route = service.resolve_intent(message, mode="base", history=[])
        result = service.chat(message, [], mode="base", route=route)

        self.assertEqual(route["name"], "motion_control")
        self.assertEqual(
            route["decision_source"], "base_circular_motion_request"
        )
        self.assertIn("半径 0.5 米", result["message"])
        self.assertNotIn("请提供圆的半径", result["message"])
        self.assertEqual(result["pending_action"]["name"], "drive_robot")
        self.assertEqual(result["pending_action"]["arguments"]["linear"], 0.15)
        self.assertEqual(result["pending_action"]["arguments"]["angular"], 0.3)

    def test_base_generated_circle_defaults_to_motion_demo(self) -> None:
        service = object.__new__(RobotAgentService)
        service.pending = {}
        route = service.resolve_intent(
            "生成一个半径1米的圆", mode="base", history=[]
        )
        result = service.chat(
            "生成一个半径1米的圆", [], mode="base", route=route
        )
        self.assertEqual(route["name"], "motion_control")
        self.assertEqual(route["decision_source"], "base_circular_motion_request")
        self.assertIn("半径 1 米", result["message"])
        self.assertIn("线速度", result["message"])
        self.assertNotIn("图纸", result["message"])
        self.assertIsNotNone(result["pending_action"])

    def test_base_circle_screenshot_flow_returns_confirmation_without_direction_question(self) -> None:
        service = object.__new__(RobotAgentService)
        service._register_pending = lambda name, arguments, mode="base": {
            "name": name,
            "arguments": arguments,
        }
        history = [
            {"role": "user", "content": "控制小车走一个边长为1m的圆"},
            {
                "role": "assistant",
                "content": "请同时提供圆周运动的线速度和角速度，或提供线速度与半径。",
            },
        ]

        route = service.resolve_intent(
            "线速度为0.2m/s 半径为1m", mode="base", history=history
        )
        result = service.chat(
            "线速度为0.2m/s 半径为1m", history, mode="base", route=route
        )

        self.assertEqual(route["decision_source"], "circular_motion_parameter_followup")
        self.assertFalse(route["clarification_required"])
        self.assertEqual(result["pending_action"]["name"], "drive_sequence")
        steps = result["pending_action"]["arguments"]["steps"]
        self.assertEqual(len(steps), 2)
        self.assertTrue(all(step["linear"] == 0.2 for step in steps))
        self.assertTrue(all(step["angular"] == 0.2 for step in steps))
        self.assertNotIn("0m/s", result["message"])
        self.assertIn("默认逆时针", result["message"])
        self.assertIn("确认执行", result["message"])

    def test_circle_side_word_is_treated_as_radius_for_simple_demo(self) -> None:
        service = object.__new__(RobotAgentService)
        service._register_pending = lambda name, arguments, mode="base": {
            "name": name,
            "arguments": arguments,
        }

        route = service.resolve_intent(
            "控制小车走一个边长为1m的圆", mode="base", history=[]
        )
        result = service.chat(
            "控制小车走一个边长为1m的圆", [], mode="base", route=route
        )

        self.assertEqual(route["decision_source"], "base_circular_motion_request")
        self.assertIsNotNone(result["pending_action"])
        self.assertIn("已按半径理解", result["message"])
        self.assertIn("0.15 m/s", result["message"])

    def test_motion_demo_choice_inherits_circle_and_radius(self) -> None:
        service = object.__new__(RobotAgentService)
        service.pending = {}
        history = [
            {"role": "user", "content": "生成一个半径1米的圆"},
            {
                "role": "assistant",
                "content": "请确认是图形任务还是只进行运动演示？这个圆半径 1 米。",
            },
        ]
        route = service.resolve_intent(
            "只进行运动演示", mode="base", history=history
        )
        result = service.chat(
            "只进行运动演示", history, mode="base", route=route
        )
        self.assertEqual(route["decision_source"], "base_motion_demo_followup")
        self.assertIn("半径 1 米", route["resolved_message"])
        self.assertIn("线速度", result["message"])
        self.assertNotIn("设备和具体动作", result["message"])

    def test_motion_demo_choice_without_context_asks_for_shape_once(self) -> None:
        route = self.service.resolve_intent(
            "只进行运动演示", mode="base", history=[]
        )
        self.assertTrue(route["clarification_required"])
        self.assertIn("路径形状和尺寸", route["clarification_question"])

    def test_circle_speed_answer_stream_returns_confirmation_action(self) -> None:
        service = object.__new__(RobotAgentService)
        service._register_pending = lambda name, arguments, mode="base": {
            "name": name,
            "arguments": arguments,
        }
        history = [
            {"role": "user", "content": "让小车画半径 0.5 米的圆"},
            {"role": "assistant", "content": "画半径 0.5 米的圆。圆周速度希望多少？"},
        ]
        route = service.resolve_intent(
            "0.15 m/s，顺时针", mode="base", history=history
        )

        events = list(service.chat_stream(
            "0.15 m/s，顺时针", history, mode="base", route=route
        ))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "result")
        self.assertIn("确认执行", events[0]["message"])
        self.assertEqual(events[0]["pending_action"]["name"], "drive_robot")

    def test_circle_speed_followup_inherits_unitless_radius(self) -> None:
        service = object.__new__(RobotAgentService)
        service._register_pending = lambda name, arguments, mode="base": {
            "name": name,
            "arguments": arguments,
        }
        history = [
            {"role": "user", "content": "控制小车走一个半径为0.5的圆"},
            {"role": "assistant", "content": "请补充圆周运动速度。"},
        ]

        route = service.resolve_intent(
            "线速度0.15m/s，顺时针", mode="base", history=history
        )
        result = service.chat(
            "线速度0.15m/s，顺时针", history, mode="base", route=route
        )

        self.assertEqual(
            route["decision_source"], "circular_motion_parameter_followup"
        )
        self.assertIn("半径 0.5 米", result["message"])
        self.assertIn("确认执行", result["message"])
        self.assertEqual(result["pending_action"]["name"], "drive_robot")

    def test_mode_names_map_to_base_and_advanced(self) -> None:
        self.assertEqual(self.service.normalize_agent_mode("chat"), "base")
        self.assertEqual(self.service.normalize_agent_mode("base"), "base")
        self.assertEqual(self.service.normalize_agent_mode("work"), "advanced")
        self.assertEqual(self.service.normalize_agent_mode("advanced"), "advanced")

    def test_task_readiness_question_routes_to_diagnosis(self) -> None:
        route = self.service.route_intent("检查小车是否可以开始任务", mode="advanced")
        self.assertEqual(route["name"], "diagnosis")
        self.assertEqual(route["operation"], "diagnose")
        self.assertEqual(route["next_step"], "读取实时状态并给出证据")

    def test_short_affirmation_keeps_movement_demo_context(self) -> None:
        route = self.service.resolve_intent(
            "没错",
            mode="base",
            history=[
                {
                    "role": "assistant",
                    "content": "你说的“只进行运动演示”是指先不喷墨/不画线，只让机器人按5×3米矩形路径走一遍吗？",
                }
            ],
        )
        self.assertEqual(route["decision_source"], "affirmative_followup")
        self.assertEqual(route["name"], "motion_control")
        self.assertFalse(route["clarification_required"])
        self.assertEqual(route["followup_dimensions"], {"width_m": 5.0, "height_m": 3.0})

    def test_short_affirmation_creates_pending_movement_sequence(self) -> None:
        service = object.__new__(RobotAgentService)
        service._register_pending = lambda name, arguments, mode="base": {
            "name": name,
            "arguments": arguments,
        }
        history = [
            {
                "role": "assistant",
                "content": "只让机器人按5×3米矩形路径走一遍吗？不喷墨、不画线。",
            }
        ]
        route = service.resolve_intent("没错", mode="base", history=history)
        result = service.chat("没错", history, mode="base", route=route)
        self.assertIn("5×3 米矩形路径", result["message"])
        self.assertEqual(result["pending_action"]["name"], "drive_sequence")
        self.assertGreaterEqual(len(result["pending_action"]["arguments"]["steps"]), 8)

    def test_design_generation_confirmation_has_deterministic_route(self) -> None:
        route = self.service.route_intent("确认生成候选方案", mode="advanced")
        self.assertEqual(route["name"], "drawing_design")
        self.assertEqual(route["stage"], "candidate_generation")
        self.assertFalse(route["review_required"])
        self.assertFalse(route["api_required"])

    def test_short_design_confirmation_uses_previous_generation_question(self) -> None:
        route = self.service.resolve_intent(
            "确认",
            mode="advanced",
            history=[{
                "role": "assistant",
                "content": "确认按标准 28×15 米生成候选方案吗？确认后我再出图。",
            }],
        )

        self.assertEqual(route["name"], "drawing_design")
        self.assertEqual(route["decision_source"], "design_confirmation_followup")
        self.assertEqual(route["resolved_message"], "确认生成候选方案")
        self.assertFalse(route["clarification_required"])

    def test_detailed_design_confirmation_does_not_enter_model_clarification(self) -> None:
        route = self.service.resolve_intent(
            "确认按标准 28×15 米生成候选方案",
            mode="advanced",
            history=[],
        )

        self.assertEqual(route["name"], "drawing_design")
        self.assertEqual(route["decision_source"], "design_confirmation_followup")
        self.assertFalse(route["review_required"])
        self.assertFalse(route["clarification_required"])

    def test_site_capacity_question_routes_to_cad_not_vehicle_status(self) -> None:
        route = self.service.route_intent(
            "100平方米的土地能画多少个篮球场", mode="advanced"
        )
        self.assertEqual(route["name"], "drawing_design")
        self.assertEqual(route["tool_family"], "cad")
        self.assertEqual(route["operation"], "inspect")
        self.assertNotIn("runtime", route["requested_data_domains"])

    def test_graphic_change_request_routes_to_cad_modification(self) -> None:
        route = self.service.route_intent("把当前图形右侧增加一条边界线", mode="advanced")
        self.assertEqual(route["name"], "drawing_design")
        self.assertEqual(route["operation"], "modify")

    def test_deepseek_cad_tools_cannot_bypass_candidate_edit_pipeline(self) -> None:
        route = {
            "name": "drawing_design",
            "tool_family": "cad",
            "operation": "modify",
        }
        names = {
            item["function"]["name"]
            for item in self.service._selected_deepseek_tools(
                "把当前图形向右移动一米",
                mode="advanced",
                route=route,
            )
        }
        self.assertNotIn("modify_drawing", names)
        self.assertNotIn("add_design_variant", names)

    def test_spatial_new_design_request_cannot_become_candidate_edit(self) -> None:
        route = self.service.resolve_intent(
            "规划一个半径为1m的圆，在圆的上方1m有一个标准的停车位",
            mode="advanced",
            history=[],
        )
        self.assertEqual(route["name"], "drawing_design")
        self.assertEqual(route["operation"], "create")
        self.assertNotEqual(route.get("decision_source"), "incremental_cad_edit")

    def test_advanced_reasoner_has_room_for_answer_after_reasoning(self) -> None:
        self.assertEqual(self.service._deepseek_max_tokens("advanced"), 2400)
        self.assertEqual(self.service._deepseek_max_tokens("base"), 900)

    def test_streamed_safe_tool_gets_model_followup_answer(self) -> None:
        service = object.__new__(RobotAgentService)
        service._execute_safe = lambda name, arguments, mode="base": {
            "ok": True,
            "message": "实时状态已读取",
        }
        service._deepseek_request = lambda messages, tools, mode="base": {
            "choices": [{"message": {"content": "根据读取结果生成的最终答复"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
        }
        result = service._streamed_tool_result(
            [{"id": "call-1", "name": "get_robot_status", "arguments": "{}"}],
            {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
            mode="advanced",
            messages=[{"role": "user", "content": "读取状态"}],
            tools=[],
        )
        self.assertEqual(result["message"], "根据读取结果生成的最终答复")
        self.assertEqual(result["usage"]["total_tokens"], 17)

    def test_deepseek_cannot_call_internal_variant_writer(self) -> None:
        service = object.__new__(RobotAgentService)
        variant = {
            "id": "variant-arch",
            "name": "半圆拱门",
            "preview_paths": [{"points": [[0, 0], [1, 2], [2, 0]]}],
        }
        project = {"id": "project-arch", "variants": [variant]}
        service._execute_safe = lambda name, arguments, mode="base": {
            "ok": True,
            "message": "候选方案已生成",
            "project": project,
            "variant": variant,
            "preview_paths": variant["preview_paths"],
        }
        service._deepseek_request = lambda messages, tools, mode="base": {
            "choices": [{"message": {"content": "拱门候选已生成"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        with patch(
            "app.agent_service.validate_tool_arguments",
            return_value=({}, None),
        ):
            result = service._streamed_tool_result(
                [{"id": "call-cad", "name": "add_design_variant", "arguments": "{}"}],
                {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                mode="advanced",
                messages=[{"role": "user", "content": "绘制半圆拱门"}],
                tools=[],
            )

        self.assertNotIn("project", result)
        self.assertNotIn("variant", result)
        self.assertIn("add_design_variant", result["message"])

    def test_streamed_status_then_motion_still_requires_confirmation(self) -> None:
        service = object.__new__(RobotAgentService)
        service._execute_safe = lambda name, arguments, mode="base": {
            "ok": True,
            "message": "实时状态已读取",
        }
        service._register_pending = lambda name, arguments, mode="base": {
            "id": "pending-motion",
            "name": name,
            "arguments": arguments,
        }
        service._deepseek_request = lambda messages, tools, mode="base": {
            "choices": [{"message": {
                "content": "",
                "tool_calls": [{
                    "id": "call-motion",
                    "type": "function",
                    "function": {
                        "name": "drive_robot",
                        "arguments": (
                            '{"linear":0.0,"angular":0.4,'
                            '"duration_seconds":2.0}'
                        ),
                    },
                }],
            }}],
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": 7,
                "total_tokens": 12,
            },
        }

        result = service._streamed_tool_result(
            [{
                "id": "call-status",
                "name": "get_robot_status",
                "arguments": "{}",
            }],
            {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
            mode="base",
            messages=[{"role": "user", "content": "原地左转"}],
            tools=[],
        )

        self.assertEqual(result["pending_action"]["name"], "drive_robot")
        self.assertIn("确认执行", result["message"])
        self.assertNotIn("tool_results", result)

    def test_task_readiness_question_uses_live_local_diagnosis(self) -> None:
        result = self.service._local_intent(
            "检查小车是否可以开始任务", allow_design=True, mode="advanced"
        )
        self.assertIsNotNone(result)
        self.assertIn("底盘", result["message"])

    def test_advanced_chat_does_not_bypass_api_for_design_advice(self) -> None:
        service = object.__new__(RobotAgentService)
        service.mode = "deepseek"
        service.api_keys = {"deepseek": "test-key"}
        service.model = "deepseek-chat"
        service.advanced_model = "deepseek-reasoner"
        with patch.object(
            service,
            "_deepseek_chat",
            return_value={"ok": True, "message": "API answer", "usage": {}},
        ) as api:
            result = service.chat("100平方米土地适合设计什么", [], mode="advanced")
        api.assert_called_once()
        self.assertEqual("API answer", result["message"])

    def test_deepseek_connection_uses_supported_model_collection_endpoint(self) -> None:
        service = object.__new__(RobotAgentService)
        service.mode = "deepseek"
        service.model = "deepseek-chat"
        service.api_keys = {"deepseek": "test-key"}
        response = MagicMock()
        response.status = 200
        response.__enter__.return_value = response
        with patch("app.agent_service.urllib.request.urlopen", return_value=response) as request:
            result = service.test_connection()
        self.assertTrue(result["ok"])
        self.assertEqual(request.call_args.args[0].full_url, "https://api.deepseek.com/models")

    def test_deepseek_requests_do_not_share_a_global_network_lock(self) -> None:
        service = object.__new__(RobotAgentService)
        service.mode = "deepseek"
        service.base_model = "deepseek-chat"
        service.advanced_model = "deepseek-reasoner"
        service._deepseek_request_timeout = 10.0
        active = 0
        max_active = 0
        entered_lock = threading.Lock()

        class Response:
            status = 200

            def __init__(self) -> None:
                self._read = False

            def read(self, _size: int = -1) -> bytes:
                if self._read:
                    return b""
                self._read = True
                return b'{"choices": []}'

            def close(self) -> None:
                return None

        class Connection:
            def close(self) -> None:
                return None

        def response_factory(_payload: dict[str, object]):
            nonlocal active, max_active
            with entered_lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.15)
            with entered_lock:
                active -= 1
            return Connection(), Response()

        with patch.object(service, "_deepseek_response", side_effect=response_factory):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(
                    lambda _: service._deepseek_request([], tools=[]), range(2)
                ))
        self.assertEqual(2, len(results))
        self.assertEqual(2, max_active)

    def test_deepseek_request_has_a_total_timeout(self) -> None:
        service = object.__new__(RobotAgentService)
        service.mode = "deepseek"
        service.base_model = "deepseek-chat"
        service.advanced_model = "deepseek-reasoner"
        service._deepseek_request_timeout = 0.05

        class SlowResponse:
            status = 200

            def read(self, _size: int = -1) -> bytes:
                time.sleep(0.1)
                return b'{"choices": []}'

            def close(self) -> None:
                return None

        class Connection:
            def close(self) -> None:
                return None

        with patch.object(
            service,
            "_deepseek_response",
            return_value=(Connection(), SlowResponse()),
        ):
            with self.assertRaisesRegex(RuntimeError, "请求超时"):
                service._deepseek_request([], tools=[])

    def test_user_model_config_does_not_overwrite_the_default_profile(self) -> None:
        service = object.__new__(RobotAgentService)
        service._mode = "local"
        service._model = "xline-local-diagnostics"
        service._base_model = service._model
        service._advanced_model = service._model
        service._api_keys = {}

        class Store:
            def __init__(self) -> None:
                self.profiles: dict[str, dict[str, object]] = {}

            def get(self, owner: str):
                profile = self.profiles.get(owner)
                return dict(profile) if profile is not None else None

            def update(self, owner: str, **values):
                self.profiles[owner] = {
                    "mode": values["mode"],
                    "model": values["model"],
                    "base_model": values["model"],
                    "advanced_model": values["model"],
                    "api_keys": {values["mode"]: values["api_key"]},
                }
                return self.profiles[owner]

        store = Store()
        with patch("app.agent_service.user_model_config", store):
            with agent_user_scope("user-a"):
                service.update_config("deepseek", "deepseek-chat", "key-a")
                self.assertEqual("deepseek", service.mode)
                self.assertEqual("key-a", service.api_key)
            self.assertEqual("local", service._mode)
            self.assertEqual({}, service._api_keys)

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

    def test_replayed_pending_device_action_reuses_existing_task(self) -> None:
        self.service.pending = {}
        arguments = {
            "steps": [{"linear": 0.1, "angular": 0.0, "duration_seconds": 1.0}]
        }
        first = self.service._register_pending("drive_sequence", arguments)
        second = self.service._register_pending("drive_sequence", arguments)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.service.pending), 1)


if __name__ == "__main__":
    unittest.main()
