import unittest

from app.mission_reports import build_acceptance_report


class MissionReportTests(unittest.TestCase):
    def test_unexecuted_segments_with_null_checks_do_not_hide_failure_reason(self):
        report = build_acceptance_report(
            {
                "id": "mission-1",
                "segments": [
                    {
                        "state": "completed",
                        "postcheck": {"endpoint_error_m": 0.02, "warnings": []},
                    },
                    {"state": "pending", "postcheck": None, "verification": None},
                ],
            },
            "failed",
            "odom_imu_relative",
            [],
        )

        self.assertEqual("failed", report["verdict"])
        self.assertEqual(0.02, report["endpoint_error_m"]["maximum"])


if __name__ == "__main__":
    unittest.main()
