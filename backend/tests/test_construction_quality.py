from __future__ import annotations

import unittest
from unittest.mock import patch

from app.construction_quality import analyze_construction_quality
from app.mission_quality import score_planned_mission
from app.mission_reports import build_acceptance_report


def line(segment_id: int, start: tuple[int, int], end: tuple[int, int]) -> dict:
    return {
        "id": segment_id,
        "type": "line",
        "work": True,
        "start": {"x": start[0], "y": start[1]},
        "end": {"x": end[0], "y": end[1]},
        "ink": {"enabled": True, "printer": "center"},
    }


class ConstructionQualityTests(unittest.TestCase):
    def test_diagnostics_apply_to_canonical_segments_from_any_source(self) -> None:
        diagnostics = analyze_construction_quality([
            line(1, (0, 0), (1000, 0)),
            line(2, (1200, 0), (200, 0)),
        ])

        self.assertEqual("all_drawing_sources", diagnostics["scope"])
        self.assertEqual(1, diagnostics["turns"]["sharp_turn_count"])
        self.assertAlmostEqual(0.2, diagnostics["junctions"]["maximum_gap_m"])
        self.assertEqual(1, diagnostics["junctions"]["warning_count"])
        self.assertEqual("planned_proxy_only", diagnostics["ink_quality"]["status"])
        self.assertFalse(diagnostics["ink_quality"]["real_measurement_available"])

    def test_circle_reports_analytical_curvature(self) -> None:
        diagnostics = analyze_construction_quality([{
            "id": 1,
            "type": "circle",
            "work": True,
            "center": {"x": 0, "y": 0},
            "radius": 500,
            "ink": {"enabled": True, "printer": "center"},
        }])

        self.assertEqual(2.0, diagnostics["curvature"]["maximum_per_m"])

    def test_nozzle_offset_is_reported_but_not_claimed_as_execution_compensation(self) -> None:
        with (
            patch("app.construction_quality.NOZZLE_OFFSET_FORWARD_M", 0.1),
            patch("app.construction_quality.NOZZLE_OFFSET_LATERAL_M", -0.02),
        ):
            diagnostics = analyze_construction_quality([
                line(1, (0, 0), (1000, 0)),
            ])

        nozzle = diagnostics["nozzle_offset"]
        self.assertTrue(nozzle["configured"])
        self.assertTrue(nozzle["diagnostic_only"])
        self.assertAlmostEqual(0.102, nozzle["magnitude_m"], places=3)

    def test_quality_and_acceptance_report_keep_diagnostics(self) -> None:
        segments = [line(1, (0, 0), (1000, 0))]
        quality = score_planned_mission(
            segments,
            {"printing_length_m": 1, "travel_length_m": 0},
            {"errors": [], "warnings": []},
        )
        report = build_acceptance_report(
            {
                "id": "mission-quality",
                "execution_mode": "virtual_sim",
                "quality": quality,
                "segments": [{"state": "completed", "postcheck": {"warnings": []}}],
            },
            "completed",
            "ln150_imu",
            [],
        )

        self.assertIn("construction_diagnostics", quality)
        self.assertEqual(
            "construction-quality-diagnostics.v1",
            report["construction_diagnostics"]["schema"],
        )
        self.assertEqual("accepted", report["verdict"])
        self.assertIn(
            "尚未配置喷头相对底盘偏移，无法验证喷头补偿",
            quality["construction_diagnostics"]["warnings"],
        )

    def test_real_execution_keeps_missing_nozzle_calibration_warning(self) -> None:
        quality = score_planned_mission(
            [line(1, (0, 0), (1000, 0))],
            {"printing_length_m": 1, "travel_length_m": 0},
            {"errors": [], "warnings": []},
        )
        report = build_acceptance_report(
            {
                "id": "real-mission-quality",
                "execution_mode": "ros2",
                "quality": quality,
                "segments": [{"state": "completed", "postcheck": {"warnings": []}}],
            },
            "completed",
            "ln150_imu",
            [],
        )

        self.assertEqual("accepted_with_warnings", report["verdict"])


if __name__ == "__main__":
    unittest.main()
