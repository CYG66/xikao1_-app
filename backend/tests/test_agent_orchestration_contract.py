from __future__ import annotations

import unittest
from unittest.mock import patch

from app.agent_service import RobotAgentService


class AgentOrchestrationContractTest(unittest.TestCase):
    def test_outer_diameter_is_not_overwritten_by_root_diameter_index(self):
        import json
        project={'original_prompt':'生成一个齿轮轮廓，外径2米，8个齿',
            'requirements':{'dimensions':{'diameter_m':1.5},
                'source_followups':['齿根圆直径1.5米，各齿齿顶角宽15度。']}}
        text=RobotAgentService._project_construction_prompt(project)
        tail=text.split('[CAD_REQUIREMENT_CONTRACT_SNAPSHOT.v1]',1)[1]
        snapshot,_=json.JSONDecoder().raw_decode(tail[tail.index('{'):])
        assert snapshot['requirements']['dimensions']['diameter_m']==2

    def test_array_cell_size_is_not_promoted_to_confirmed_overall_dimensions(self):
        import json
        from copy import deepcopy
        project={'original_prompt':'生成3列2行的蜂窝六边形阵列，边长0.5米，无缝拼接',
            'requirements':{'dimensions':{'width_m':.5,'height_m':.5}}}
        before=deepcopy(project)
        text=RobotAgentService._project_construction_prompt(project)
        tail=text.split('[CAD_REQUIREMENT_CONTRACT_SNAPSHOT.v1]',1)[1]
        snapshot,_=json.JSONDecoder().raw_decode(tail[tail.index('{'):])
        assert snapshot['requirements']['dimensions']=={}
        assert '宽度0.5米' not in text and '高度0.5米' not in text
        assert project==before

    def test_dimensioned_unregistered_object_is_drawing_not_device_motion(self) -> None:
        from app.cad_construction_interpreter import clarify_construction_request
        service = object.__new__(RobotAgentService)
        service.mode = "deepseek"
        service.api_keys = {"deepseek": "test"}
        source = "画一个L形走廊，宽1米，两条臂分别长3米和2米，直角连接"
        with patch.object(service, "_structured_review_text") as request:
            route = service.resolve_intent(source, "advanced", [])
        request.assert_not_called()
        self.assertEqual(route["operation"], "create")
        self.assertEqual(route["tool_family"], "cad")
        clarification = clarify_construction_request(source)
        self.assertEqual(clarification["question_key"], "construction_scope")
        self.assertEqual(clarification["recognized_shape"], "L形走廊")
        self.assertEqual(clarify_construction_request("生成一个")['question_key'], 'shape')

    def test_unregistered_curve_is_reviewed_as_geometry_not_device_motion(self) -> None:
        service = object.__new__(RobotAgentService)
        service.mode = "deepseek"
        service.api_keys = {"deepseek": "test"}
        review = '{"primary_intent":"drawing_design","secondary_intents":[],"confidence":0.98,"requires_clarification":false,"cad_operation":"create"}'
        with patch.object(service, "_structured_review_text", return_value=review) as request:
            route = service.resolve_intent(
                "生成一个阿基米德螺旋线，从(0,0)出发，旋转3圈，最大半径2米",
                "advanced", [],
            )
        self.assertEqual(route["name"], "drawing_design")
        self.assertEqual(route["operation"], "create")
        self.assertFalse(route.get("clarification_required", False))
        prompt = request.call_args.args[0][-1]["content"]
        self.assertIn("不是 motion_control", prompt)
        self.assertIn("只有用户明确要求设备执行动作", prompt)

    def test_edit_domain_is_explicit_for_candidate_and_standalone_targets(self) -> None:
        candidate = RobotAgentService._with_edit_domain({
            "operation": "modify",
            "selected_project_id": "project-1",
            "drawing_selection": {
                "project_id": "project-1",
                "variant_id": "variant-1",
                "geometry_ids": [1],
            },
        })
        standalone = RobotAgentService._with_edit_domain({
            "operation": "modify",
            "drawing_selection": {
                "source_file_name": "standalone.json",
                "geometry_ids": [1],
            },
        })

        self.assertEqual(candidate["edit_domain"], "candidate_variant")
        self.assertEqual(standalone["edit_domain"], "standalone_drawing")

    def test_candidate_domain_rejects_standalone_modify_tool(self) -> None:
        error = RobotAgentService._edit_domain_tool_error(
            "modify_drawing",
            {
                "operation": "modify",
                "selected_project_id": "project-1",
                "edit_domain": "candidate_variant",
            },
        )
        self.assertIn("候选方案", error)

    def test_colloquial_generic_cad_creation_is_not_sent_to_generic_router(self) -> None:
        service = object.__new__(RobotAgentService)
        service.mode = "deepseek"
        service.api_keys = {"deepseek": "test"}
        with patch.object(service, "_structured_review_text") as request:
            route = service.resolve_intent(
                "绘画一个大小不超过5m的爱心", "advanced", []
            )
        request.assert_not_called()
        self.assertEqual(route["name"], "drawing_design")
        self.assertEqual(route["operation"], "create")
        self.assertFalse(route["clarification_required"])
        self.assertEqual(
            route["decision_source"], "deterministic_generic_cad_creation"
        )

    def test_rectangle_design_request_does_not_get_generic_clarification(self) -> None:
        service = object.__new__(RobotAgentService)
        service.mode = "deepseek"
        service.api_keys = {"deepseek": "test"}
        with patch.object(service, "_deepseek_request") as request:
            route = service.resolve_intent("规划一个 5×3 米矩形", "base", [])
        request.assert_not_called()
        self.assertEqual(route["name"], "drawing_design")
        self.assertFalse(route["review_required"])
        with patch.object(service, "_local_intent", return_value=None):
            result = service.chat("规划一个 5×3 米矩形", [], mode="base", route=route)
        self.assertIn("切换进阶模式", result["message"])
        self.assertIsNone(result["pending_action"])

    def test_parking_space_design_does_not_trigger_stop_safety_clarification(self) -> None:
        service = object.__new__(RobotAgentService)
        service.mode = "deepseek"
        service.api_keys = {}
        route = service.resolve_intent(
            "给我生成3个相连的停车位的图纸", "advanced", []
        )
        self.assertEqual(route["name"], "drawing_design")
        self.assertEqual(route["tool_family"], "cad")
        self.assertFalse(route.get("clarification_required", False))
        self.assertNotIn("stop", route.get("review", {}).get("physical_intents", []))

    def test_layout_answer_inherits_advanced_drawing_intent(self) -> None:
        service = object.__new__(RobotAgentService)
        service.mode = "deepseek"
        service.api_keys = {"deepseek": "test"}
        history = [
            {"role": "user", "content": "设计两个篮球场"},
            {"role": "assistant", "content": "请说明排列方式和间距。"},
        ]
        with patch.object(service, "_deepseek_request") as request:
            route = service.resolve_intent("并排，间距 2 米", "advanced", history)
        request.assert_not_called()
        self.assertEqual(route["name"], "drawing_design")
        self.assertEqual(route["tool_family"], "cad")
        self.assertFalse(route["clarification_required"])
        self.assertEqual(route["operation"], "modify")
        self.assertIsNone(RobotAgentService._drawing_layout_followup_route(
            "并排，间距 2 米", "advanced", []
        ))
        self.assertIsNone(RobotAgentService._drawing_layout_followup_route(
            "并排并让小车前进", "advanced", history
        ))

    def test_layout_answer_updates_only_the_selected_drawing_project(self) -> None:
        service = object.__new__(RobotAgentService)
        route = {
            "decision_source": "drawing_layout_followup",
            "object_memory": {"objects": {"project": [{"id": "court-1"}]}},
        }
        project = {
            "id": "court-1", "status": "clarifying",
            "missing_parameters": ["arrangement", "spacing_m"],
        }
        with patch("app.agent_service.get_creative_project_store") as store:
            store.return_value.get.return_value = project
            store.return_value.update.return_value = {**project, "status": "ready_for_design"}
            result = service._apply_drawing_layout_followup("并排，间距 2 米", route)
            store.return_value.update.assert_called_once_with(
                "court-1",
                requirements={
                    "arrangement": "long_side_adjacent",
                    "spacing_m": 2.0,
                    "layout_override": True,
                    "peer_placement": None,
                    "spacing_reference": None,
                },
                missing_parameters=[], event_message="已确认图纸排列方式和间距",
            )
        self.assertEqual(result["project_id"], "court-1")
        self.assertIn("生成候选方案", result["message"])
        self.assertIsNone(result["pending_action"])

    def test_layout_answer_does_not_guess_between_multiple_projects(self) -> None:
        service = object.__new__(RobotAgentService)
        route = {"decision_source": "drawing_layout_followup"}
        with patch("app.agent_service.get_creative_project_store") as store:
            store.list.return_value = [
                {"id": "a", "status": "ready_for_design"},
                {"id": "b", "status": "ready_for_design"},
            ]
            result = service._apply_drawing_layout_followup("并排，间距 2 米", route)
            store.update.assert_not_called()
        self.assertIn("选择", result["message"])

    def test_clear_short_command_does_not_require_model_review(self) -> None:
        service = object.__new__(RobotAgentService)
        service.mode = "deepseek"
        service.api_keys = {"deepseek": "test"}

        with patch.object(service, "_deepseek_request") as request:
            route = service.resolve_intent("停止", "base", [])

        request.assert_not_called()
        self.assertEqual(route["name"], "stop")
        self.assertEqual(route["decision_source"], "rules")

    def test_ambiguous_route_falls_back_without_api_key(self) -> None:
        service = object.__new__(RobotAgentService)
        service.mode = "deepseek"
        service.api_keys = {}

        with patch.object(service, "_deepseek_request") as request:
            route = service.resolve_intent("这个怎么样", "advanced", [])

        request.assert_not_called()
        self.assertEqual(route["decision_source"], "rules_fallback")
        self.assertTrue(route["review"]["attempted"] is False)

    def test_model_can_correct_an_ambiguous_query_route(self) -> None:
        route = RobotAgentService.route_intent("这个怎么样")
        merged = RobotAgentService._merge_route_review(route, {
            "primary_intent": "diagnosis",
            "secondary_intents": ["status_query"],
            "confidence": 0.91,
            "requires_clarification": False,
            "reason": "用户在询问设备异常判断",
        })

        self.assertEqual(merged["name"], "diagnosis")
        self.assertEqual(merged["tool_family"], "telemetry")
        self.assertEqual(merged["decision_source"], "model_review")
        self.assertEqual(merged["secondary_intents"], ["status_query"])

    def test_model_cannot_invent_physical_action(self) -> None:
        route = RobotAgentService.route_intent("它现在怎么样")
        merged = RobotAgentService._merge_route_review(route, {
            "primary_intent": "motion_control",
            "secondary_intents": [],
            "confidence": 0.98,
            "requires_clarification": False,
        })

        self.assertTrue(merged["clarification_required"])
        self.assertEqual(merged["decision_source"], "safety_clarification")
        self.assertEqual(merged["tool_family"], "conversation")

    def test_model_cannot_downgrade_rule_physical_action(self) -> None:
        route = RobotAgentService.route_intent("前进")
        merged = RobotAgentService._merge_route_review(route, {
            "primary_intent": "status_query",
            "secondary_intents": [],
            "confidence": 0.8,
            "requires_clarification": False,
        })

        self.assertTrue(merged["clarification_required"])
        self.assertEqual(merged["decision_source"], "safety_clarification")

    def test_model_review_normalizes_invalid_confidence_and_secondary_type(self) -> None:
        route = RobotAgentService.route_intent("这个怎么样")
        merged = RobotAgentService._merge_route_review(route, {
            "primary_intent": "diagnosis",
            "secondary_intents": "status_query",
            "confidence": "not-a-number",
            "requires_clarification": False,
        })

        self.assertEqual(merged["name"], "conversation")
        self.assertEqual(merged["confidence"], 0.0)
        self.assertEqual(merged["secondary_intents"], [])
        self.assertTrue(merged["clarification_required"])

    def test_low_model_confidence_forces_clarification(self) -> None:
        route = RobotAgentService.route_intent("这个怎么样")
        merged = RobotAgentService._merge_route_review(route, {
            "primary_intent": "diagnosis",
            "secondary_intents": [],
            "confidence": 0.3,
            "requires_clarification": False,
        })

        self.assertTrue(merged["clarification_required"])
        self.assertEqual(merged["decision_source"], "model_clarification")

    def test_secondary_physical_intent_forces_clarification(self) -> None:
        route = RobotAgentService.route_intent("查看状态并让它前进")
        merged = RobotAgentService._merge_route_review(route, {
            "primary_intent": "status_query",
            "secondary_intents": ["motion_control"],
            "confidence": 0.95,
            "requires_clarification": False,
        })

        self.assertTrue(merged["clarification_required"])
        self.assertEqual(merged["tool_family"], "conversation")

    def test_deterministic_rules_stop_mixed_query_and_motion_before_api(self) -> None:
        service = object.__new__(RobotAgentService)
        service.mode = "deepseek"
        service.api_keys = {"deepseek": "test"}
        with patch.object(service, "_deepseek_request") as request:
            route = service.resolve_intent("查看当前状态并让它前进", "base", [])

        request.assert_not_called()
        self.assertTrue(route["clarification_required"])
        self.assertEqual(route["decision_source"], "safety_clarification")
        self.assertIn("motion_control", route["review"]["physical_intents"])

    def test_readiness_diagnosis_is_not_misclassified_as_mission_action(self) -> None:
        self.assertEqual(
            RobotAgentService._physical_action_signals("检查小车是否可以开始任务"),
            set(),
        )

    def test_markdown_json_review_is_supported(self) -> None:
        parsed = RobotAgentService._json_object(
            '```json\n{"primary_intent":"status_query"}\n```'
        )
        self.assertEqual(parsed, {"primary_intent": "status_query"})

    def test_direct_chat_stops_before_tools_when_clarification_is_required(self) -> None:
        service = object.__new__(RobotAgentService)
        route = {
            "clarification_required": True,
            "clarification_question": "请说明要控制底盘还是喷码机。",
        }
        with patch.object(service, "_local_intent") as local:
            result = service.chat("继续", [], mode="base", route=route)

        local.assert_not_called()
        self.assertEqual(result["message"], "请说明要控制底盘还是喷码机。")
        self.assertIsNone(result["pending_action"])

    def test_route_contains_single_tool_family_and_context_requirements(self) -> None:
        route = RobotAgentService.route_intent("查询小车当前电量和定位")

        self.assertEqual(route["schema_version"], "1.1")
        self.assertEqual(route["name"], "status_query")
        self.assertEqual(route["tool_family"], "telemetry")
        self.assertEqual(
            route["context_requirements"], ["energy_age_ms", "telemetry_age_ms"]
        )
        self.assertEqual(
            route["requested_data_domains"], ["energy", "localization"]
        )

    def test_domain_stop_and_status_requests_do_not_route_to_chassis_stop(self) -> None:
        self.assertEqual(
            RobotAgentService.route_intent("停止当前划线任务")["name"],
            "mission_control",
        )
        self.assertEqual(
            RobotAgentService.route_intent("关闭喷墨")["name"],
            "printer_control",
        )
        self.assertEqual(
            RobotAgentService.route_intent("查看喷码机状态")["name"],
            "status_query",
        )
        self.assertEqual(
            RobotAgentService.route_intent("当前速度是多少")["name"],
            "status_query",
        )

    def test_localization_action_has_its_own_confirmed_tool_family(self) -> None:
        route = RobotAgentService.route_intent("初始化全站仪", "advanced")

        self.assertEqual(route["name"], "localization_control")
        self.assertEqual(route["tool_family"], "localization")
        self.assertTrue(route["safety_confirmation_required"])
        tools = RobotAgentService._selected_deepseek_tools(
            "初始化全站仪", mode="advanced"
        )
        names = {item["function"]["name"] for item in tools}
        self.assertIn("control_ln150", names)

    @patch("app.agent_service.robot_state.snapshot")
    def test_runtime_context_marks_stale_telemetry(self, snapshot) -> None:
        snapshot.return_value = {
            "online": True,
            "telemetry_age_ms": 5000,
            "printer_status": {},
            "mission_stage": "idle",
        }

        context = RobotAgentService.runtime_context(
            RobotAgentService.route_intent("查询电量")
        )

        self.assertFalse(context["fresh"])
        self.assertEqual(context["source"], "robot_state_snapshot")
        self.assertEqual(context["schema_version"], "1.1")
        self.assertEqual(context["quality"]["freshness_gate"], "block")
        self.assertEqual(context["quality"]["blocked_domains"], ["energy"])

    @patch("app.agent_service.robot_state.snapshot")
    def test_energy_freshness_does_not_depend_on_pose_age(self, snapshot) -> None:
        snapshot.return_value = {
            "online": True,
            "telemetry_age_ms": None,
            "energy_source": "ros_battery_state",
            "energy_age_ms": 250,
            "battery": 76,
            "printer_status": {},
            "mission_stage": "idle",
        }

        context = RobotAgentService.runtime_context(
            RobotAgentService.route_intent("当前电量是多少")
        )

        self.assertTrue(context["fresh"])
        self.assertEqual(context["quality"]["freshness_gate"], "allow")
        self.assertEqual(context["telemetry"]["energy"]["battery_percent"], 76)

    @patch("app.agent_service.robot_state.snapshot")
    def test_stale_printer_does_not_block_fresh_localization(self, snapshot) -> None:
        snapshot.return_value = {
            "online": True,
            "telemetry_age_ms": 120,
            "localization_source": "odom_imu_relative",
            "localization_valid": True,
            "robot_pose": {"x": 1.0, "y": 2.0},
            "printer_status": {"printer_center": {"connected": True}},
            "printer_status_age_ms": 9000,
            "mission_stage": "idle",
        }

        context = RobotAgentService.runtime_context(
            RobotAgentService.route_intent("当前定位是否有效")
        )

        self.assertTrue(context["fresh"])
        self.assertEqual(context["quality"]["blocked_domains"], [])
        self.assertFalse(context["quality"]["domain_quality"]["printer"]["fresh"])

    @patch("app.agent_service.robot_state.snapshot")
    def test_system_context_explicitly_blocks_stale_energy_claims(self, snapshot) -> None:
        snapshot.return_value = {
            "online": True,
            "telemetry_age_ms": 100,
            "energy_source": "ros_battery_state",
            "energy_age_ms": 12000,
            "battery": 55,
            "printer_status": {},
            "mission_stage": "idle",
        }
        service = object.__new__(RobotAgentService)
        route = RobotAgentService.route_intent("当前电量是多少")

        with patch.object(service, "knowledge_context", return_value={"matches": []}):
            context = service._system_context("当前电量是多少", route=route)

        self.assertIn("实时数据新鲜度门禁未通过", context)
        self.assertIn("禁止把 blocked_domains 中的值描述为当前事实", context)

    @patch("app.agent_service.robot_state.snapshot")
    def test_safe_status_tool_returns_verified_status_contract(self, snapshot) -> None:
        state = {
            "online": True,
            "telemetry_age_ms": 100,
            "printer_status": {},
            "mission_stage": "idle",
        }
        snapshot.return_value = state
        service = object.__new__(RobotAgentService)

        result = service._execute_safe("get_robot_status", {})

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], state)
        self.assertTrue(result["verification"]["verified"])
        self.assertEqual(result["verification"]["level"], "telemetry")
        self.assertEqual(result["verification"]["status"], "success")
        self.assertEqual(result["verification"]["tool"], "get_robot_status")

    @patch("app.agent_service.robot_state.snapshot")
    def test_printer_trigger_requires_counter_and_device_state(self, snapshot) -> None:
        snapshot.return_value = {
            "printer_status": {
                "printer_center": {
                    "connected": True,
                    "device_state": 1,
                    "print_count": 11,
                    "spray_state": "spraying",
                }
            }
        }
        before = {
            "printer_status": {
                "printer_center": {"connected": True, "print_count": 10}
            }
        }

        verification = RobotAgentService._validate_tool_result(
            "control_printer",
            {"printer_name": "center", "action": "test_print", "param": 0},
            {"ok": True},
            before,
        )

        self.assertEqual(verification["status"], "success")
        self.assertIn("print_count=10->11", verification["evidence"])

    @patch("app.agent_service.robot_state.snapshot")
    def test_disconnected_printer_is_terminal_verification_failure(self, snapshot) -> None:
        snapshot.return_value = {"printer_status": {}}

        verification = RobotAgentService._validate_tool_result(
            "control_printer",
            {"printer_name": "center", "action": "test_print", "param": 0},
            {"ok": True},
            {},
        )

        self.assertEqual(verification["status"], "failed")
        self.assertEqual(verification["reason_code"], "printer_disconnected")

    @patch("app.agent_service.robot_state.snapshot")
    def test_ln150_submission_stays_pending_without_target_state(self, snapshot) -> None:
        snapshot.return_value = {
            "ln150_ready": True,
            "ln150_status": "",
            "localization_valid": False,
            "localization_source": "unavailable",
        }

        verification = RobotAgentService._validate_tool_result(
            "control_ln150", {"command_type": 2}, {"ok": True}, {}
        )

        self.assertEqual(verification["status"], "pending")
        self.assertFalse(verification["verified"])
        self.assertIn("tracking", verification["expected"])

    @patch("app.agent_service.robot_state.snapshot")
    def test_ln150_initialization_accepts_chinese_success_status(self, snapshot) -> None:
        snapshot.return_value = {
            "ln150_ready": True,
            "ln150_status": "初始化成功，请执行自动跟踪",
            "localization_valid": False,
            "localization_source": "ln150",
        }

        verification = RobotAgentService._validate_tool_result(
            "control_ln150", {"command_type": 1}, {"ok": True}, {}
        )

        self.assertEqual(verification["status"], "success")
        self.assertTrue(verification["verified"])
        self.assertIn("initialized", ",".join(verification["evidence"]))

    @patch("app.agent_service.robot_state.snapshot")
    def test_ln150_tracking_accepts_chinese_tracking_status(self, snapshot) -> None:
        snapshot.return_value = {
            "ln150_ready": True,
            "ln150_status": "自动跟踪中",
            "localization_valid": False,
            "localization_source": "ln150",
        }

        verification = RobotAgentService._validate_tool_result(
            "control_ln150", {"command_type": 2}, {"ok": True}, {}
        )

        self.assertEqual(verification["status"], "success")
        self.assertTrue(verification["verified"])
        self.assertIn("tracking", ",".join(verification["evidence"]))

    @patch("app.agent_service.robot_state.snapshot")
    def test_ln150_leveling_accepts_chinese_level_status(self, snapshot) -> None:
        snapshot.return_value = {
            "ln150_ready": True,
            "ln150_status": "自动调平已完成",
            "localization_valid": False,
            "localization_source": "ln150",
        }

        verification = RobotAgentService._validate_tool_result(
            "control_ln150", {"command_type": 3}, {"ok": True}, {}
        )

        self.assertEqual(verification["status"], "success")
        self.assertTrue(verification["verified"])
        self.assertIn("leveled", ",".join(verification["evidence"]))

    @patch("app.agent_service.robot_state.snapshot")
    def test_ln150_chinese_failure_status_does_not_verify(self, snapshot) -> None:
        snapshot.return_value = {
            "ln150_ready": True,
            "ln150_status": "初始化失败",
            "localization_valid": False,
            "localization_source": "ln150",
        }

        verification = RobotAgentService._validate_tool_result(
            "control_ln150", {"command_type": 1}, {"ok": True}, {}
        )

        self.assertEqual(verification["status"], "pending")
        self.assertFalse(verification["verified"])


if __name__ == "__main__":
    unittest.main()
