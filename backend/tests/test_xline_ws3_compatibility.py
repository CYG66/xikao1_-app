from __future__ import annotations

import unittest
from unittest.mock import patch
from pathlib import Path
import time

import app.ros_adapter as ros_adapter_module
from app.config import (
    BACKEND_NODE_NAME,
    MAX_LINEAR_VELOCITY,
    MAX_TASK_LINEAR_VELOCITY,
    MAX_MOTOR_RPM,
    CMD_VEL_TIMEOUT_SEC,
    DEFAULT_LINEAR_VELOCITY,
    PLANNED_RESULTS_DIR,
    SUPPORTED_PRINTERS,
    XLINE_SETUP_FILE,
    XLINE_WS_DIR,
    RUNTIME_PROFILE,
)
from app.schemas import PrinterCommand
from app.ros_adapter import RobotBackendNode, hardware_runtime_command
from app.state import robot_state


class XlineWs3RuntimeTest(unittest.TestCase):
    def test_defaults_use_current_workspace(self) -> None:
        self.assertEqual(XLINE_WS_DIR, "/home/qingz/xline_ws3")
        self.assertEqual(XLINE_SETUP_FILE, "/home/qingz/xline_ws3/install/setup.bash")
        self.assertEqual(
            PLANNED_RESULTS_DIR,
            "/home/qingz/xline_ws3/other/planned_results",
        )
        self.assertEqual(MAX_LINEAR_VELOCITY, 1.00)
        self.assertEqual(DEFAULT_LINEAR_VELOCITY, 0.10)
        self.assertEqual(MAX_TASK_LINEAR_VELOCITY, 0.10)
        self.assertEqual(MAX_MOTOR_RPM, 500.0)
        self.assertEqual(CMD_VEL_TIMEOUT_SEC, 0.50)
        self.assertEqual(BACKEND_NODE_NAME, "xline_app_backend1")
        self.assertEqual(RUNTIME_PROFILE, "xline_ws3")
        self.assertEqual(SUPPORTED_PRINTERS, ("center",))

    def test_total_station_runtime_explicitly_enables_hardware(self) -> None:
        with patch.object(ros_adapter_module, "USE_TOTAL_STATION", True):
            command = hardware_runtime_command()

        self.assertIn("system_test.launch.py", command)
        self.assertIn("export XLINE_WS_ROOT=/home/qingz/xline_ws3", command)
        self.assertIn("enable_hardware:=true", command)
        self.assertNotIn("use_total_station:=", command)

    def test_relative_runtime_keeps_planner_and_executor_persistent(self) -> None:
        with (
            patch.object(ros_adapter_module, "USE_TOTAL_STATION", False),
            patch.object(ros_adapter_module, "ENABLE_PRINTER", True),
        ):
            command = hardware_runtime_command()

        self.assertIn("shape_painting_system.launch.py", command)
        self.assertIn("export XLINE_WS_ROOT=/home/qingz/xline_ws3", command)
        self.assertIn("enable_printer:=true", command)
        self.assertIn("xline_path_planner planner_node", command)
        self.assertIn("xline_base_controller base_controller_node", command)
        self.assertNotIn("trajectory_painter shape_painter ", command)

    def test_backend_launcher_does_not_modify_ros_workspace(self) -> None:
        launcher = (
            Path(__file__).resolve().parents[1] / "run_robot_backend.sh"
        ).read_text(encoding="utf-8")

        self.assertNotIn("install -m", launcher)
        self.assertNotIn("rm -f", launcher)
        self.assertIn("cd /home/qingz/xline_app_backend1", launcher)

    def test_systemd_unit_uses_independent_ws3_backend_directory(self) -> None:
        unit = (
            Path(__file__).resolve().parents[1] / "xline-app-backend1.service"
        ).read_text(encoding="utf-8")

        self.assertIn("WorkingDirectory=/home/qingz/xline_app_backend1", unit)
        self.assertIn("ExecStart=/home/qingz/xline_app_backend1/", unit)
        self.assertIn("Wants=network-online.target xline-ws3-runtime.service", unit)
        self.assertIn("After=network-online.target xline-ws3-runtime.service", unit)
        self.assertNotIn("xline-cyg", unit)

    def test_ws3_runtime_is_an_independent_restartable_service(self) -> None:
        backend_root = Path(__file__).resolve().parents[1]
        unit = (backend_root / "xline-ws3-runtime.service").read_text(
            encoding="utf-8"
        )
        launcher = (backend_root / "run_ws3_runtime.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("ExecStart=/home/qingz/xline_app_backend1/run_ws3_runtime.sh", unit)
        self.assertIn("Restart=always", unit)
        self.assertIn("KillMode=control-group", unit)
        self.assertIn("shape_painting_system.launch.py", launcher)
        self.assertIn("xline_path_planner planner_node", launcher)
        self.assertIn("xline_base_controller base_controller_node", launcher)

    def test_backend_switch_script_is_removed(self) -> None:
        script = Path(__file__).resolve().parents[1] / "switch_xline_backend.sh"
        self.assertFalse(script.exists())

    def test_public_printer_api_accepts_only_physical_center_head(self) -> None:
        self.assertEqual(PrinterCommand(client_id="app", printer_name="center").printer_name, "center")
        with self.assertRaises(ValueError):
            PrinterCommand(client_id="app", printer_name="left")


class XlineWs3ReadinessTest(unittest.TestCase):
    def setUp(self) -> None:
        robot_state.printer_status = {}
        robot_state.printer_status_updated_at = 0.0
        self.node = object.__new__(RobotBackendNode)
        self.node.calibration_client = None

    def test_controller_cannot_impersonate_wheel_driver(self) -> None:
        self.node.get_node_names = lambda: [
            "base_controller",
            "cmd_vel_mux",
            "localization",
            "path_planner",
        ]
        with patch.object(RobotBackendNode, "_socketcan_ready", return_value=True):
            self.node._update_graph_readiness()

        self.assertFalse(robot_state.motor_driver_ready)
        self.assertFalse(robot_state.control_ready)
        self.assertFalse(robot_state.mission_nodes_ready)
        self.assertIn("differential_wheels_driver", robot_state.missing_required_nodes)

    def test_final_ws3_node_names_report_mission_runtime_ready(self) -> None:
        self.node.get_node_names = lambda: [
            "differential_wheels_driver",
            "cmd_vel_mux",
            "drawing_planner_node",
            "motion_control_center",
            "odom_imu_localization",
        ]
        with patch.object(RobotBackendNode, "_socketcan_ready", return_value=True):
            self.node._update_graph_readiness()

        self.assertTrue(robot_state.control_ready)
        self.assertTrue(robot_state.mission_nodes_ready)
        self.assertEqual(robot_state.missing_required_nodes, [])

    def test_relative_planning_uses_runtime_startup_origin(self) -> None:
        robot_state.localization_source = "odom_imu_relative"
        robot_state.localization_valid = True
        robot_state.robot_pose = {"frame_id": "map", "x": 0.4, "y": 0.2, "theta": 0.1}

        self.assertTrue(self.node._reset_relative_origin_for_planning())
        self.assertEqual(robot_state.localization_calibration, "startup_origin")

    def test_stale_printer_status_cannot_report_ready(self) -> None:
        self.node.get_node_names = lambda: ["inkjet_printer_node"]
        robot_state.printer_status = {
            "printer_center": {"connected": True, "enabled": True}
        }
        robot_state.printer_status_updated_at = time.time() - 6.0
        with patch.object(RobotBackendNode, "_socketcan_ready", return_value=False):
            self.node._update_graph_readiness()
        self.assertFalse(robot_state.printer_ready)


class PrinterCommandCompatibilityTest(unittest.TestCase):
    class FakeFuture:
        pass

    class FakeClient:
        def __init__(self) -> None:
            self.request = None

        def service_is_ready(self) -> bool:
            return True

        def call_async(self, request):
            self.request = request
            return PrinterCommandCompatibilityTest.FakeFuture()

    class FakePrinterCommand:
        class Request:
            def __init__(self) -> None:
                self.printer_name = ""
                self.command = ""
                self.json_data = ""

    def test_raw_printer_command_preserves_protocol_code(self) -> None:
        node = object.__new__(RobotBackendNode)
        node.printer_command_client = self.FakeClient()
        with patch.object(
            ros_adapter_module, "PrinterCommand", self.FakePrinterCommand
        ):
            accepted = node.send_printer_command(
                "center",
                "0x34",
                '{"PrintMode":{"interval":2.0}}',
            )

        self.assertTrue(accepted)
        self.assertEqual(node.printer_command_client.request.command, "0x34")
        self.assertEqual(node.printer_command_client.request.printer_name, "center")


class PrinterTelemetryCompatibilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.node = object.__new__(RobotBackendNode)
        robot_state.printer_status = {
            "printer_center": {
                "connected": True,
                "enabled": True,
                "device_state": 1,
                "print_count": 10,
            }
        }

    def test_print_confirmation_requires_counter_growth_and_ready_state(self) -> None:
        self.assertFalse(self.node._printer_trigger_confirmed("center", 10))
        robot_state.printer_status["printer_center"]["print_count"] = 11
        self.assertTrue(self.node._printer_trigger_confirmed("center", 10))
        robot_state.printer_status["printer_center"]["device_state"] = 0
        self.assertFalse(self.node._printer_trigger_confirmed("center", 10))

    def test_missing_counter_fails_closed(self) -> None:
        robot_state.printer_status["printer_center"]["print_count"] = None
        self.assertFalse(self.node._printer_trigger_confirmed("center", None))

    def test_wait_for_printer_active_uses_reported_enabled_state(self) -> None:
        adapter = object.__new__(ros_adapter_module.RobotRosAdapter)

        self.assertTrue(adapter.wait_for_printer_active("center", True, timeout=0))
        self.assertFalse(adapter.wait_for_printer_active("center", False, timeout=0))


if __name__ == "__main__":
    unittest.main()
