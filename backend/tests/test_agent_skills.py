from __future__ import annotations

import unittest
from unittest.mock import patch

from app.agent_skills import (
    DRAWING_TEMPLATE_SKILLS,
    check_drawing_feasibility,
    clarify_requirements,
    drawing_template_motion_steps,
    layer_drawing_paths,
    parameterize_design,
    recommend_recovery,
    recognize_drawing_template,
    score_design_variant,
)
from app.state import robot_state


class AgentSkillsTest(unittest.TestCase):
    def test_every_drawing_editor_template_has_local_skill_and_motion_preview(self) -> None:
        for skill in DRAWING_TEMPLATE_SKILLS.values():
            match = recognize_drawing_template(skill["aliases"][0])
            self.assertIsNotNone(match)
            steps = drawing_template_motion_steps(match)
            self.assertGreaterEqual(len(steps), 2, skill["label"])

    def test_parameterization_reports_missing_printer(self) -> None:
        with patch.object(robot_state, "printer_status", {}):
            result = parameterize_design("画一个 5x3 米矩形")

        self.assertEqual(result["shape"], "rectangle")
        self.assertEqual(result["dimensions"], {"width_m": 5.0, "height_m": 3.0})
        self.assertIn("printer", result["missing"])

    def test_parameterization_uses_single_online_robot_printer(self) -> None:
        status = {
            "printer_center": {
                "connected": True,
                "is_online": True,
                "enabled": True,
                "device_id": 0,
            }
        }
        with patch.object(robot_state, "printer_status", status):
            result = parameterize_design("画一个半径 0.5 米的圆")

        self.assertEqual(result["printer"], "center")
        self.assertNotIn("printer", result["missing"])
        self.assertTrue(result["ok"])

    def test_clarification_returns_questions_for_missing_parameters(self) -> None:
        result = clarify_requirements("画一个矩形")

        self.assertFalse(result["ready_for_design"])
        self.assertIn("dimensions", result["missing"])
        self.assertTrue(result["questions"])

    def test_feasibility_rejects_degenerate_geometry(self) -> None:
        result = check_drawing_feasibility([
            {
                "id": 1,
                "type": "line",
                "layer_id": 1,
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 0, "y": 0, "z": 0},
            }
        ])

        self.assertFalse(result["ok"])
        self.assertTrue(result["errors"])

    def test_path_layering_leaves_travel_to_xline_planner(self) -> None:
        result = layer_drawing_paths([
            {
                "id": 1,
                "type": "line",
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 1000, "y": 0, "z": 0},
            }
        ], "center")

        self.assertEqual(result["layers"][0]["route_type"], "printing")
        self.assertEqual(result["layers"][0]["printer"], "center")
        self.assertEqual(result["travel_policy"], "generated_by_xline_ws3_planner")
        self.assertNotIn("travel_paths", result)

    def test_parameterization_rejects_nonexistent_side_printer(self) -> None:
        status = {
            "printer_center": {"connected": True, "enabled": True},
        }
        with patch.object(robot_state, "printer_status", status):
            result = parameterize_design("用左喷头画一个 5x3 米矩形")

        self.assertFalse(result["ok"])
        self.assertIn(
            "unsupported_printer:xline_ws3_only_has_center",
            result["missing"],
        )

    def test_design_score_is_not_reported_as_ros_planning_score(self) -> None:
        result = score_design_variant([{
            "id": 1, "type": "line", "layer_id": 1,
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 1000, "y": 0, "z": 0},
        }])

        self.assertEqual(result["score_type"], "design_only")
        self.assertTrue(result["requires_ros_planning_score"])

    def test_recovery_requires_stop_and_never_auto_resumes(self) -> None:
        result = recommend_recovery({
            "mission_running": True,
            "localization_valid": False,
            "control_ready": True,
            "printer_ready": True,
            "mission_required_printers": [],
            "obstacle_distances": {},
            "mission_error": "",
        })

        self.assertTrue(result["stop_required"])
        self.assertFalse(result["auto_resume_allowed"])
        self.assertTrue(result["reasons"])


if __name__ == "__main__":
    unittest.main()
