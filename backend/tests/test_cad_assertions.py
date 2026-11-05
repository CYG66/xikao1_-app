from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from app.cad_assertions import (
    build_cad_machine_assertions,
    repair_cad_machine_assertions_once,
    validate_cad_machine_assertions,
)
from app.cad_edit_contract import build_cad_edit_contract
from app.cad_edit_plan import build_cad_edit_plan
from app.cad_edit_preview import build_cad_edit_preview
from app.creative_projects import CreativeProjectStore
from app.incremental_cad import edit_candidate_geometries


class CadMachineAssertionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = [
            {"id": 1, "type": "line", "template_instance": 1,
             "start": {"x": 0, "y": 0}, "end": {"x": 1000, "y": 0}},
            {"id": 2, "type": "line", "template_instance": 2,
             "start": {"x": 2000, "y": 0}, "end": {"x": 3000, "y": 0}},
        ]
        edit = {
            "operation": "translate", "instance": 2,
            "dx_mm": 1000.0, "dy_mm": 0.0,
            "project_id": "project-1", "parent_variant_id": "variant-1",
        }
        target, error = edit_candidate_geometries(self.source, edit)
        self.assertIsNone(error)
        self.target = target or []
        self.contract = build_cad_edit_contract(edit, source_text="第二个向右移动1米")
        self.plan = build_cad_edit_plan(self.source, self.target, self.contract)
        self.preview = build_cad_edit_preview(
            self.source, self.target, self.contract,
            target_resolution=edit.get("target_resolution"),
        )

    def test_all_blocking_assertions_pass_for_exact_candidate(self) -> None:
        report = build_cad_machine_assertions(
            self.source, self.target, self.contract, self.plan, self.preview,
        )

        self.assertEqual(report["schema"], "cad.machine-assertions.v1")
        self.assertTrue(report["blocking"])
        self.assertTrue(report["verified"], report)
        self.assertEqual(report["failure_codes"], [])
        self.assertEqual(len(report["assertions"]), 10)
        self.assertTrue(all(item["ok"] for item in report["assertions"]))

    def test_missing_version_binding_blocks_persistence(self) -> None:
        contract = deepcopy(self.contract)
        contract.pop("parent_variant_id", None)
        plan = build_cad_edit_plan(self.source, self.target, contract)
        preview = build_cad_edit_preview(self.source, self.target, contract)

        report = build_cad_machine_assertions(
            self.source, self.target, contract, plan, preview,
        )

        self.assertFalse(report["verified"])
        self.assertIn("version_binding", report["failure_codes"])

    def test_failed_edit_plan_blocks_persistence(self) -> None:
        plan = deepcopy(self.plan)
        plan["verification"]["verified"] = False

        report = build_cad_machine_assertions(
            self.source, self.target, self.contract, plan, self.preview,
        )

        self.assertFalse(report["verified"])
        self.assertIn("edit_plan", report["failure_codes"])

    def test_tampered_assertion_report_fails_revalidation(self) -> None:
        report = build_cad_machine_assertions(
            self.source, self.target, self.contract, self.plan, self.preview,
        )
        report["assertions"][0]["ok"] = False

        validation = validate_cad_machine_assertions(
            report,
            self.source,
            self.target,
            self.contract,
            self.plan,
            self.preview,
        )

        self.assertFalse(validation["verified"])
        self.assertEqual(validation["reason"], "machine_assertion_mismatch")
        self.assertNotEqual(
            validation["expected_report_sha256"],
            validation["supplied_report_sha256"],
        )

    def test_project_store_rejects_tampered_machine_assertions(self) -> None:
        with TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create("两条线", "移动第二条线")
            parent = store.add_variant(
                project["id"], "原始方案", self.source, "初始方案", {}, [],
            )
            source = parent["geometries"]
            edit = {
                "operation": "translate",
                "instance": 2,
                "dx_mm": 1000.0,
                "dy_mm": 0.0,
                "project_id": project["id"],
                "parent_variant_id": parent["id"],
            }
            target, error = edit_candidate_geometries(source, edit)
            self.assertIsNone(error)
            contract = build_cad_edit_contract(edit, source_text="第二个向右移动1米")
            plan = build_cad_edit_plan(source, target or [], contract)
            preview = build_cad_edit_preview(source, target or [], contract)
            report = build_cad_machine_assertions(
                source, target or [], contract, plan, preview,
            )
            report["assertions"][0]["ok"] = False

            candidate = store.add_variant(
                project["id"],
                "篡改候选",
                target or [],
                "不应保存",
                {},
                [],
                parent_variant_id=parent["id"],
                edit_contract=contract,
                edit_plan=plan,
                edit_preview=preview,
                machine_assertions=report,
            )

            self.assertIsNone(candidate)
            self.assertEqual(len(store.get(project["id"])["variants"]), 1)

    def test_recovers_one_non_target_drift_and_reruns_all_assertions(self) -> None:
        drifted = deepcopy(self.target)
        drifted[0]["end"]["x"] += 125.0
        plan = build_cad_edit_plan(self.source, drifted, self.contract)
        preview = build_cad_edit_preview(self.source, drifted, self.contract)
        report = build_cad_machine_assertions(
            self.source, drifted, self.contract, plan, preview,
        )

        repaired, final_plan, final_preview, final_report, recovery = (
            repair_cad_machine_assertions_once(
                self.source, drifted, self.contract, plan, preview, report,
            )
        )

        self.assertTrue(recovery["attempted"])
        self.assertEqual(recovery["attempt_count"], 1)
        self.assertTrue(recovery["recovered"])
        self.assertEqual(repaired, self.target)
        self.assertTrue(final_plan["verification"]["verified"])
        self.assertTrue(final_report["verified"])
        self.assertEqual(final_report["failure_codes"], [])
        self.assertEqual(
            final_preview["candidate"]["geometry_sha256"],
            final_report["candidate_geometry_sha256"],
        )

    def test_does_not_repair_version_binding_failure(self) -> None:
        contract = deepcopy(self.contract)
        contract.pop("parent_variant_id", None)
        plan = build_cad_edit_plan(self.source, self.target, contract)
        preview = build_cad_edit_preview(self.source, self.target, contract)
        report = build_cad_machine_assertions(
            self.source, self.target, contract, plan, preview,
        )

        _, _, _, final_report, recovery = repair_cad_machine_assertions_once(
            self.source, self.target, contract, plan, preview, report,
        )

        self.assertFalse(recovery["attempted"])
        self.assertEqual(
            recovery["reason"], "unsupported_machine_assertion_failure",
        )
        self.assertIn("version_binding", recovery["unsupported_failure_codes"])
        self.assertFalse(final_report["verified"])

    def test_does_not_replace_a_mismatched_preview(self) -> None:
        preview = deepcopy(self.preview)
        preview["candidate"]["geometry_sha256"] = "0" * 64
        report = build_cad_machine_assertions(
            self.source, self.target, self.contract, self.plan, preview,
        )

        _, _, final_preview, final_report, recovery = (
            repair_cad_machine_assertions_once(
                self.source,
                self.target,
                self.contract,
                self.plan,
                preview,
                report,
            )
        )

        self.assertFalse(recovery["attempted"])
        self.assertIn("preview_exact", recovery["unsupported_failure_codes"])
        self.assertEqual(final_preview, preview)
        self.assertFalse(final_report["verified"])

    def test_machine_recovery_never_attempts_twice(self) -> None:
        drifted = deepcopy(self.target)
        drifted[0]["end"]["x"] += 125.0
        plan = build_cad_edit_plan(self.source, drifted, self.contract)
        plan["repair"] = {"attempt_count": 1}
        preview = build_cad_edit_preview(self.source, drifted, self.contract)
        report = build_cad_machine_assertions(
            self.source, drifted, self.contract, plan, preview,
        )

        _, final_plan, _, final_report, recovery = (
            repair_cad_machine_assertions_once(
                self.source,
                drifted,
                self.contract,
                plan,
                preview,
                report,
            )
        )

        self.assertFalse(recovery["attempted"])
        self.assertEqual(recovery["attempt_count"], 1)
        self.assertEqual(recovery["reason"], "repair_limit_reached")
        self.assertFalse(final_plan["verification"]["verified"])
        self.assertFalse(final_report["verified"])


if __name__ == "__main__":
    unittest.main()
