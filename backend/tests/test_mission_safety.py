from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.mission_analysis import analyze_mission
from app.mission_ledger import MissionLedgerStore
import app.ros_adapter as ros_adapter_module
from app.ros_adapter import RobotBackendNode, classify_planned_segment
from app.state import robot_state


def line(segment_id: int, *, printing: bool, start_x: float, end_x: float) -> dict:
    return {
        "id": segment_id,
        "type": "line",
        "layer_id": 1 if printing else 1_000_000,
        "work": printing,
        "start": {"x": start_x, "y": 0.0},
        "end": {"x": end_x, "y": 0.0},
        "ink": {"enabled": printing, "printer": "center", "mode": "solid"},
    }


class MissionAnalysisTest(unittest.TestCase):
    def test_summary_counts_printing_and_travel_lengths(self) -> None:
        segments = [
            line(1, printing=True, start_x=0, end_x=1000),
            line(1_000_000, printing=False, start_x=1000, end_x=1500),
        ]
        summary, validation = analyze_mission(
            segments, classify_planned_segment, localization_source="odom_imu_relative"
        )
        self.assertTrue(validation["ok"])
        self.assertEqual(summary["printing_segment_count"], 1)
        self.assertEqual(summary["travel_segment_count"], 1)
        self.assertEqual(summary["printing_length_m"], 1.0)
        self.assertEqual(summary["travel_length_m"], 0.5)
        self.assertEqual(summary["required_printers"], ["center"])
        self.assertTrue(validation["warnings"])

    def test_malformed_printing_segment_is_rejected(self) -> None:
        malformed = line(1, printing=True, start_x=0, end_x=1000)
        malformed["ink"] = {"enabled": False, "printer": "center"}
        # Force printing semantics while preserving an invalid ink payload.
        malformed["work"] = True
        malformed["layer_id"] = 1
        _, validation = analyze_mission([malformed], classify_planned_segment)
        self.assertFalse(validation["ok"])
        self.assertTrue(any("喷墨配置" in item for item in validation["errors"]))


class MissionLedgerTest(unittest.TestCase):
    def test_segment_completion_persists_and_restart_interrupts_running(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            store = MissionLedgerStore(path)
            mission = store.create(
                "drawing.json", {"segment_count": 1},
                [line(1, printing=True, start_x=0, end_x=1000)],
                classify_planned_segment,
            )
            mission_id = mission["id"]
            store.set_mission_state(mission_id, "executing")
            store.start_segment(mission_id, 0)
            restored = MissionLedgerStore(path).get(mission_id)
            self.assertEqual(restored["state"], "interrupted")
            self.assertEqual(restored["segments"][0]["state"], "interrupted")

            completed = MissionLedgerStore(Path(directory) / "completed.json")
            item = completed.create(
                "drawing.json", {}, [line(2, printing=True, start_x=0, end_x=1000)],
                classify_planned_segment,
            )
            completed.verify_segment(item["id"], 0, {"ok": True})
            self.assertEqual(
                MissionLedgerStore(completed.path).get(item["id"])["segments"][0]["state"],
                "completed",
            )


class SegmentVerificationTest(unittest.TestCase):
    def setUp(self) -> None:
        robot_state.emergency_stopped = False
        robot_state.localization_valid = True
        robot_state.last_pose_update_at = time.time()
        robot_state.robot_pose = {"x": 1.0, "y": 0.0}
        robot_state.printer_status = {
            "printer_center": {
                "connected": True,
                "is_online": True,
                "enabled": True,
            }
        }
        self.node = object.__new__(RobotBackendNode)
        self.node._mission_feedback_id = 1

    def test_printing_segment_fails_when_printer_disconnects(self) -> None:
        robot_state.printer_status["printer_center"]["connected"] = False
        result = self.node._verify_completed_segment(
            line(1, printing=True, start_x=0, end_x=1000)
        )
        self.assertFalse(result["ok"])
        self.assertTrue(any("已断开" in item for item in result["errors"]))

    def test_endpoint_mismatch_fails(self) -> None:
        robot_state.robot_pose = {"x": 0.0, "y": 0.0}
        result = self.node._verify_completed_segment(
            line(1, printing=True, start_x=0, end_x=1000)
        )
        self.assertFalse(result["ok"])
        self.assertGreater(result["endpoint_error_m"], 0.35)

    def test_travel_segment_does_not_require_printer(self) -> None:
        robot_state.printer_status = {}
        self.node._mission_feedback_id = 1_000_000
        result = self.node._verify_completed_segment(
            line(1_000_000, printing=False, start_x=0, end_x=1000)
        )
        self.assertTrue(result["ok"])


class PrinterTestPrintLifecycleTest(unittest.TestCase):
    class FakeFuture:
        def __init__(self, response=None, error=None):
            self.response = response
            self.error = error
            self.callbacks = []

        def add_done_callback(self, callback):
            self.callbacks.append(callback)
            return self

        def result(self):
            if self.error is not None:
                raise self.error
            return self.response

        def complete(self):
            for callback in list(self.callbacks):
                callback(self)

    class FakeClient:
        def __init__(self, response):
            self.response = response
            self.requests = []
            self.futures = []

        def call_async(self, request):
            self.requests.append(request)
            if request.action == "simulate":
                status = robot_state.printer_status["printer_center"]
                status["print_count"] = int(status.get("print_count", 0)) + 1
            future = PrinterTestPrintLifecycleTest.FakeFuture(self.response)
            self.futures.append(future)
            return future

    class FakeQuickCommand:
        class Request:
            def __init__(self):
                self.printer_name = ""
                self.action = ""
                self.param = 0

    class FakePrinterCommand:
        class Request:
            def __init__(self):
                self.printer_name = ""
                self.command = ""
                self.json_data = ""

    class ImmediateFuture(FakeFuture):
        def add_done_callback(self, callback):
            callback(self)
            return self

    class ImmediateClient:
        def __init__(self, response, *, count_simulate=False):
            self.response = response
            self.count_simulate = count_simulate
            self.requests = []

        def wait_for_service(self, timeout_sec=0.0):
            return True

        def call_async(self, request):
            self.requests.append(request)
            if self.count_simulate and getattr(request, "action", "") == "simulate":
                status = robot_state.printer_status["printer_center"]
                status["print_count"] = int(status["print_count"]) + 1
                status["device_state"] = 1
            return PrinterTestPrintLifecycleTest.ImmediateFuture(self.response)

    def setUp(self):
        robot_state.printer_status = {
            "printer_center": {
                "connected": True,
                "is_online": True,
                "enabled": True,
                "device_state": 1,
                "print_count": 10,
            }
        }
        self.node = object.__new__(RobotBackendNode)
        self.node._printer_test_stop_timers = {}
        self.node._printer_test_stop_generations = {}
        self.node._manual_spraying = set()
        self.node._manual_spray_states = {}
        self.node._manual_spray_errors = {}
        self.node._manual_spray_prepared = set()
        import threading
        self.node._printer_test_stop_lock = threading.Lock()

    def wait_for(self, predicate, timeout=1.0):
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return predicate()

    def test_successful_test_print_schedules_stop(self):
        client = self.FakeClient(type("Response", (), {"success": True, "message": "ok"})())
        self.node.printer_client = client
        with patch.object(ros_adapter_module, "QuickCommand", self.FakeQuickCommand):
            self.assertTrue(self.node.call_printer("center", "test_print", 0))
            client.futures[0].complete()
            self.assertTrue(
                self.wait_for(lambda: "center" in self.node._printer_test_stop_timers)
            )
            timer = self.node._printer_test_stop_timers["center"]
            timer.cancel()
            self.node._auto_stop_test_print("center", 1)
        self.assertEqual(
            [request.action for request in client.requests],
            ["test_print", "simulate", "stop_print"],
        )

    def test_connected_printer_does_not_require_ping_flag(self):
        robot_state.printer_status["printer_center"]["is_online"] = False
        client = self.FakeClient(type("Response", (), {"success": True, "message": "ok"})())
        self.node.printer_client = client
        with patch.object(ros_adapter_module, "QuickCommand", self.FakeQuickCommand):
            self.assertTrue(self.node.call_printer("center", "test_print", 0))

    def test_stop_print_cancels_pending_auto_stop(self):
        client = self.FakeClient(type("Response", (), {"success": True, "message": "ok"})())
        self.node.printer_client = client
        with patch.object(ros_adapter_module, "QuickCommand", self.FakeQuickCommand):
            self.node.call_printer("center", "test_print", 0)
            client.futures[0].complete()
        self.assertTrue(
            self.wait_for(lambda: "center" in self.node._printer_test_stop_timers)
        )
        with patch.object(ros_adapter_module, "QuickCommand", self.FakeQuickCommand):
            self.assertTrue(self.node.call_printer("center", "stop_print", 0))
        self.assertNotIn("center", self.node._printer_test_stop_timers)
        self.assertEqual(
            [request.action for request in client.requests],
            ["test_print", "simulate", "stop_print"],
        )

    def test_failed_test_print_does_not_schedule_stop(self):
        client = self.FakeClient(type("Response", (), {"success": False, "message": "failed"})())
        self.node.printer_client = client
        with patch.object(ros_adapter_module, "QuickCommand", self.FakeQuickCommand):
            self.node.call_printer("center", "test_print", 0)
        client.futures[0].complete()
        self.assertNotIn("center", self.node._printer_test_stop_timers)

    def test_manual_spray_loads_content_without_auto_stop(self):
        client = self.FakeClient(type("Response", (), {"success": True, "message": "ok"})())
        self.node.printer_client = client
        with patch.object(ros_adapter_module, "QuickCommand", self.FakeQuickCommand):
            self.assertTrue(
                self.node.call_printer(
                    "center",
                    "test_print",
                    0,
                    auto_stop_test_print=False,
                    manual_spray=True,
                )
            )
            client.futures[0].complete()

        self.assertTrue(
            self.wait_for(lambda: "center" in self.node._manual_spraying)
        )

        self.assertEqual(
            [request.action for request in client.requests],
            ["test_print", "simulate"],
        )
        self.assertNotIn("center", self.node._printer_test_stop_timers)
        self.assertIn("center", self.node._manual_spraying)
        self.assertTrue(robot_state.printer_status["printer_center"]["spraying"])

    def test_manual_spray_accepts_trigger_when_ws3_counters_are_unavailable(self):
        status = robot_state.printer_status["printer_center"]
        status.pop("print_count", None)
        status.pop("device_state", None)
        client = self.FakeClient(type("Response", (), {"success": True, "message": "ok"})())
        self.node.printer_client = client

        with patch.object(ros_adapter_module, "QuickCommand", self.FakeQuickCommand):
            self.assertTrue(
                self.node.call_printer(
                    "center",
                    "test_print",
                    0,
                    auto_stop_test_print=False,
                    manual_spray=True,
                )
            )
            client.futures[0].complete()
            self.assertTrue(
                self.wait_for(lambda: "center" in self.node._manual_spraying)
            )
        self.assertEqual(
            [request.action for request in client.requests],
            ["test_print", "simulate", "simulate"],
        )
        self.assertEqual(status["spray_state"], "triggered_unverified")
        self.assertEqual(status["spray_error"], "")

    def test_stop_cancels_second_unverified_trigger(self):
        status = robot_state.printer_status["printer_center"]
        status.pop("print_count", None)
        status.pop("device_state", None)
        client = self.FakeClient(type("Response", (), {"success": True, "message": "ok"})())
        self.node.printer_client = client

        with patch.object(ros_adapter_module, "QuickCommand", self.FakeQuickCommand):
            self.assertTrue(
                self.node.call_printer(
                    "center",
                    "test_print",
                    0,
                    auto_stop_test_print=False,
                    manual_spray=True,
                )
            )
            client.futures[0].complete()
            self.assertTrue(self.wait_for(lambda: len(client.requests) >= 2))
            self.node._cancel_test_print_auto_stop("center")

        import time

        time.sleep(0.4)
        self.assertEqual(
            [request.action for request in client.requests],
            ["test_print", "simulate"],
        )
        self.assertNotIn("center", self.node._manual_spraying)

    def test_failed_spray_state_survives_stop_cleanup(self):
        self.node.set_manual_spray_state("center", "error", "喷墨确认失败")
        self.node.set_manual_spraying("center", False, preserve_state=True)

        status = robot_state.printer_status["printer_center"]
        self.assertFalse(status["spraying"])
        self.assertEqual(status["spray_state"], "error")
        self.assertEqual(status["spray_error"], "喷墨确认失败")

    def test_manual_line_spray_uses_ws3_payload_and_confirms_counter(self):
        response = type("Response", (), {"success": True, "message": "ok"})()
        quick_client = self.ImmediateClient(response, count_simulate=True)
        command_client = self.ImmediateClient(response)
        self.node.printer_client = quick_client
        self.node.printer_command_client = command_client

        with (
            patch.object(ros_adapter_module, "QuickCommand", self.FakeQuickCommand),
            patch.object(ros_adapter_module, "PrinterCommand", self.FakePrinterCommand),
            patch.object(ros_adapter_module.time, "sleep", return_value=None),
        ):
            self.assertTrue(self.node.start_manual_line_spray("center"))

        self.assertEqual(
            [request.action for request in quick_client.requests],
            ["stop_print", "start_print", "simulate"],
        )
        self.assertEqual(
            [request.command for request in command_client.requests],
            ["0x34", "0x54", "0x34"],
        )
        self.assertIn("center", self.node._manual_spray_prepared)
        self.assertIn("center", self.node._manual_spraying)
        self.assertEqual(
            robot_state.printer_status["printer_center"]["spray_state"], "spraying"
        )

    def test_service_wait_times_out_instead_of_hanging(self):
        future = self.FakeFuture(
            type("Response", (), {"success": True, "message": "late"})()
        )
        ok, message = self.node._wait_service_response(future, 0.01)
        self.assertFalse(ok)
        self.assertIn("超时", message)


class AgentMotionPrinterLifecycleTest(unittest.TestCase):
    class FakeNode:
        def __init__(self) -> None:
            self.velocities = []
            self.printer_actions = []

        def publish_velocity(self, linear, angular) -> None:
            self.velocities.append((linear, angular))

        def call_printer(self, printer_name, action, param) -> None:
            self.printer_actions.append((printer_name, action, param))

        def set_manual_spraying(self, printer_name, spraying) -> None:
            pass

    def setUp(self) -> None:
        self.adapter = object.__new__(ros_adapter_module.RobotRosAdapter)
        self.adapter.stop_timer = None
        self.adapter.command_watchdog = None
        self.adapter.motion_sequence = [{"linear": 0.1, "angular": 0.0}]
        self.adapter.motion_sequence_index = 1
        self.adapter.motion_step_deadline = time.time()
        self.adapter.node = self.FakeNode()
        robot_state.agent_motion_active = True
        robot_state.agent_motion_deadline = time.time()
        robot_state.agent_motion_command = {"linear": 0.1}
        robot_state.printer_status = {
            "printer_center": {
                "connected": True,
                "enabled": True,
                "spraying": True,
                "spray_state": "triggered_unverified",
            }
        }

    def test_normal_motion_completion_preserves_manual_spray(self) -> None:
        self.adapter._complete_agent_motion("test completed")

        self.assertFalse(robot_state.agent_motion_active)
        self.assertEqual(self.adapter.node.velocities, [(0.0, 0.0)])
        self.assertEqual(self.adapter.node.printer_actions, [])
        self.assertTrue(robot_state.printer_status["printer_center"]["spraying"])

    def test_fail_safe_still_stops_manual_spray(self) -> None:
        self.adapter.fail_safe_stop("test safety loss")

        self.assertEqual(
            self.adapter.node.printer_actions,
            [("center", "stop_print", 0)],
        )


if __name__ == "__main__":
    unittest.main()
