from __future__ import annotations

import unittest
from copy import deepcopy
import tempfile
from pathlib import Path

from app.cad_edit_contract import build_cad_edit_contract
from app.cad_edit_gate import build_cad_edit_preflight
from app.cad_edit_preview import build_cad_edit_preview, validate_cad_edit_preview
from app.incremental_cad import edit_candidate_geometries
from app.creative_projects import CreativeProjectStore
from app.agent_skills import score_design_variant
from app.drawing_store import preview_paths


class CadEditPreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = [
            {"id": 1, "type": "line", "template_instance": 1,
             "start": {"x": 0, "y": 0}, "end": {"x": 1000, "y": 0}},
            {"id": 2, "type": "line", "template_instance": 2,
             "start": {"x": 2000, "y": 0}, "end": {"x": 3000, "y": 0}},
        ]
        self.edit = {
            "operation": "translate", "instance": 2,
            "dx_mm": 1000.0, "dy_mm": 0.0,
        }
        target, error = edit_candidate_geometries(self.source, self.edit)
        self.assertIsNone(error)
        self.target = target or []
        self.contract = build_cad_edit_contract(self.edit, source_text="第二个向右移动1米")

    def test_preview_records_exact_working_copy_and_verifies(self) -> None:
        preflight = build_cad_edit_preflight(
            self.source, self.target, self.contract,
        )
        preview = build_cad_edit_preview(
            self.source,
            self.target,
            self.contract,
            preflight=preflight,
            target_resolution=self.edit.get("target_resolution"),
        )
        validation = validate_cad_edit_preview(
            preview, self.source, self.target, self.contract,
            preflight=preflight,
        )

        self.assertEqual(preview["schema"], "cad.edit-preview.v1")
        self.assertTrue(preview["review_only"])
        self.assertEqual(preview["changes"]["modified_geometry_ids"], [2])
        self.assertEqual(preview["changes"]["counts"]["modified"], 1)
        self.assertTrue(preview["path_impact"]["requires_replan"])
        self.assertFalse(preview["execution"]["persisted"])
        self.assertFalse(preview["execution"]["execution_allowed"])
        self.assertTrue(validation["verified"], validation)

    def test_preview_rejects_geometry_changed_after_review(self) -> None:
        preview = build_cad_edit_preview(
            self.source, self.target, self.contract,
        )
        changed = deepcopy(self.target)
        changed[1]["end"]["x"] += 1

        validation = validate_cad_edit_preview(
            preview, self.source, changed, self.contract,
        )

        self.assertFalse(validation["verified"])
        self.assertEqual(validation["reason"], "preview_result_mismatch")
        self.assertNotEqual(
            validation["expected_preview_sha256"],
            validation["actual_preview_sha256"],
        )

    def test_preview_rejects_contract_changed_after_review(self) -> None:
        preview = build_cad_edit_preview(
            self.source, self.target, self.contract,
        )
        changed_contract = deepcopy(self.contract)
        changed_contract["parameters"]["dx_mm"] = 2000.0

        validation = validate_cad_edit_preview(
            preview, self.source, self.target, changed_contract,
        )

        self.assertFalse(validation["verified"])
        self.assertEqual(validation["reason"], "preview_result_mismatch")

    def test_project_store_rejects_tampered_preview(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "预演校验", "两个图形", {"shape": "custom", "quantity": 2}, {}, [],
            )
            parent = store.add_variant(
                project["id"], "原方案", self.source, "原始图纸",
                score_design_variant(self.source),
                preview_paths({"lines": self.source}),
            )
            self.assertIsNotNone(parent)
            store.begin_design_iteration(project["id"], parent["id"])
            preview = build_cad_edit_preview(
                self.source, self.target, self.contract,
            )
            preview["candidate"]["geometry_sha256"] = "0" * 64

            saved = store.add_variant(
                project["id"], "伪造预演", self.target, "不应保存",
                score_design_variant(self.target),
                preview_paths({"lines": self.target}),
                parent_variant_id=parent["id"],
                edit_contract=self.contract,
                edit_preview=preview,
            )

        self.assertIsNone(saved)


if __name__ == "__main__":
    unittest.main()
