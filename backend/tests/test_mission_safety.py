from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from app.mission_analysis import analyze_mission
from app.mission_ledger import MissionLedgerStore
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
            "printer_center": {"connected": True, "enabled": True}
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


if __name__ == "__main__":
    unittest.main()
