from __future__ import annotations

import unittest

from app.route_optimization_comparison import (
    attach_ros2_result,
    build_route_optimization_comparison,
)


def _line(geometry_id: int, start: tuple[float, float], end: tuple[float, float]) -> dict:
    return {
        "id": geometry_id,
        "type": "line",
        "start": {"x": start[0] * 1000, "y": start[1] * 1000, "z": 0},
        "end": {"x": end[0] * 1000, "y": end[1] * 1000, "z": 0},
        "role": "printing",
    }


class RouteOptimizationComparisonTest(unittest.TestCase):
    def test_reorders_and_reverses_paths_without_marking_them_executable(self) -> None:
        comparison = build_route_optimization_comparison([
            _line(1, (10, 0), (11, 0)),
            _line(2, (2, 0), (1, 0)),
            _line(3, (5, 0), (6, 0)),
        ])

        self.assertEqual(comparison["status"], "advisory_ready")
        self.assertFalse(comparison["execution_allowed"])
        self.assertEqual(
            [item["geometry_id"] for item in comparison["advisory"]["order"]],
            [2, 3, 1],
        )
        self.assertTrue(comparison["advisory"]["order"][0]["reversed"])
        self.assertLess(
            comparison["advisory"]["transition_length_m"],
            comparison["baseline"]["transition_length_m"],
        )

    def test_attaches_ros2_metrics_without_claiming_execution_authority(self) -> None:
        comparison = build_route_optimization_comparison([
            _line(1, (0, 0), (1, 0)),
            _line(2, (3, 0), (4, 0)),
        ])
        result = attach_ros2_result(
            comparison,
            {"travel_length_m": 2.5, "total_length_m": 4.5},
        )

        self.assertEqual(result["ros2_result"]["transition_length_m"], 2.5)
        self.assertIn("不能", result["ros2_result"]["note"])
        self.assertFalse(result["execution_allowed"])

    def test_empty_drawing_is_explicitly_unavailable(self) -> None:
        comparison = build_route_optimization_comparison([])

        self.assertEqual(comparison["status"], "not_available")
        self.assertEqual(comparison["reason"], "no_printing_paths")


if __name__ == "__main__":
    unittest.main()
