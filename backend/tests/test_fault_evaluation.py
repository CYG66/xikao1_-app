from __future__ import annotations

import unittest

from app.fault_evaluation import evaluate_live_vehicle
from app.diagnostics import build_link_diagnosis


class LiveFaultEvaluationTest(unittest.TestCase):
    def test_healthy_runtime_has_no_failures(self) -> None:
        result = evaluate_live_vehicle({
            "online": True,
            "ros_available": True,
            "drive_device_connected": True,
            "motor_driver_ready": True,
            "emergency_stopped": False,
            "localization_valid": True,
            "energy_source": "ros_battery_state",
            "printer_status": {"printer_center": {"connected": True}},
            "mission_nodes_ready": True,
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["failure_count"], 0)

    def test_faults_are_structured_without_commands(self) -> None:
        result = evaluate_live_vehicle({
            "online": True,
            "ros_available": False,
            "drive_device_connected": False,
            "motor_driver_ready": False,
            "emergency_stopped": True,
            "localization_valid": False,
            "energy_source": "unavailable",
            "printer_status": {},
            "mission_nodes_ready": False,
        })
        self.assertFalse(result["ok"])
        self.assertTrue(result["read_only"])
        self.assertIn("can_connected", result["issue_codes"])
        self.assertIn("energy_telemetry", result["issue_codes"])

    def test_link_diagnosis_exposes_breakpoint_and_usable_features(self) -> None:
        result = build_link_diagnosis({
            "online": True,
            "ros_available": True,
            "drive_device_connected": False,
            "motor_driver_ready": False,
            "localization_valid": False,
            "energy_source": "unavailable",
            "printer_ready": False,
            "mission_nodes_ready": True,
        })
        self.assertEqual(result["breakpoint_code"], "ros2_can")
        self.assertIn("AI 对话", result["usable_features"])
        self.assertIn("图纸编辑与预览", result["usable_features"])
        self.assertNotIn("手动底盘控制", result["usable_features"])
        self.assertTrue(result["requires_human_action"])
