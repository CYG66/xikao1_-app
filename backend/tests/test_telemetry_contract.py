import unittest

from app.telemetry_contract import build_telemetry_contract


class TelemetryContractTests(unittest.TestCase):
    def test_marks_missing_vehicle_bms_as_unavailable(self):
        energy = build_telemetry_contract({})["energy"]

        self.assertFalse(energy["available"])
        self.assertEqual("vehicle_bms_not_publishing", energy["missing_reason"])

    def test_preserves_real_vehicle_bms_values(self):
        energy = build_telemetry_contract({
            "battery": 74,
            "battery_voltage": 51.2,
            "battery_current": 4.8,
            "battery_temperature": 31.0,
            "energy_source": "ros_battery_state",
            "energy_age_ms": 120,
        })["energy"]

        self.assertTrue(energy["available"])
        self.assertEqual("ros_battery_state", energy["source"])
        self.assertEqual(51.2, energy["voltage"])
        self.assertEqual(120, energy["age_ms"])


if __name__ == "__main__":
    unittest.main()
