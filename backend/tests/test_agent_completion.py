from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.drawing_versions import DrawingVersionStore
from app.mission_ledger import MissionLedgerStore
from app.mission_quality import score_planned_mission
from app.mission_reports import build_acceptance_report
from app.oscillation import HeadingOscillationDetector


def printing(segment_id: int, start: tuple[int, int], end: tuple[int, int]) -> dict:
    return {"id": segment_id, "type": "line", "work": True,
            "start": {"x": start[0], "y": start[1]}, "end": {"x": end[0], "y": end[1]},
            "ink": {"enabled": True, "printer": "center"}}


class DrawingVersionTest(unittest.TestCase):
    def test_same_name_creates_immutable_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = DrawingVersionStore(root / "versions.json")
            first = store.save(root, "court.json", {"lines": [1]}, "app")
            second = store.save(root, "court.json", {"lines": [2]}, "agent")
            self.assertEqual(first["file_name"], "court_v001.json")
            self.assertEqual(second["file_name"], "court_v002.json")
            self.assertEqual(len(store.list(first["drawing_id"])), 2)
            self.assertNotEqual(first["sha256"], second["sha256"])


class PlanningQualityTest(unittest.TestCase):
    def test_real_segments_drive_quality_metrics(self) -> None:
        segments = [printing(1, (0, 0), (1000, 0)), printing(2, (1000, 0), (0, 0))]
        summary = {"printing_length_m": 2, "travel_length_m": 0,
                   "duplicate_ink_paths_filtered": 1}
        quality = score_planned_mission(segments, summary, {"errors": [], "warnings": []})
        self.assertEqual(quality["metrics"]["sharp_turns"], 1)
        self.assertEqual(quality["metrics"]["duplicate_ink_paths"], 1)
        self.assertLess(quality["score"], 100)


class OscillationTest(unittest.TestCase):
    def test_repeated_heading_reversal_without_progress_is_detected(self) -> None:
        detector = HeadingOscillationDetector()
        event = None
        for index, angular in enumerate((0.3, -0.3, 0.3, -0.3, 0.3)):
            event = detector.add(index * 0.7, angular, 1.0, 1.0)
        self.assertIsNotNone(event)
        self.assertGreaterEqual(event["reversals"], 4)

    def test_reversal_with_forward_progress_is_not_detected(self) -> None:
        detector = HeadingOscillationDetector()
        event = None
        for index, angular in enumerate((0.3, -0.3, 0.3, -0.3, 0.3)):
            event = detector.add(index * 0.7, angular, index * 0.1, 0.0)
        self.assertIsNone(event)


class CheckpointAndReportTest(unittest.TestCase):
    def test_checkpoints_and_acceptance_report_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = MissionLedgerStore(Path(temporary) / "ledger.json")
            mission = store.create("court_v001.json", {}, [printing(1, (0, 0), (1000, 0))],
                                   lambda _: "printing", {"score": 92}, {"version": 1})
            store.record_precheck(mission["id"], 0, {"ok": True})
            store.start_segment(mission["id"], 0)
            store.verify_segment(mission["id"], 0, {"ok": True, "endpoint_error_m": 0.02,
                                                     "warnings": []})
            completed = store.get(mission["id"])
            report = build_acceptance_report(completed, "completed", "ln150_imu", [])
            store.set_report(mission["id"], report)
            persisted = MissionLedgerStore(Path(temporary) / "ledger.json").get(mission["id"])
            self.assertTrue(persisted["segments"][0]["precheck"]["ok"])
            self.assertTrue(persisted["segments"][0]["postcheck"]["ok"])
            self.assertEqual(persisted["report"]["verdict"], "accepted")


if __name__ == "__main__":
    unittest.main()
