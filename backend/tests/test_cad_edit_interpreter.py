from __future__ import annotations

import unittest
import json

from app.cad_edit_interpreter import parse_structured_cad_interpretation
from app.agent_service import RobotAgentService


class CadEditInterpreterTest(unittest.TestCase):
    def test_converts_rule_missed_translation_to_existing_executor_shape(self) -> None:
        source = "请将第二个场地沿水平方向正向偏移2米"
        result = parse_structured_cad_interpretation({
            "schema_version": "cad.language-interpretation.v1",
            "is_cad_edit": True,
            "operation": "translate",
            "target": {"scope": "instance", "instance_ids": [2]},
            "parameters": {
                "dx_mm": 2000.0, "dy_mm": 0.0,
                "coordinate_frame": "drawing",
            },
            "assumptions": [],
            "constraints": [{"kind": "preserve_non_target"}],
            "evidence_text": ["第二个场地", "正向偏移2米"],
            "confidence": 0.94,
        }, source)

        self.assertIsNotNone(result)
        edit, intent = result or ({}, {})
        self.assertEqual(edit["instance"], 2)
        self.assertEqual(edit["dx_mm"], 2000.0)
        self.assertEqual(intent["operation"], "translate")
        self.assertEqual(intent["parser"], "model_structured_fallback")
        self.assertEqual(intent["missing_parameters"], [])
        self.assertTrue(intent["grounding"]["verified"])

    def test_rejects_model_generated_geometry(self) -> None:
        result = parse_structured_cad_interpretation({
            "schema_version": "cad.language-interpretation.v1",
            "is_cad_edit": True,
            "operation": "translate",
            "target": {"scope": "instance", "instance_ids": [1]},
            "parameters": {"dx_mm": 1000.0, "dy_mm": 0.0},
            "assumptions": [],
            "constraints": [{"kind": "force_point", "x": 1000, "y": 0}],
            "evidence_text": ["第一个图形", "移动1米"],
            "confidence": 0.9,
        }, "把第一个图形移动1米")

        self.assertIsNone(result)

    def test_rejects_operation_without_source_evidence(self) -> None:
        result = parse_structured_cad_interpretation({
            "schema_version": "cad.language-interpretation.v1",
            "is_cad_edit": True,
            "operation": "delete",
            "target": {"scope": "instance", "instance_ids": [1]},
            "parameters": {},
            "assumptions": [],
            "constraints": [],
            "evidence_text": ["第一个图形"],
            "confidence": 0.9,
        }, "查看第一个图形")

        self.assertIsNone(result)

    def test_ungrounded_instance_id_forces_zero_confidence(self) -> None:
        result = parse_structured_cad_interpretation({
            "schema_version": "cad.language-interpretation.v1",
            "is_cad_edit": True,
            "operation": "translate",
            "target": {"scope": "instance", "instance_ids": [3]},
            "parameters": {"dx_mm": 2000.0, "dy_mm": 0.0},
            "assumptions": [], "constraints": [],
            "evidence_text": ["第二个场地", "向右移动2米"],
            "confidence": 0.98,
        }, "把第二个场地向右移动2米")

        self.assertIsNotNone(result)
        _, intent = result or ({}, {})
        self.assertEqual(intent["confidence"], 0.0)
        self.assertFalse(intent["grounding"]["verified"])
        self.assertIn(
            "target.instance_ids",
            {item["claim"] for item in intent["grounding"]["failures"]},
        )

    def test_ungrounded_distance_forces_zero_confidence(self) -> None:
        result = parse_structured_cad_interpretation({
            "schema_version": "cad.language-interpretation.v1",
            "is_cad_edit": True,
            "operation": "translate",
            "target": {"scope": "instance", "instance_ids": [2]},
            "parameters": {"dx_mm": 3000.0, "dy_mm": 0.0},
            "assumptions": [], "constraints": [],
            "evidence_text": ["第二个场地", "向右移动2米"],
            "confidence": 0.98,
        }, "把第二个场地向右移动2米")

        self.assertIsNotNone(result)
        _, intent = result or ({}, {})
        self.assertEqual(intent["confidence"], 0.0)
        self.assertIn(
            "parameters.translation_distance",
            {item["claim"] for item in intent["grounding"]["failures"]},
        )

    def test_ungrounded_direction_forces_zero_confidence(self) -> None:
        result = parse_structured_cad_interpretation({
            "schema_version": "cad.language-interpretation.v1",
            "is_cad_edit": True,
            "operation": "translate",
            "target": {"scope": "instance", "instance_ids": [2]},
            "parameters": {"dx_mm": -2000.0, "dy_mm": 0.0},
            "assumptions": [], "constraints": [],
            "evidence_text": ["第二个场地", "向右移动2米"],
            "confidence": 0.98,
        }, "把第二个场地向右移动2米")

        self.assertIsNotNone(result)
        _, intent = result or ({}, {})
        self.assertEqual(intent["confidence"], 0.0)
        self.assertIn(
            "parameters.translation_direction",
            {item["claim"] for item in intent["grounding"]["failures"]},
        )

    def test_service_uses_structured_fallback_for_rule_missed_edit(self) -> None:
        service = object.__new__(RobotAgentService)
        service.mode = "deepseek"
        service.api_keys = {"deepseek": "test-key"}
        service._deepseek_request = lambda messages, tools, mode="advanced", **kwargs: {
            "choices": [{"message": {"content": json.dumps({
                "schema_version": "cad.language-interpretation.v1",
                "is_cad_edit": True,
                "operation": "translate",
                "target": {"scope": "instance", "instance_ids": [2]},
                "parameters": {
                    "dx_mm": 2000.0, "dy_mm": 0.0,
                    "coordinate_frame": "drawing",
                },
                "assumptions": [],
                "constraints": [],
                "evidence_text": ["第二个场地", "正向偏移2米"],
                "confidence": 0.94,
            }, ensure_ascii=False)}}],
        }
        route = {
            "name": "drawing_design",
            "tool_family": "cad",
            "operation": "modify",
            "decision_source": "rules",
        }

        resolved = service._structured_cad_edit_fallback(
            "请将第二个场地沿水平方向正向偏移2米", [], route, "advanced"
        )

        self.assertEqual(resolved["decision_source"], "incremental_cad_edit")
        self.assertEqual(resolved["resolved_edit"]["instance"], 2)
        self.assertEqual(resolved["resolved_edit"]["dx_mm"], 2000.0)

    def test_low_confidence_fallback_requires_clarification(self) -> None:
        service = object.__new__(RobotAgentService)
        service.mode = "deepseek"
        service.api_keys = {"deepseek": "test-key"}
        service._deepseek_request = lambda messages, tools, mode="advanced", **kwargs: {
            "choices": [{"message": {"content": json.dumps({
                "schema_version": "cad.language-interpretation.v1",
                "is_cad_edit": True,
                "operation": "translate",
                "target": {"scope": "instance", "instance_ids": [2]},
                "parameters": {"dx_mm": 2000.0, "dy_mm": 0.0},
                "assumptions": [],
                "constraints": [],
                "evidence_text": ["第二个场地", "正向偏移2米"],
                "confidence": 0.4,
            }, ensure_ascii=False)}}],
        }
        route = {
            "name": "drawing_design", "operation": "modify",
            "decision_source": "rules",
        }

        resolved = service._structured_cad_edit_fallback(
            "请将第二个场地沿水平方向正向偏移2米", [], route, "advanced"
        )

        self.assertTrue(resolved["clarification_required"])
        self.assertNotIn("resolved_edit", resolved)

    def test_high_model_confidence_cannot_override_failed_grounding(self) -> None:
        service = object.__new__(RobotAgentService)
        service.mode = "deepseek"
        service.api_keys = {"deepseek": "test-key"}
        service._deepseek_request = lambda messages, tools, mode="advanced", **kwargs: {
            "choices": [{"message": {"content": json.dumps({
                "schema_version": "cad.language-interpretation.v1",
                "is_cad_edit": True,
                "operation": "translate",
                "target": {"scope": "instance", "instance_ids": [3]},
                "parameters": {"dx_mm": 3000.0, "dy_mm": 0.0},
                "assumptions": [], "constraints": [],
                "evidence_text": ["第二个场地", "水平方向正向偏移2米"],
                "confidence": 0.99,
            }, ensure_ascii=False)}}],
        }
        route = {
            "name": "drawing_design", "operation": "modify",
            "decision_source": "rules",
        }

        resolved = service._structured_cad_edit_fallback(
            "把第二个场地沿水平方向正向偏移2米", [], route, "advanced"
        )

        self.assertTrue(resolved["clarification_required"])
        self.assertEqual(resolved["edit_intent"]["confidence"], 0.0)
        self.assertFalse(resolved["edit_intent"]["grounding"]["verified"])
        self.assertNotIn("resolved_edit", resolved)

    def test_unresolved_target_cannot_become_executable_edit(self) -> None:
        payload = {
            "schema_version": "cad.language-interpretation.v1",
            "is_cad_edit": True,
            "operation": "resize",
            "target": {"scope": "unresolved"},
            "parameters": {"dimension": "width", "value_mm": 30000},
            "assumptions": [],
            "constraints": [],
            "evidence_text": ["宽度改为30米"],
            "confidence": 0.99,
        }

        result = parse_structured_cad_interpretation(
            payload, "把它的宽度改为30米"
        )

        self.assertIsNotNone(result)
        _, intent = result or ({}, {})
        self.assertEqual(intent["confidence"], 0.0)
        self.assertIn(
            "target.resolved",
            {item["claim"] for item in intent["grounding"]["failures"]},
        )

    def test_rule_parsed_edit_never_calls_model_fallback(self) -> None:
        service = object.__new__(RobotAgentService)
        service.mode = "deepseek"
        service.api_keys = {"deepseek": "test-key"}
        service._deepseek_request = lambda *args, **kwargs: self.fail(
            "规则已解析时不应调用模型"
        )
        route = {
            "name": "drawing_design", "operation": "modify",
            "decision_source": "incremental_cad_edit",
        }

        resolved = service._structured_cad_edit_fallback(
            "第二个图形向右移动2米", [], route, "advanced"
        )

        self.assertIs(resolved, route)

    def test_rule_missed_cad_wording_reaches_modify_route(self) -> None:
        route = RobotAgentService.route_intent(
            "请将第二个场地沿水平方向正向偏移2米", "advanced"
        )

        self.assertEqual(route["name"], "drawing_design")
        self.assertEqual(route["operation"], "modify")

    def test_vehicle_offset_does_not_become_cad_edit(self) -> None:
        route = RobotAgentService.route_intent("让小车向右偏移2米", "advanced")

        self.assertNotEqual(route["name"], "drawing_design")


if __name__ == "__main__":
    unittest.main()
