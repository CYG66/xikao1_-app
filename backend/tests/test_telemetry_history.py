import tempfile
import unittest
from pathlib import Path

from app.database import XLineDatabase


class TelemetryHistoryTests(unittest.TestCase):
    def test_persisted_energy_and_safety_values_are_returned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = XLineDatabase(Path(directory) / "xline.db")
            database.record_telemetry({
                "battery": 72,
                "battery_voltage": 48.3,
                "battery_current": 3.2,
                "battery_temperature": 31.0,
                "telemetry_age_ms": 80,
                "linear_velocity": 0.1,
                "localization_valid": True,
                "emergency_stopped": False,
                "control_ready": True,
            })

            samples = database.telemetry_history(minutes=60, limit=100)

            self.assertEqual(1, len(samples))
            self.assertEqual(72, samples[0]["battery_percent"])
            self.assertEqual(48.3, samples[0]["voltage"])
            self.assertTrue(samples[0]["localization_valid"])
            self.assertFalse(samples[0]["emergency_stopped"])

    def test_history_range_and_limit_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = XLineDatabase(Path(directory) / "xline.db")
            self.assertEqual([], database.telemetry_history(minutes=-1, limit=-1))


if __name__ == "__main__":
    unittest.main()
