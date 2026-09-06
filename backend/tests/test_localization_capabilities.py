from __future__ import annotations

import unittest
from unittest.mock import patch

from app.main import handle_rosbridge_payload
from app.ros_adapter import ros_adapter
from app.state import robot_state


class LocalizationCapabilityTest(unittest.TestCase):
    def test_calibration_is_rejected_when_ros_service_is_unavailable(self) -> None:
        payload = {
            "op": "call_service",
            "service": "/localization/calibrate_pose",
            "client_id": "app-client",
        }
        with (
            patch.object(robot_state, "bridge_mode", "virtual_ros2"),
            patch.object(robot_state, "localization_calibration_available", False),
            patch.object(ros_adapter, "owns_control", return_value=True),
            patch.object(ros_adapter, "calibrate_localization") as calibrate,
        ):
            result = handle_rosbridge_payload(payload)

        self.assertFalse(result["ok"])
        self.assertIn("没有校准或原点重置服务", result["message"])
        calibrate.assert_not_called()

    def test_calibration_calls_ros_only_when_service_is_available(self) -> None:
        payload = {
            "op": "call_service",
            "service": "/localization/calibrate_pose",
            "client_id": "app-client",
        }
        with (
            patch.object(robot_state, "localization_calibration_available", True),
            patch.object(ros_adapter, "owns_control", return_value=True),
            patch.object(ros_adapter, "calibrate_localization", return_value=True) as calibrate,
        ):
            result = handle_rosbridge_payload(payload)

        self.assertTrue(result["ok"])
        calibrate.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
