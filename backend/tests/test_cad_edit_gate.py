from __future__ import annotations

import unittest

from app.cad_edit_contract import CadEditCommand
from app.cad_edit_gate import build_cad_edit_preflight, validate_target_change_scope
from app.incremental_cad import edit_candidate_geometries


class CadEditGateTests(unittest.TestCase):
    @staticmethod
    def geometry(instance: int, geometry_id: int, x: float) -> dict:
        return {
            "id": geometry_id, "type": "line", "template_instance": instance,
            "start": {"x": x, "y": 0}, "end": {"x": x + 1000, "y": 0},
        }

    def test_normal_translation_is_ready_without_confirmation(self) -> None:
        source = [self.geometry(1, 1, 0), self.geometry(2, 2, 3000)]
        target = [self.geometry(1, 1, 0), self.geometry(2, 2, 5000)]
        result = build_cad_edit_preflight(source, target, {
            "operation": "translate",
            "target": {"scope": "instance", "instance_ids": [2]},
            "parameters": {"dx_mm": 2000, "dy_mm": 0},
        })
        self.assertTrue(result["ready"])
        self.assertEqual(result["risk_level"], "low")
        self.assertFalse(result["requires_confirmation"])

    def test_mass_delete_and_extreme_scale_require_confirmation(self) -> None:
        source = [self.geometry(index, index, index * 2000) for index in range(1, 5)]
        deletion = build_cad_edit_preflight(source, source[:1], {
            "operation": "retain",
            "target": {"scope": "instance", "instance_ids": [1]},
            "parameters": {},
        })
        self.assertTrue(deletion["ready"])
        self.assertTrue(deletion["requires_confirmation"])
        self.assertIn("删除范围超过原图一半", deletion["risk_reasons"])

        scaled = [self.geometry(1, 1, 0)]
        scaled[0]["end"]["x"] = 3000
        scale = build_cad_edit_preflight(source[:1], scaled, {
            "operation": "scale",
            "target": {"scope": "instance", "instance_ids": [1]},
            "parameters": {"factor": 3},
        })
        self.assertTrue(scale["requires_confirmation"])

    def test_noop_and_duplicate_ids_are_rejected(self) -> None:
        source = [self.geometry(1, 1, 0)]
        noop = build_cad_edit_preflight(source, source, {
            "operation": "translate", "parameters": {"dx_mm": 1, "dy_mm": 0},
        })
        self.assertFalse(noop["ready"])
        duplicate = [self.geometry(1, 1, 0), self.geometry(2, 1, 3000)]
        invalid = build_cad_edit_preflight(source, duplicate, {
            "operation": "duplicate", "parameters": {},
        })
        self.assertFalse(invalid["ready"])

    def test_non_target_change_is_rejected(self) -> None:
        source = [self.geometry(1, 1, 0), self.geometry(2, 2, 3000)]
        target = [self.geometry(1, 1, 2000), self.geometry(2, 2, 5000)]

        result = build_cad_edit_preflight(source, target, {
            "operation": "translate",
            "target": {"scope": "instance", "instance_ids": [2]},
            "parameters": {"dx_mm": 2000, "dy_mm": 0},
        })

        self.assertFalse(result["ready"])
        scope = result["scope_validation"]
        self.assertFalse(scope["ok"])
        self.assertEqual(scope["unexpected_existing_ids"], [1])

    def test_exact_hash_rejects_sub_millimetre_non_target_drift(self) -> None:
        source = [self.geometry(1, 1, 0), self.geometry(2, 2, 3000)]
        target = [self.geometry(1, 1, 0.0004), self.geometry(2, 2, 5000)]

        result = build_cad_edit_preflight(source, target, {
            "operation": "translate",
            "target": {"scope": "instance", "instance_ids": [2]},
            "parameters": {"dx_mm": 2000, "dy_mm": 0},
        })

        self.assertFalse(result["ready"])
        integrity = result["scope_validation"]["non_target_integrity"]
        self.assertFalse(integrity["verified"])
        self.assertEqual(integrity["mismatched_geometry_ids"], [1])
        self.assertNotEqual(integrity["source_hash_root"], integrity["target_hash_root"])

    def test_successful_target_edit_preserves_protected_hash_root(self) -> None:
        source = [self.geometry(1, 1, 0), self.geometry(2, 2, 3000)]
        target = [self.geometry(1, 1, 0), self.geometry(2, 2, 5000)]

        result = build_cad_edit_preflight(source, target, {
            "operation": "translate",
            "target": {"scope": "instance", "instance_ids": [2]},
            "parameters": {"dx_mm": 2000, "dy_mm": 0},
        })

        integrity = result["scope_validation"]["non_target_integrity"]
        self.assertTrue(integrity["verified"])
        self.assertEqual(integrity["protected_geometry_ids"], [1])
        self.assertEqual(integrity["source_hash_root"], integrity["target_hash_root"])

    def test_declared_translation_distance_must_match_actual_geometry(self) -> None:
        source = [self.geometry(1, 1, 0), self.geometry(2, 2, 3000)]
        target = [self.geometry(1, 1, 0), self.geometry(2, 2, 5000)]
        contract = {
            "schema": "cad.edit.v2",
            "operation": "translate",
            "target": {
                "scope": "instance", "instance_ids": [2], "geometry_ids": [],
            },
            "coordinate_frame": "drawing",
            "parameters": {"dx_mm": 1000, "dy_mm": 0},
        }

        result = build_cad_edit_preflight(source, target, contract)

        self.assertFalse(result["ready"])
        effect = result["effect_validation"]
        self.assertTrue(effect["enforced"])
        self.assertFalse(effect["verified"])
        self.assertEqual(effect["mismatched_geometry_ids"], [2])
        failed = {item["code"] for item in result["checks"] if not item["ok"]}
        self.assertIn("declared_edit_effect", failed)

    def test_declared_translation_replay_accepts_equivalent_numeric_types(self) -> None:
        source = [self.geometry(1, 1, 0), self.geometry(2, 2, 3000)]
        target = [self.geometry(1, 1, 0), self.geometry(2, 2, 5000.0)]
        contract = {
            "schema": "cad.edit.v2",
            "operation": "translate",
            "target": {
                "scope": "instance", "instance_ids": [2], "geometry_ids": [],
            },
            "coordinate_frame": "drawing",
            "parameters": {"dx_mm": 2000.0, "dy_mm": 0.0},
        }

        result = build_cad_edit_preflight(source, target, contract)

        self.assertTrue(result["ready"])
        self.assertTrue(result["effect_validation"]["verified"])
        self.assertEqual(
            result["effect_validation"]["expected_fingerprint"],
            result["effect_validation"]["actual_fingerprint"],
        )

    def test_patch_change_set_must_match_actual_diff_exactly(self) -> None:
        source = [self.geometry(1, 1, 0), self.geometry(1, 2, 2000)]
        target = [self.geometry(1, 1, 1000), self.geometry(1, 2, 2000)]

        valid = validate_target_change_scope(
            source,
            target,
            {"scope": "geometry", "geometry_ids": [1]},
            expected_modified_ids={1},
            expected_removed_ids=set(),
            expected_added_ids=set(),
        )
        mismatched = validate_target_change_scope(
            source,
            target,
            {"scope": "geometry", "geometry_ids": [1]},
            expected_modified_ids={1, 2},
            expected_removed_ids=set(),
            expected_added_ids=set(),
        )

        self.assertTrue(valid["ok"])
        self.assertFalse(mismatched["ok"])
        self.assertEqual(mismatched["operation_mismatch"]["modified"], [2])

    def test_split_shared_contract_rejects_incomplete_or_wrong_scope(self) -> None:
        base = {
            "schema": "cad.edit.v2", "operation": "translate",
            "target": {"scope": "logical_object", "geometry_ids": [1, 2],
                       "object_ids": ["space-1"]},
            "parameters": {"dx_mm": 1000, "dy_mm": 0,
                           "boundary_policy": "split_shared",
                           "shared_geometry_ids": [1],
                           "created_geometry_ids": [3]},
        }
        self.assertEqual(CadEditCommand.model_validate(base).operation, "translate")
        missing = {**base, "parameters": {**base["parameters"],
                                           "created_geometry_ids": []}}
        wrong_scope = {**base, "target": {"scope": "geometry",
                                            "geometry_ids": [1, 2]}}
        with self.assertRaises(ValueError):
            CadEditCommand.model_validate(missing)
        with self.assertRaises(ValueError):
            CadEditCommand.model_validate(wrong_scope)

    def test_split_shared_preflight_proves_created_boundary_origin(self) -> None:
        source = [self.geometry(1, 1, 0), self.geometry(1, 2, 2000)]
        edit = {
            "operation": "translate", "geometry_ids": [1, 2],
            "logical_object_ids": ["space-1"],
            "dx_mm": 1000.0, "dy_mm": 0.0,
            "boundary_policy": "split_shared", "shared_geometry_ids": [1],
        }
        target, error = edit_candidate_geometries(source, edit)
        self.assertIsNone(error)
        contract = {
            "schema": "cad.edit.v2", "operation": "translate",
            "target": {"scope": "logical_object", "instance_ids": [],
                       "geometry_ids": [1, 2], "object_ids": ["space-1"]},
            "coordinate_frame": "drawing",
            "parameters": {"dx_mm": 1000.0, "dy_mm": 0.0,
                           "boundary_policy": "split_shared",
                           "shared_geometry_ids": [1],
                           "created_geometry_ids": [3]},
        }
        valid = build_cad_edit_preflight(source, target, contract)
        self.assertTrue(valid["ready"], valid)
        self.assertTrue(valid["split_boundary_validation"]["verified"])

        forged = {**contract, "parameters": {
            **contract["parameters"], "created_geometry_ids": [4],
        }}
        rejected = build_cad_edit_preflight(source, target, forged)
        self.assertFalse(rejected["ready"])
        self.assertFalse(rejected["split_boundary_validation"]["verified"])
        self.assertIn("split_boundary_provenance", {
            item["code"] for item in rejected["checks"] if not item["ok"]
        })


if __name__ == "__main__":
    unittest.main()
