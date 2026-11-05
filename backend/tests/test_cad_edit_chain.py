from __future__ import annotations

import unittest

from app.cad_edit_chain import parse_incremental_edit_chain, replay_cad_edit_chain
from app.cad_edit_contract import build_cad_edit_chain_contract
from app.cad_edit_gate import build_cad_edit_preflight
from app.cad_edit_plan import build_cad_edit_plan


class CadEditChainTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = [
            {
                "id": 1, "type": "line", "layer_id": 1, "template_instance": 1,
                "start": {"x": 0.0, "y": 0.0, "z": 0.0},
                "end": {"x": 1000.0, "y": 0.0, "z": 0.0},
            },
            {
                "id": 2, "type": "line", "layer_id": 1, "template_instance": 2,
                "start": {"x": 2000.0, "y": 0.0, "z": 0.0},
                "end": {"x": 3000.0, "y": 0.0, "z": 0.0},
            },
        ]

    def test_parses_target_inheritance_and_preserves_order(self) -> None:
        edits = parse_incremental_edit_chain(
            "先把第二个图形向右移动2米，然后逆时针旋转90度"
        )

        self.assertIsNotNone(edits)
        self.assertEqual([item["operation"] for item in edits or []], [
            "translate", "rotate",
        ])
        self.assertEqual([item["instance"] for item in edits or []], [2, 2])

    def test_allows_explicit_target_switch_and_inherits_latest_target(self) -> None:
        edits = parse_incremental_edit_chain(
            "先把第二个图形向右移动2米，然后把第一个图形旋转90度，"
            "再向上移动1米"
        )

        self.assertIsNotNone(edits)
        self.assertEqual(
            [item["instance"] for item in edits or []], [2, 1, 1]
        )

    def test_contract_uses_target_union_and_replays_each_explicit_target(self) -> None:
        edits = parse_incremental_edit_chain(
            "先把第二个图形向右移动2米，然后把第一个图形逆时针旋转90度"
        ) or []
        contract = build_cad_edit_chain_contract(edits, source_text="复合修改")

        target, error, replay = replay_cad_edit_chain(self.source, contract)

        self.assertIsNone(error)
        self.assertEqual(contract["target"]["instance_ids"], [1, 2])
        self.assertEqual(
            [step["target"]["instance_ids"] for step in contract["chain_steps"]],
            [[2], [1]],
        )
        self.assertEqual(len(replay), 2)
        self.assertNotEqual((target or [])[0], self.source[0])
        self.assertNotEqual((target or [])[1], self.source[1])

    def test_rejects_step_target_outside_declared_chain_union(self) -> None:
        edits = parse_incremental_edit_chain(
            "先把第二个图形向右移动2米，然后把第一个图形逆时针旋转90度"
        ) or []
        contract = build_cad_edit_chain_contract(edits, source_text="复合修改")
        contract["target"]["instance_ids"] = [1]

        target, error, replay = replay_cad_edit_chain(self.source, contract)

        self.assertIsNone(target)
        self.assertIn("target union", error or "")
        self.assertEqual(replay, [])

    def test_replays_chain_and_verifies_each_step_and_final_result(self) -> None:
        edits = parse_incremental_edit_chain(
            "先把第二个图形向右移动2米，然后逆时针旋转90度"
        ) or []
        contract = build_cad_edit_chain_contract(
            edits, source_text="先把第二个图形向右移动2米，然后逆时针旋转90度"
        )

        target, error, replay = replay_cad_edit_chain(self.source, contract)
        self.assertIsNone(error)
        self.assertIsNotNone(target)
        plan = build_cad_edit_plan(self.source, target or [], contract)
        preflight = build_cad_edit_preflight(self.source, target or [], contract)

        self.assertEqual(contract["operation"], "chain")
        self.assertEqual(len(replay), 2)
        self.assertTrue(all(
            item["verification"]["verified"] for item in replay
        ))
        self.assertTrue(all(
            item["input_fingerprint"] and item["output_fingerprint"]
            for item in replay
        ))
        self.assertEqual(len(plan["steps"]), 2)
        self.assertTrue(plan["verification"]["verified"], plan)
        self.assertTrue(preflight["ready"], preflight)
        self.assertEqual((target or [])[0], self.source[0])

    def test_failed_step_rolls_back_without_partial_result(self) -> None:
        edits = [
            {"operation": "translate", "instance": 2, "dx_mm": 2000.0, "dy_mm": 0.0},
            {"operation": "resize", "instance": 2, "dimension": "半径", "value_mm": 20.0},
        ]
        contract = build_cad_edit_chain_contract(edits, source_text="复合修改")

        target, error, replay = replay_cad_edit_chain(self.source, contract)

        self.assertIsNone(target)
        self.assertIn("第 2 步失败", error or "")
        self.assertEqual(len(replay), 1)
        self.assertEqual(self.source[1]["start"]["x"], 2000.0)

    def test_invariant_circle_rotation_is_verified_before_scaling(self) -> None:
        source = [{
            "id": 1, "type": "circle", "layer_id": 1,
            "center": {"x": 0.0, "y": 0.0, "z": 0.0},
            "radius": 100.0, "template_instance": 1,
        }]
        contract = build_cad_edit_chain_contract([
            {
                "operation": "rotate", "geometry_ids": [1],
                "angle_degrees": 90.0, "pivot": "instance_center",
            },
            {
                "operation": "scale", "geometry_ids": [1],
                "factor": 2.0, "pivot": "instance_center",
            },
        ], source_text="先旋转圆，再扩大圆")

        target, error, replay = replay_cad_edit_chain(source, contract)

        self.assertIsNone(error)
        self.assertEqual(target[0]['radius'], 200.0)
        self.assertEqual(len(replay), 2)
        self.assertTrue(replay[0]["verification"]["verified"])
        self.assertFalse(replay[0]['geometry_changed'])
        self.assertTrue(replay[0]['effect_validation']['verified'])
        self.assertTrue(replay[1]['geometry_changed'])
        self.assertEqual(source[0]["radius"], 100.0)


if __name__ == "__main__":
    unittest.main()
