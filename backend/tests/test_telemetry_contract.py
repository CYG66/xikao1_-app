import unittest

from app.state import RobotState
from app.telemetry_contract import (
    build_mission_contract,
    build_status_packet,
    build_telemetry_contract,
)


class TelemetryContractTests(unittest.TestCase):
    def test_terminal_snapshot_clears_stale_runtime_lock(self):
        state = RobotState(
            mission_stage="cancelled",
            mission_running=True,
            mission_paused=True,
            mission_current_id=4,
        )

        snapshot = state.snapshot()

        self.assertFalse(snapshot["mission_running"])
        self.assertFalse(snapshot["mission_paused"])
        self.assertTrue(snapshot["mission_terminal"])
        self.assertIsNone(snapshot["mission_current_id"])
        self.assertFalse(state.mission_running)
        self.assertFalse(state.mission_paused)

    def test_mission_contract_normalizes_stale_terminal_flags(self):
        mission = build_mission_contract({
            "mission_stage": "failed",
            "mission_running": True,
            "mission_paused": True,
            "mission_current_id": 8,
        })

        self.assertTrue(mission["terminal"])
        self.assertFalse(mission["active"])
        self.assertFalse(mission["running"])
        self.assertFalse(mission["paused"])
        self.assertIsNone(mission["current_segment"])

    def test_paused_mission_remains_active(self):
        mission = build_mission_contract({
            "mission_stage": "paused",
            "mission_running": True,
            "mission_paused": True,
        })

        self.assertTrue(mission["active"])
        self.assertTrue(mission["running"])
        self.assertTrue(mission["paused"])
        self.assertFalse(mission["terminal"])

    def test_status_packet_exposes_one_normalized_mission_contract(self):
        packet = build_status_packet({
            "mission_stage": "completed",
            "mission_running": True,
            "mission_paused": True,
        })

        self.assertFalse(packet["mission_running"])
        self.assertFalse(packet["mission_active"])
        self.assertTrue(packet["mission_terminal"])
        self.assertEqual(packet["mission_running"], packet["mission"]["running"])

    def test_prepared_mission_requires_matching_file_and_generation(self):
        mission = build_mission_contract({
            "mission_stage": "ready",
            "mission_file": "current.json",
            "mission_total": 6,
            "mission_plan_generation": 4,
            "mission_prepared_file": "current.json",
            "mission_prepared_generation": 3,
        })
        self.assertFalse(mission["prepared"])

        mission = build_mission_contract({
            "mission_stage": "ready",
            "mission_file": "current.json",
            "mission_total": 6,
            "mission_plan_generation": 4,
            "mission_prepared_file": "current.json",
            "mission_prepared_generation": 4,
        })
        self.assertTrue(mission["prepared"])
        self.assertEqual(mission["prepared_file"], "current.json")

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
