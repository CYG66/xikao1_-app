"""Stable, read-only contracts exposed to the App.

The values are deliberately copied from RobotState. Unknown hardware values
remain null instead of being replaced with estimates.
"""

from __future__ import annotations

import os
from typing import Any

from .state import normalize_mission_lifecycle


CONTRACT_VERSION = "1.0"


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


FRESHNESS_LIMITS_MS = {
    "runtime": _positive_int_env("XLINE_RUNTIME_FRESHNESS_MS", 3000),
    "motion": _positive_int_env("XLINE_MOTION_FRESHNESS_MS", 3000),
    "localization": _positive_int_env("XLINE_LOCALIZATION_FRESHNESS_MS", 3000),
    "energy": _positive_int_env("XLINE_ENERGY_FRESHNESS_MS", 10000),
    "printer": _positive_int_env("XLINE_PRINTER_FRESHNESS_MS", 5000),
    "obstacles": _positive_int_env("XLINE_OBSTACLE_FRESHNESS_MS", 3000),
}


def _quality(age_ms: Any, available: bool, domain: str) -> dict[str, Any]:
    limit_ms = FRESHNESS_LIMITS_MS[domain]
    age_known = isinstance(age_ms, (int, float))
    fresh = available and age_known and 0 <= age_ms <= limit_ms
    reason = None
    if not available:
        reason = "unavailable"
    elif not age_known:
        reason = "timestamp_missing"
    elif age_ms > limit_ms:
        reason = "stale"
    return {
        "available": available,
        "fresh": fresh,
        "age_ms": age_ms,
        "limit_ms": limit_ms,
        "reason": reason,
    }


def build_telemetry_contract(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Normalize the live snapshot without changing the safety model."""
    telemetry_age = snapshot.get("telemetry_age_ms")
    energy_age = snapshot.get("energy_age_ms")
    obstacle_age = snapshot.get("obstacle_age_ms")
    runtime_available = snapshot.get("online") is True
    localization_available = (
        snapshot.get("localization_source") not in {None, "", "unavailable"}
        and bool(snapshot.get("robot_pose") or snapshot.get("odometry"))
    )
    energy_available = (
        snapshot.get("energy_source") not in {None, "", "unavailable"}
        and any(snapshot.get(key) is not None for key in (
            "battery", "battery_voltage", "battery_current", "battery_temperature"
        ))
    )
    obstacle_values = snapshot.get("obstacle_distances")
    obstacle_available = isinstance(obstacle_values, dict) and any(
        value is not None for value in obstacle_values.values()
    )
    motion_available = any(
        snapshot.get(key) not in (None, {})
        for key in ("linear_velocity", "wheel_speeds", "odometry")
    )
    return {
        "contract_version": CONTRACT_VERSION,
        "recorded_at": snapshot.get("telemetry_age_ms"),
        "runtime": {
            "online": snapshot.get("online") is True,
            "ros_available": snapshot.get("ros_available") is True,
            "bridge_mode": snapshot.get("bridge_mode", "unavailable"),
            "control_ready": snapshot.get("control_ready") is True,
            "telemetry_age_ms": snapshot.get("telemetry_age_ms"),
            # This snapshot is built from the backend's current ROS graph state;
            # pose telemetry is not required to decide whether that graph is online.
            "quality": _quality(0, runtime_available, "runtime"),
        },
        "drive": {
            "transport": snapshot.get("drive_transport"),
            "device_path": snapshot.get("drive_device_path"),
            "device_connected": snapshot.get("drive_device_connected") is True,
            "driver_ready": snapshot.get("motor_driver_ready") is True,
            "wheel_speeds": snapshot.get("wheel_speeds", {}),
            "motor_status": snapshot.get("motor_status", {}),
            "linear_velocity": snapshot.get("linear_velocity"),
            "quality": _quality(telemetry_age, motion_available, "motion"),
        },
        "localization": {
            "valid": snapshot.get("localization_valid") is True,
            "source": snapshot.get("localization_source", "unavailable"),
            "accuracy_mm": snapshot.get("localization_accuracy_mm"),
            "pose": snapshot.get("robot_pose", {}),
            "odometry": snapshot.get("odometry", {}),
            "quality": _quality(
                telemetry_age, localization_available, "localization"
            ),
        },
        "energy": {
            "battery_percent": snapshot.get("battery"),
            "voltage": snapshot.get("battery_voltage"),
            "current": snapshot.get("battery_current"),
            "temperature": snapshot.get("battery_temperature"),
            "source": snapshot.get("energy_source", "unavailable"),
            "age_ms": snapshot.get("energy_age_ms"),
            "available": energy_available,
            "quality": _quality(energy_age, energy_available, "energy"),
            "missing_reason": (
                "vehicle_bms_not_publishing"
                if snapshot.get("energy_source", "unavailable") == "unavailable"
                else None
            ),
        },
        "obstacles": {
            "distances": snapshot.get("obstacle_distances", {}),
            "age_ms": snapshot.get("obstacle_age_ms"),
            "quality": _quality(obstacle_age, obstacle_available, "obstacles"),
        },
    }


def build_printer_contract(snapshot: dict[str, Any]) -> dict[str, Any]:
    printers = snapshot.get("printer_status")
    printers = printers if isinstance(printers, dict) else {}
    result: dict[str, Any] = {}
    for key, raw in printers.items():
        value = raw if isinstance(raw, dict) else {}
        state = str(value.get("spray_state") or "idle")
        result[key] = {
            "connected": value.get("connected") is True,
            "online": value.get("is_online") is True,
            "enabled": value.get("enabled") is True,
            "spraying": value.get("spraying") is True,
            "lifecycle": state,
            "ink_level": value.get("ink_level"),
            "error": value.get("spray_error") or value.get("error"),
            "status": value.get("status"),
        }
    available = bool(result)
    return {
        "contract_version": CONTRACT_VERSION,
        "printers": result,
        "quality": _quality(
            snapshot.get("printer_status_age_ms"), available, "printer"
        ),
    }


def build_mission_contract(snapshot: dict[str, Any]) -> dict[str, Any]:
    lifecycle = normalize_mission_lifecycle(
        snapshot.get("mission_stage"),
        snapshot.get("mission_running"),
        snapshot.get("mission_paused"),
    )
    plan_generation = int(snapshot.get("mission_plan_generation", 0) or 0)
    prepared_generation = int(snapshot.get("mission_prepared_generation", 0) or 0)
    mission_file = str(snapshot.get("mission_file") or "")
    prepared_file = str(snapshot.get("mission_prepared_file") or "")
    prepared = (
        lifecycle["stage"] == "ready"
        and bool(mission_file)
        and prepared_file == mission_file
        and prepared_generation == plan_generation
        and int(snapshot.get("mission_total", 0) or 0) > 0
    )
    return {
        "contract_version": CONTRACT_VERSION,
        "stage": lifecycle["stage"],
        "file_name": mission_file or None,
        "plan_generation": plan_generation,
        "prepared": prepared,
        "prepared_file": prepared_file or None,
        "prepared_generation": prepared_generation,
        "current_segment": (
            None if lifecycle["terminal"] else snapshot.get("mission_current_id")
        ),
        "completed_segments": snapshot.get("mission_completed", 0),
        "total_segments": snapshot.get("mission_total", 0),
        "running": lifecycle["running"],
        "paused": lifecycle["paused"],
        "active": lifecycle["active"],
        "terminal": lifecycle["terminal"],
        "error": snapshot.get("mission_error") or None,
        "checkpoint": snapshot.get("mission_checkpoint", {}),
        "quality": snapshot.get("mission_quality", {}),
    }


def build_status_packet(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Build the one canonical status packet used by HTTP and WebSocket APIs."""
    packet = dict(snapshot)
    mission = build_mission_contract(packet)
    packet.update({
        # Keep normalized legacy fields while clients migrate to mission.*.
        "mission_stage": mission["stage"],
        "mission_running": mission["running"],
        "mission_paused": mission["paused"],
        "mission_active": mission["active"],
        "mission_terminal": mission["terminal"],
        "mission_current_id": mission["current_segment"],
        "mission_plan_generation": mission["plan_generation"],
        "mission_prepared": mission["prepared"],
        "mission_prepared_file": mission["prepared_file"],
        "mission_prepared_generation": mission["prepared_generation"],
        "telemetry": build_telemetry_contract(packet),
        "printer_contract": build_printer_contract(packet),
        "mission": mission,
    })
    return packet
