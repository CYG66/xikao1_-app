from __future__ import annotations

import unittest
from copy import deepcopy

from app.cad_edit_chain import replay_cad_edit_chain
from app.cad_edit_contract import build_cad_edit_chain_contract
from app.cad_edit_plan import build_cad_edit_plan, repair_cad_edit_plan_once


class CadEditPlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = [
            {
                "id": 1,
                "type": "line",
                "layer_id": 1,
                "start": {"x": 0.0, "y": 0.0, "z": 0.0},
                "end": {"x": 1000.0, "y": 0.0, "z": 0.0},
                "template_instance": 1,
            },
            {
                "id": 2,
                "type": "line",
                "layer_id": 1,
                "start": {"x": 0.0, "y": 1000.0, "z": 0.0},
                "end": {"x": 1000.0, "y": 1000.0, "z": 0.0},
                "template_instance": 2,
            },
        ]
        self.contract = {
            "schema": "cad.edit.v2",
            "operation": "translate",
            "target": {"scope": "instance", "instance_ids": [2]},
            "coordinate_frame": "drawing",
            "parameters": {"dx_mm": 500.0, "dy_mm": 0.0},
        }

    def test_plan_resolves_instance_and_protects_non_target_geometry(self) -> None:
        target = deepcopy(self.source)
        target[1]["start"]["x"] += 500.0
        target[1]["end"]["x"] += 500.0

        plan = build_cad_edit_plan(self.source, target, self.contract)

        self.assertTrue(plan["verification"]["verified"], plan)
        self.assertEqual(plan["expected_changes"]["modified_geometry_ids"], [2])
        self.assertEqual(plan["expected_changes"]["protected_geometry_ids"], [1])

    def test_plan_rejects_non_target_geometry_drift(self) -> None:
        target = deepcopy(self.source)
        target[0]["end"]["x"] += 100.0
        target[1]["start"]["x"] += 500.0
        target[1]["end"]["x"] += 500.0

        plan = build_cad_edit_plan(self.source, target, self.contract)

        self.assertFalse(plan["verification"]["verified"])
        failures = {
            item["kind"] for item in plan["verification"]["failures"]
        }
        self.assertIn("exact_modified_ids", failures)
        self.assertIn("protected_geometries_unchanged", failures)

    def test_repairs_non_target_drift_once_from_failed_assertions(self) -> None:
        target = deepcopy(self.source)
        target[0]["end"]["x"] += 100.0
        target[1]["start"]["x"] += 500.0
        target[1]["end"]["x"] += 500.0
        failed = build_cad_edit_plan(self.source, target, self.contract)

        repaired, plan, evidence = repair_cad_edit_plan_once(
            self.source, target, self.contract, failed
        )

        self.assertTrue(evidence["attempted"])
        self.assertEqual(evidence["attempt_count"], 1)
        self.assertTrue(evidence["repaired"])
        self.assertEqual(evidence["actions"], [{
            "kind": "restore_source_geometries", "geometry_ids": [1],
        }])
        self.assertEqual(repaired[0], self.source[0])
        self.assertTrue(plan["verification"]["verified"], plan)
        self.assertEqual(plan["repair"]["attempt_count"], 1)

    def test_does_not_guess_a_missing_intended_modification(self) -> None:
        target = deepcopy(self.source)
        failed = build_cad_edit_plan(self.source, target, self.contract)

        repaired, plan, evidence = repair_cad_edit_plan_once(
            self.source, target, self.contract, failed
        )

        self.assertFalse(evidence["attempted"])
        self.assertEqual(evidence["reason"], "missing_intended_geometry_change")
        self.assertEqual(evidence["missing_modified_geometry_ids"], [2])
        self.assertEqual(repaired, target)
        self.assertFalse(plan["verification"]["verified"])

    def test_repair_limit_blocks_a_second_attempt(self) -> None:
        target = deepcopy(self.source)
        target[0]["end"]["x"] += 100.0
        target[1]["start"]["x"] += 500.0
        target[1]["end"]["x"] += 500.0
        failed = build_cad_edit_plan(self.source, target, self.contract)
        failed["repair"] = {"attempt_count": 1}

        _, plan, evidence = repair_cad_edit_plan_once(
            self.source, target, self.contract, failed
        )

        self.assertFalse(evidence["attempted"])
        self.assertEqual(evidence["reason"], "repair_limit_reached")
        self.assertEqual(evidence["attempt_count"], 1)
        self.assertFalse(plan["verification"]["verified"])

    def test_chain_failure_is_not_rewritten_by_single_step_repair(self) -> None:
        contract = build_cad_edit_chain_contract([
            {
                "operation": "translate", "instance": 2,
                "dx_mm": 500.0, "dy_mm": 0.0,
            },
            {
                "operation": "rotate", "instance": 2,
                "angle_degrees": 90.0, "pivot": "instance_center",
            },
        ], source_text="先平移再旋转")
        target, error, _ = replay_cad_edit_chain(self.source, contract)
        self.assertIsNone(error)
        self.assertIsNotNone(target)
        invalid_target = deepcopy(target)
        invalid_target[0]["end"]["x"] += 100.0
        failed = build_cad_edit_plan(self.source, invalid_target, contract)

        repaired, plan, evidence = repair_cad_edit_plan_once(
            self.source, invalid_target, contract, failed
        )

        self.assertFalse(evidence["attempted"])
        self.assertEqual(evidence["reason"], "unsupported_failed_assertion")
        self.assertIn("chain_result_exact", evidence["unsupported_failures"])
        self.assertEqual(repaired, invalid_target)
        self.assertFalse(plan["verification"]["verified"])


if __name__ == "__main__":
    unittest.main()
