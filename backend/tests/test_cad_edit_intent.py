from __future__ import annotations

import unittest

from app.cad_edit_contract import build_cad_edit_contract, cad_edit_contract_to_edit
from app.cad_edit_intent import build_cad_edit_intent, cad_edit_intent_clarification
from app.cad_edit_plan import build_cad_edit_plan
from app.incremental_cad import parse_constrained_addition, parse_incremental_edit


class CadEditIntentTest(unittest.TestCase):
    def test_translate_has_separated_target_operation_and_parameters(self) -> None:
        text = "第二个篮球场向右移动2米"
        parsed = parse_incremental_edit(text)
        self.assertIsNotNone(parsed)

        intent = build_cad_edit_intent(text, parsed or {})

        self.assertEqual(intent["target"]["scope"], "instance")
        self.assertEqual(intent["target"]["instance_ids"], [2])
        self.assertEqual(intent["operation"], "translate")
        self.assertEqual(intent["parameters"]["dx_mm"], 2000.0)
        self.assertEqual(intent["parameters"]["dy_mm"], 0.0)
        self.assertEqual(intent["missing_parameters"], [])

    def test_duplicate_without_placement_asks_one_key_question(self) -> None:
        text = "复制第一个图形"
        intent = build_cad_edit_intent(text, parse_incremental_edit(text) or {})

        self.assertEqual(intent["operation"], "duplicate")
        self.assertEqual(
            intent["missing_parameters"],
            ["direction", "distance_mm", "placement"],
        )
        self.assertEqual(
            cad_edit_intent_clarification(intent),
            "请说明复制到目标图形的哪个方向。",
        )

    def test_align_separates_reference_from_target(self) -> None:
        text = "让第二个图形与第一个左对齐"
        intent = build_cad_edit_intent(text, parse_incremental_edit(text) or {})

        self.assertEqual(intent["target"]["instance_ids"], [2])
        self.assertEqual(intent["parameters"]["reference_instance"], 1)
        self.assertEqual(intent["parameters"]["alignment"], "左")
        self.assertEqual(intent["missing_parameters"], [])

    def test_constrained_addition_is_machine_readable(self) -> None:
        text = "在篮球场上下各添加矩形，与篮球场相连，外侧两个顶点在外圆上，尺寸由系统判断"
        parsed = parse_constrained_addition(text)
        self.assertIsNotNone(parsed)

        intent = build_cad_edit_intent(text, parsed or {})

        self.assertEqual(intent["operation"], "add_constrained")
        self.assertEqual(intent["target"]["scope"], "selector")
        self.assertEqual(intent["missing_parameters"], [])
        self.assertIn(
            {"kind": "symmetry", "axis": "target_horizontal_centerline"},
            intent["constraints"],
        )
        self.assertEqual(intent["auto_decisions"], [{
            "parameter": "rectangle.dimensions",
            "policy": "auto_optimize",
            "objective": "maximize_area",
        }])

    def test_contract_and_plan_preserve_intent_evidence(self) -> None:
        edit = {
            "operation": "translate",
            "instance": 2,
            "dx_mm": 500.0,
            "dy_mm": 0.0,
            "intent_schema": "cad.edit-intent.v1",
            "constraints": [{"kind": "keep_others_unchanged"}],
            "missing_parameters": [],
            "auto_decisions": [{"parameter": "axis", "policy": "drawing"}],
            "assumptions": ["向右按图纸坐标解释"],
        }
        contract = build_cad_edit_contract(edit, source_text="第二个图形向右移动0.5米")
        restored = cad_edit_contract_to_edit(contract)
        source = [
            {"id": 1, "type": "line", "template_instance": 1,
             "start": {"x": 0.0, "y": 0.0}, "end": {"x": 1.0, "y": 0.0}},
            {"id": 2, "type": "line", "template_instance": 2,
             "start": {"x": 0.0, "y": 1.0}, "end": {"x": 1.0, "y": 1.0}},
        ]
        target = [dict(source[0]), {
            **source[1],
            "start": {"x": 500.0, "y": 1.0},
            "end": {"x": 501.0, "y": 1.0},
        }]
        plan = build_cad_edit_plan(source, target, contract)

        self.assertEqual(restored["intent_schema"], "cad.edit-intent.v1")
        self.assertEqual(plan["constraints"], edit["constraints"])
        self.assertEqual(plan["auto_decisions"], edit["auto_decisions"])
        self.assertTrue(plan["verification"]["verified"], plan)


if __name__ == "__main__":
    unittest.main()
