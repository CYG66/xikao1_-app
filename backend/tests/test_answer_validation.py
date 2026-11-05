from __future__ import annotations

import unittest

from app.answer_validation import validate_agent_answer


def context(*, requested=None, blocked=None, battery=80, voltage=48.2) -> dict:
    return {
        "quality": {
            "requested_domains": requested or [],
            "blocked_domains": blocked or [],
        },
        "telemetry": {
            "energy": {
                "battery_percent": battery,
                "voltage": voltage,
                "current": None,
                "temperature": None,
            },
            "drive": {"linear_velocity": 0.2},
            "runtime": {"online": True},
            "localization": {"valid": True},
        },
    }


class AnswerValidationTest(unittest.TestCase):
    def test_hides_internal_software_test_report(self) -> None:
        corrected, validation = validate_agent_answer(
            "中间羽毛球场已能正确解析为实例 2。另外，专项测试还暴露了一个原有的候选链上下文断言问题，后续还需要单独处理。",
            {"name": "drawing_design"},
            context(),
        )

        self.assertEqual(corrected, "中间羽毛球场已能正确解析为实例 2。")
        self.assertNotIn("专项测试", corrected)
        self.assertTrue(any(
            item["code"] == "development_report_hidden"
            for item in validation["issues"]
        ))

    def test_keeps_operator_facing_hardware_test_instruction(self) -> None:
        corrected, validation = validate_agent_answer(
            "请先测试喷码机连接，再确认是否执行。",
            {"name": "printer_control"},
            context(),
        )

        self.assertEqual(corrected, "请先测试喷码机连接，再确认是否执行。")
        self.assertFalse(any(
            item["code"] == "development_report_hidden"
            for item in validation["issues"]
        ))

    def test_removes_current_claim_for_stale_domain(self) -> None:
        corrected, validation = validate_agent_answer(
            "当前电量为 80%。建议检查电池接口。",
            {"name": "status_query"},
            context(requested=["energy"], blocked=["energy"]),
        )

        self.assertNotIn("当前电量为 80%", corrected)
        self.assertIn("无法确认当前能源状态", corrected)
        self.assertIn("建议检查电池接口", corrected)
        self.assertEqual(validation["status"], "corrected")

    def test_corrects_numeric_fact_from_fresh_snapshot(self) -> None:
        corrected, validation = validate_agent_answer(
            "当前电量为 35%，电压为 46V。",
            {"name": "status_query"},
            context(requested=["energy"]),
        )

        self.assertEqual(corrected, "当前电量为 80%，电压为 48.2V。")
        self.assertEqual(validation["checks"]["numeric_consistency"], "corrected")

    def test_does_not_change_matching_fresh_facts(self) -> None:
        corrected, validation = validate_agent_answer(
            "当前电量为 80%，电压为 48.2V。",
            {"name": "status_query"},
            context(requested=["energy"]),
        )

        self.assertEqual(corrected, "当前电量为 80%，电压为 48.2V。")
        self.assertEqual(validation["status"], "passed")

    def test_does_not_rewrite_energy_advice_threshold(self) -> None:
        corrected, validation = validate_agent_answer(
            "当前电量为 80%。电量低于 20% 时建议充电。",
            {"name": "status_query"},
            context(requested=["energy"]),
        )

        self.assertEqual(corrected, "当前电量为 80%。电量低于 20% 时建议充电。")
        self.assertEqual(validation["status"], "passed")

    def test_corrects_fresh_localization_boolean(self) -> None:
        corrected, validation = validate_agent_answer(
            "当前定位状态无效。",
            {"name": "status_query"},
            context(requested=["localization"]),
        )

        self.assertEqual(corrected, "当前定位有效。")
        self.assertEqual(validation["checks"]["numeric_consistency"], "corrected")

    def test_rejects_completion_claim_when_verification_is_pending(self) -> None:
        corrected, validation = validate_agent_answer(
            "喷码机已经打开。",
            {"name": "printer_control"},
            context(),
            tool_results=[{
                "name": "printer_spray",
                "verification": {"status": "pending", "verified": False},
            }],
        )

        self.assertIn("尚未得到真实设备状态验证", corrected)
        self.assertEqual(validation["checks"]["tool_completion"], "corrected")

    def test_pending_confirmation_cannot_be_reported_as_completed(self) -> None:
        corrected, validation = validate_agent_answer(
            "任务已启动。",
            {"name": "mission_control"},
            context(),
            pending_action={"id": "pending-1"},
        )

        self.assertIn("尚未完成", corrected)
        self.assertTrue(validation["message_changed"])

    def test_removes_unsupported_obstacle_distance_claim(self) -> None:
        corrected, validation = validate_agent_answer(
            "设备就绪，周边最近障碍 0.82 米。请人工检查急停。",
            {"name": "motion_control"},
            context(requested=["motion"]),
        )

        self.assertNotIn("0.82", corrected)
        self.assertIn("未接入周边障碍检测", corrected)
        self.assertIn("人工确认作业区域", corrected)
        self.assertEqual(validation["status"], "corrected")

    def test_text_confirmation_without_pending_action_is_rejected(self) -> None:
        corrected, validation = validate_agent_answer(
            "请回复“确认执行”，我即提交该演示。",
            {"name": "motion_control"},
            context(requested=["motion"]),
        )

        self.assertEqual(corrected, "尚未创建可确认的操作，请重新提供具体运动参数。")
        self.assertEqual(validation["checks"]["tool_completion"], "corrected")

    def test_candidate_generation_claim_requires_real_variant_result(self) -> None:
        corrected, validation = validate_agent_answer(
            "候选方案已生成，请在方案区查看并选择。",
            {"name": "drawing_design", "operation": "modify"},
            context(),
            tool_results=[],
        )

        self.assertIn("候选方案尚未生成", corrected)
        self.assertEqual(validation["checks"]["tool_completion"], "corrected")

    def test_candidate_generation_claim_accepts_verified_variant_result(self) -> None:
        corrected, validation = validate_agent_answer(
            "候选方案已生成，请在方案区查看并选择。",
            {"name": "drawing_design", "operation": "modify"},
            context(),
            tool_results=[{
                "name": "persist_candidate_variant",
                "ok": True,
                "variant_id": "variant-2",
                "preview_paths": [{"points": [[0, 0], [1, 0]]}],
            }],
        )

        self.assertEqual(corrected, "候选方案已生成，请在方案区查看并选择。")
        self.assertEqual(validation["checks"]["tool_completion"], "passed")

    def test_internal_geometry_payload_is_hidden_from_chat(self) -> None:
        corrected, validation = validate_agent_answer(
            '仅根据几何条数估算实例数量。\n'
            '{"ok":true,"geometry_count":2,"preview_path_count":2,'
            '"printing_length_m":170.7,"topology":{"ok":true}}',
            {"name": "drawing_design", "operation": "create"},
            context(),
        )

        self.assertNotIn("geometry_count", corrected)
        self.assertNotIn("printing_length_m", corrected)
        self.assertIn("候选方案尚未生成", corrected)
        self.assertEqual(validation["checks"]["display_format"], "corrected")

    def test_removes_citation_not_present_in_retrieval_results(self) -> None:
        corrected, validation = validate_agent_answer(
            "规划接口不会直接启动小车 [K9]，详情见 [K1]。",
            {"name": "conversation"},
            context(),
            knowledge_source_ids={"K1"},
        )

        self.assertNotIn("[K9]", corrected)
        self.assertNotIn("[K1]", corrected)
        self.assertEqual(validation["checks"]["source_citations"], "corrected")

    def test_normalizes_markdown_internal_correction_and_paths_for_display(self) -> None:
        corrected, validation = validate_agent_answer(
            "**结论：** 建议先确认场地。\n\n"
            "（先更正上一轮：K3 实际是 xline_ws3/cad/parser.py，不能作为尺寸来源。）\n\n"
            "1. **分区顺序**：参考 D:\\xikao\\project\\layout.json 与 [K1]。",
            {"name": "drawing_design"},
            context(),
            knowledge_source_ids={"K1"},
        )

        self.assertEqual(
            corrected,
            "结论： 建议先确认场地。\n\n1. 分区顺序：参考 项目文件。",
        )
        self.assertNotIn("先更正", corrected)
        self.assertNotIn("**", corrected)
        self.assertNotIn("xline_ws3/", corrected)
        self.assertEqual(validation["checks"]["display_format"], "normalized")

    def test_compacts_greeting_closing_and_duplicate_blocks(self) -> None:
        corrected, validation = validate_agent_answer(
            "好的，我来为你分析一下：当前定位有效。\n\n"
            "当前定位有效。\n\n如有其他问题请随时告诉我。",
            {"name": "status_query"},
            context(requested=["localization"]),
        )

        self.assertEqual(corrected, "当前定位有效。")
        self.assertEqual(validation["checks"]["conciseness"], "compacted")


if __name__ == "__main__":
    unittest.main()
