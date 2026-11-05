from __future__ import annotations

import unittest

from app.trajectory_comparison import compare_trajectories


class TrajectoryComparisonTest(unittest.TestCase):
    def test_parallel_actual_trace_reports_deviation(self) -> None:
        result = compare_trajectories(
            [{"points": [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]}],
            [[0.0, 0.1], [1.0, 0.1], [2.0, 0.1]],
        )

        self.assertTrue(result["available"])
        self.assertAlmostEqual(result["mean_deviation_m"], 0.1)
        self.assertAlmostEqual(result["endpoint_error_m"], 0.1)
        self.assertEqual(result["planned_vertex_coverage"], 1.0)

    def test_missing_trace_is_explicitly_unavailable(self) -> None:
        result = compare_trajectories([{"points": [[0, 0], [1, 0]]}], [])

        self.assertFalse(result["available"])
        self.assertIn("不足", result["reason"])


if __name__ == "__main__":
    unittest.main()
