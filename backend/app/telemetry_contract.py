"""Stable, read-only contracts exposed to the App.

The values are deliberately copied from RobotState. Unknown hardware values
remain null instead of being replaced with estimates.
"""

from __future__ import annotations

from typing import Any


CONTRACT_VERSION = "1.0"


def build_telemetry_contract(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Normalize the live snapshot without changing the safety model."""
    return {
        "contract_version": CONTRACT_VERSION,
        "recorded_at": snapshot.get("telemetry_age_ms"),
        "runtime": {
            "online": snapshot.get("online") is True,
            "ros_available": snapshot.get("ros_available") is True,
            "bridge_mode": snapshot.get("bridge_mode", "unavailable"),
            "control_ready": snapshot.get("control_ready") is True,
            "telemetry_age_ms": snapshot.get("telemetry_age_ms"),
        },
        "drive": {
            "transport": snapshot.get("drive_transport"),
            "device_path": snapshot.get("drive_device_path"),
            "device_connected": snapshot.get("drive_device_connected") is True,
            "driver_ready": snapshot.get("motor_driver_ready") is True,
            "wheel_speeds": snapshot.get("wheel_speeds", {}),
            "motor_status": snapshot.get("motor_status", {}),
            "linear_velocity": snapshot.get("linear_velocity"),
        },
        "localization": {
            "valid": snapshot.get("localization_valid") is True,
            "source": snapshot.get("localization_source", "unavailable"),
            "accuracy_mm": snapshot.get("localization_accuracy_mm"),
            "pose": snapshot.get("robot_pose", {}),
            "odometry": snapshot.get("odometry", {}),
        },
        "energy": {
            "battery_percent": snapshot.get("battery"),
            "voltage": snapshot.get("battery_voltage"),
            "current": snapshot.get("battery_current"),
            "temperature": snapshot.get("battery_temperature"),
            "source": snapshot.get("energy_source", "unavailable"),
        },
        "obstacles": {
            "distances": snapshot.get("obstacle_distances", {}),
            "age_ms": snapshot.get("obstacle_age_ms"),
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
    return {"contract_version": CONTRACT_VERSION, "printers": result}


def build_mission_contract(snapshot: dict[str, Any]) -> dict[str, Any]:
    stage = str(snapshot.get("mission_stage") or "idle")
    return {
        "contract_version": CONTRACT_VERSION,
        "stage": stage,
        "file_name": snapshot.get("mission_file") or None,
        "current_segment": snapshot.get("mission_current_id"),
        "completed_segments": snapshot.get("mission_completed", 0),
        "total_segments": snapshot.get("mission_total", 0),
        "running": snapshot.get("mission_running") is True,
        "paused": snapshot.get("mission_paused") is True,
        "error": snapshot.get("mission_error") or None,
        "checkpoint": snapshot.get("mission_checkpoint", {}),
        "quality": snapshot.get("mission_quality", {}),
    }
