from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.agent_service import robot_agent
from app.agent_skills import drawing_template_geometries, score_design_variant
from app.cad_counterfactual_guard import (
    validate_counterfactual_followup,
    validate_counterfactual_guard_report,
)
from app.cad_edit_contract import build_cad_edit_contract
from app.creative_projects import CreativeProjectStore
from app.drawing_store import preview_paths


def _contract(
    *,
    instance: int = 1,
    dx_mm: float = 2000.0,
    dy_mm: float = 0.0,
    operation: str = "translate",
    project_id: str = "project-1",
) -> dict[str, object]:
    edit: dict[str, object] = {
        "operation": operation,
        "instance": instance,
        "project_id": project_id,
        "parent_variant_id": "variant-1",
    }
    if operation == "translate":
        edit.update({"dx_mm": dx_mm, "dy_mm": dy_mm})
    elif operation == "rotate":
        edit.update({"angle_degrees": 30.0, "pivot": "instance_center"})
    return build_cad_edit_contract(edit, source_text="测试修改")


class CadCounterfactualGuardTest(unittest.TestCase):
    def test_independent_instruction_is_not_restricted(self) -> None:
        report = validate_counterfactual_followup(
            _contract(), _contract(instance=2), "第二个图形向右移动2米"
        )
        self.assertFalse(report["enforced"])
        self.assertTrue(report["verified"])
        self.assertEqual(report["reason"], "independent_instruction")
        self.assertEqual(len(report["current_contract_sha256"]), 64)

    def test_explicit_direction_and_distance_correction_passes(self) -> None:
        report = validate_counterfactual_followup(
            _contract(dx_mm=2000),
            _contract(dx_mm=-1000),
            "不是向右2米，是向左1米",
        )
        self.assertTrue(report["enforced"])
        self.assertTrue(report["verified"])
        self.assertEqual(report["changed_fields"], ["parameters.dx_mm"])

    def test_magnitude_only_correction_can_inherit_direction(self) -> None:
        report = validate_counterfactual_followup(
            _contract(dx_mm=2000), _contract(dx_mm=1000), "距离改成1米"
        )
        self.assertTrue(report["verified"])

    def test_silent_target_change_is_rejected(self) -> None:
        report = validate_counterfactual_followup(
            _contract(instance=1, dx_mm=2000),
            _contract(instance=2, dx_mm=1000),
            "距离改成1米",
        )
        self.assertFalse(report["verified"])
        self.assertIn("target", report["unsupported_changes"])

    def test_silent_distance_change_is_rejected(self) -> None:
        report = validate_counterfactual_followup(
            _contract(instance=1, dx_mm=2000),
            _contract(instance=2, dx_mm=1000),
            "改成第二个图形",
        )
        self.assertFalse(report["verified"])
        self.assertIn("parameters.dx_mm", report["unsupported_changes"])

    def test_silent_operation_change_is_rejected(self) -> None:
        report = validate_counterfactual_followup(
            _contract(), _contract(operation="rotate"), "参数改成30度"
        )
        self.assertFalse(report["verified"])
        self.assertIn("operation", report["unsupported_changes"])

    def test_explicit_target_change_passes(self) -> None:
        report = validate_counterfactual_followup(
            _contract(instance=1), _contract(instance=2), "改成第二个图形"
        )
        self.assertTrue(report["verified"])
        self.assertEqual(report["changed_fields"], ["target"])

    def test_project_drift_is_rejected(self) -> None:
        report = validate_counterfactual_followup(
            _contract(project_id="project-1"),
            _contract(project_id="project-2"),
            "再来一次",
        )
        self.assertFalse(report["verified"])
        self.assertIn("project_id", report["unsupported_changes"])

    def test_persisted_report_detects_contract_and_report_tampering(self) -> None:
        contract = _contract()
        report = validate_counterfactual_followup(None, contract, "第一个图形向右移动2米")
        contract["intent_grounding"] = {"counterfactual_guard": report}
        self.assertTrue(validate_counterfactual_guard_report(contract)["verified"])

        changed_contract = deepcopy(contract)
        changed_contract["parameters"]["dx_mm"] = 3000.0
        self.assertFalse(
            validate_counterfactual_guard_report(changed_contract)["verified"]
        )

        changed_report = deepcopy(contract)
        changed_report["intent_grounding"]["counterfactual_guard"][
            "reason"
        ] = "tampered"
        self.assertFalse(
            validate_counterfactual_guard_report(changed_report)["verified"]
        )

    def test_runtime_candidate_persists_guard_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "两个房间", "两个房间",
                {"shape": "room", "quantity": 2}, {}, [],
            )
            geometries = drawing_template_geometries({
                "template": "room", "quantity": 2,
                "width_m": 5, "height_m": 3,
            })
            parent = store.add_variant(
                project["id"], "初始", geometries, "初始候选",
                score_design_variant(geometries),
                preview_paths({"lines": geometries}),
            )
            store.begin_design_iteration(project["id"], parent["id"])
            route = robot_agent.resolve_intent(
                "第二个图形向右移动1米", "advanced", []
            )
            route["user_message"] = "第二个图形向右移动1米"
            route["object_memory"] = {
                "objects": {"project": [{"id": project["id"]}]},
                "last_cad_edit": None,
            }
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                result = robot_agent.chat(
                    "第二个图形向右移动1米", [], mode="advanced", route=route
                )

        self.assertTrue(result["ok"], result)
        guard = result["cad_edit_contract"]["intent_grounding"][
            "counterfactual_guard"
        ]
        self.assertTrue(guard["verified"])
        self.assertTrue(
            validate_counterfactual_guard_report(result["cad_edit_contract"])[
                "verified"
            ]
        )

    def test_runtime_rejects_silent_target_drift_without_new_variant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "两个房间", "两个房间",
                {"shape": "room", "quantity": 2}, {}, [],
            )
            geometries = drawing_template_geometries({
                "template": "room", "quantity": 2,
                "width_m": 5, "height_m": 3,
            })
            parent = store.add_variant(
                project["id"], "初始", geometries, "初始候选",
                score_design_variant(geometries),
                preview_paths({"lines": geometries}),
            )
            store.begin_design_iteration(project["id"], parent["id"])
            previous = build_cad_edit_contract({
                "operation": "translate", "instance": 1,
                "dx_mm": 2000.0, "dy_mm": 0.0,
                "project_id": project["id"],
                "parent_variant_id": parent["id"],
            }, source_text="第一个图形向右移动2米")
            route = robot_agent.resolve_intent(
                "第二个图形向右移动1米", "advanced", []
            )
            route["user_message"] = "距离改成1米"
            route["object_memory"] = {
                "objects": {"project": [{"id": project["id"]}]},
                "last_cad_edit": previous,
            }
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                result = robot_agent.chat(
                    "第二个图形向右移动1米", [], mode="advanced", route=route
                )
                updated = store.get(project["id"])

        self.assertTrue(result["clarification_required"])
        self.assertFalse(result["counterfactual_guard"]["verified"])
        self.assertEqual(len(updated["variants"]), 1)


if __name__ == "__main__":
    unittest.main()
