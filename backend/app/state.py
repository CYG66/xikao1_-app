from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import os
import time
from typing import Any

from .config import (
    CMD_VEL_TIMEOUT_SEC,
    CONTROL_FREQUENCY_HZ,
    DEFAULT_LINEAR_VELOCITY,
    MAX_ANGULAR_VELOCITY,
    MAX_LINEAR_VELOCITY,
    MAX_TASK_LINEAR_VELOCITY,
    MAX_MOTOR_RPM,
    RUNTIME_PROFILE,
    WHEEL_BASE_M,
    WHEEL_RADIUS_M,
)


def now_text() -> str:
    return datetime.now().strftime("%H:%M:%S")


@dataclass
class RobotState:
    device_id: str = field(default_factory=lambda: os.getenv("XLINE_DEVICE_ID", "").strip())
    vehicle_model: str = field(default_factory=lambda: os.getenv("XLINE_VEHICLE_MODEL", "XLine Rover").strip())
    software_version: str = field(default_factory=lambda: os.getenv("XLINE_SOFTWARE_VERSION", "0.1.0").strip())
    ros_available: bool = False
    bridge_mode: str = "unavailable"
    online: bool = False
    # A backend restart must never implicitly release the software emergency stop.
    emergency_stopped: bool = True
    last_velocity_command_at: str | None = None
    agent_motion_active: bool = False
    agent_motion_deadline: float = 0.0
    agent_motion_command: dict[str, float] = field(default_factory=dict)
    control_owner: str | None = None
    control_lease_expires_at: float = 0.0
    control_ready: bool = False
    drive_transport: str = "socketcan"
    drive_device_path: str = ""
    drive_device_connected: bool = False
    motor_driver_ready: bool = False
    odometry_source: str = "commanded"
    mission_nodes_ready: bool = False
    missing_required_nodes: list[str] = field(default_factory=list)
    localization_valid: bool = False
    localization_source: str = "unavailable"
    ln150_ready: bool = False
    printer_ready: bool = False
    mission_running: bool = False
    mission_paused: bool = False
    mission_stage: str = "idle"
    mission_file: str = ""
    mission_current_id: int | None = None
    mission_completed: int = 0
    mission_total: int = 0
    mission_error: str = ""
    mission_required_printers: list[str] = field(default_factory=list)
    mission_duplicate_ink_paths: int = 0
    mission_summary: dict[str, Any] = field(default_factory=dict)
    mission_validation: dict[str, Any] = field(default_factory=lambda: {
        "ok": False, "errors": [], "warnings": [],
    })
    mission_ledger_id: str | None = None
    mission_segment_verification: dict[str, Any] = field(default_factory=dict)
    mission_last_verified_id: int | str | None = None
    mission_quality: dict[str, Any] = field(default_factory=dict)
    mission_checkpoint: dict[str, Any] = field(default_factory=dict)
    mission_report: dict[str, Any] = field(default_factory=dict)
    oscillation_detected: bool = False
    printer_status: dict[str, Any] = field(default_factory=dict)
    printer_status_updated_at: float = 0.0
    ln150_status: str = ""
    # Telemetry remains unknown until a real ROS2 source reports it.
    battery: int | None = None
    battery_voltage: float | None = None
    battery_current: float | None = None
    battery_temperature: float | None = None
    energy_source: str = "unavailable"
    linear_velocity: float | None = None
    localization_accuracy_mm: float | None = None
    imu: dict[str, Any] = field(default_factory=dict)
    robot_pose: dict[str, Any] = field(default_factory=dict)
    odometry: dict[str, Any] = field(default_factory=dict)
    reflector_position: dict[str, Any] = field(default_factory=dict)
    grid_map: dict[str, Any] = field(default_factory=dict)
    planned_paths: list[dict[str, Any]] = field(default_factory=list)
    path_annotations: list[dict[str, Any]] = field(default_factory=list)
    last_map_update_at: float = 0.0
    last_paths_update_at: float = 0.0
    obstacle_distances: dict[str, float | None] = field(default_factory=lambda: {
        "front": None, "back": None, "left": None, "right": None,
    })
    obstacle_updated_at: float = 0.0
    wheel_speeds: dict[str, Any] = field(default_factory=dict)
    motor_status: dict[str, Any] = field(default_factory=dict)
    localization_calibration: str = "idle"
    localization_calibration_available: bool = False
    pose_trace: list[list[float]] = field(default_factory=list)
    last_pose_update_at: float = 0.0
    last_command: dict[str, Any] = field(default_factory=dict)
    logs: list[str] = field(default_factory=lambda: ["backend ready"])

    def add_log(self, message: str) -> None:
        self.logs.insert(0, f"{now_text()}  {message}")
        del self.logs[80:]

    def snapshot(self) -> dict[str, Any]:
        lease_remaining_ms = max(0, int((self.control_lease_expires_at - time.time()) * 1000))
        telemetry_age_ms = (
            max(0, int((time.time() - self.last_pose_update_at) * 1000))
            if self.last_pose_update_at > 0 else None
        )
        agent_motion_remaining_ms = max(
            0, int((self.agent_motion_deadline - time.time()) * 1000)
        ) if self.agent_motion_active else 0
        capabilities = {
            "manual_drive": self.motor_driver_ready,
            "path_planning": self.mission_nodes_ready,
            "path_execution": self.mission_nodes_ready and self.localization_valid,
            "localization": self.localization_source != "unavailable",
            "printing": self.printer_ready,
            "emergency_stop": True,
        }
        vehicle = {
            "device_id": self.device_id,
            "model": self.vehicle_model,
            "software_version": self.software_version,
            "capabilities": capabilities,
            "motion_limits": {
                "limit_source": "app_control_policy",
                "max_linear_mps": MAX_LINEAR_VELOCITY,
                "default_linear_mps": DEFAULT_LINEAR_VELOCITY,
                "max_task_linear_mps": MAX_TASK_LINEAR_VELOCITY,
                "max_angular_rad_s": MAX_ANGULAR_VELOCITY,
                "max_motor_rpm": MAX_MOTOR_RPM,
                "cmd_vel_timeout_sec": CMD_VEL_TIMEOUT_SEC,
                "control_frequency_hz": CONTROL_FREQUENCY_HZ,
                "wheel_radius_m": WHEEL_RADIUS_M,
                "wheel_base_m": WHEEL_BASE_M,
                "runtime_fixed_velocity_clamp": False,
            },
            "runtime": {
                "profile": RUNTIME_PROFILE,
                "online": self.online,
                "ros_available": self.ros_available,
                "control_ready": self.control_ready,
                "bridge_mode": self.bridge_mode,
            },
            "safety": {
                "emergency_stopped": self.emergency_stopped,
                "control_owner": self.control_owner,
                "control_lease_remaining_ms": lease_remaining_ms,
            },
            "localization": {
                "valid": self.localization_valid,
                "source": self.localization_source,
                "accuracy_mm": self.localization_accuracy_mm,
                "telemetry_age_ms": telemetry_age_ms,
            },
        }
        return {
            "schema_version": "1.0",
            "runtime_profile": RUNTIME_PROFILE,
            "vehicle": vehicle,
            "ros_available": self.ros_available,
            "bridge_mode": self.bridge_mode,
            "online": self.online,
            "emergency_stopped": self.emergency_stopped,
            "last_velocity_command_at": self.last_velocity_command_at,
            "agent_motion_active": self.agent_motion_active,
            "agent_motion_remaining_ms": agent_motion_remaining_ms,
            "agent_motion_command": self.agent_motion_command,
            "control_owner": self.control_owner,
            "control_lease_remaining_ms": lease_remaining_ms,
            "control_ready": self.control_ready,
            "drive_transport": self.drive_transport,
            "drive_device_path": self.drive_device_path,
            "drive_device_connected": self.drive_device_connected,
            "motor_driver_ready": self.motor_driver_ready,
            "odometry_source": self.odometry_source,
            "mission_nodes_ready": self.mission_nodes_ready,
            "missing_required_nodes": self.missing_required_nodes,
            "localization_valid": self.localization_valid,
            "localization_source": self.localization_source,
            "ln150_ready": self.ln150_ready,
            "printer_ready": self.printer_ready,
            "mission_running": self.mission_running,
            "mission_paused": self.mission_paused,
            "mission_stage": self.mission_stage,
            "mission_file": self.mission_file,
            "mission_current_id": self.mission_current_id,
            "mission_completed": self.mission_completed,
            "mission_total": self.mission_total,
            "mission_error": self.mission_error,
            "mission_required_printers": self.mission_required_printers,
            "mission_duplicate_ink_paths": self.mission_duplicate_ink_paths,
            "mission_summary": self.mission_summary,
            "mission_validation": self.mission_validation,
            "mission_ledger_id": self.mission_ledger_id,
            "mission_segment_verification": self.mission_segment_verification,
            "mission_last_verified_id": self.mission_last_verified_id,
            "mission_quality": self.mission_quality,
            "mission_checkpoint": self.mission_checkpoint,
            "mission_report": self.mission_report,
            "oscillation_detected": self.oscillation_detected,
            "printer_status": self.printer_status,
            "printer_status_age_ms": (
                max(0, int((time.time() - self.printer_status_updated_at) * 1000))
                if self.printer_status_updated_at > 0 else None
            ),
            "ln150_status": self.ln150_status,
            "battery": self.battery,
            "battery_voltage": self.battery_voltage,
            "battery_current": self.battery_current,
            "battery_temperature": self.battery_temperature,
            "energy_source": self.energy_source,
            "linear_velocity": self.linear_velocity,
            "localization_accuracy_mm": self.localization_accuracy_mm,
            "imu": self.imu,
            "robot_pose": self.robot_pose,
            "odometry": self.odometry,
            "reflector_position": self.reflector_position,
            "grid_map": self.grid_map,
            "planned_paths": self.planned_paths,
            "path_annotations": self.path_annotations,
            "map_age_ms": (
                max(0, int((time.time() - self.last_map_update_at) * 1000))
                if self.last_map_update_at > 0 else None
            ),
            "paths_age_ms": (
                max(0, int((time.time() - self.last_paths_update_at) * 1000))
                if self.last_paths_update_at > 0 else None
            ),
            "obstacle_distances": self.obstacle_distances,
            "obstacle_age_ms": (
                max(0, int((time.time() - self.obstacle_updated_at) * 1000))
                if self.obstacle_updated_at > 0 else None
            ),
            "wheel_speeds": self.wheel_speeds,
            "motor_status": self.motor_status,
            "localization_calibration": self.localization_calibration,
            "localization_calibration_available": self.localization_calibration_available,
            "pose_trace": self.pose_trace,
            "telemetry_age_ms": telemetry_age_ms,
            "last_command": self.last_command,
            "logs": self.logs[:20],
        }


robot_state = RobotState()


def enable_demo_state() -> None:
    robot_state.ros_available = True
    robot_state.bridge_mode = "virtual_ros2"
    robot_state.online = True
    robot_state.control_ready = True
    robot_state.drive_transport = "socketcan"
    robot_state.drive_device_path = "can0"
    robot_state.drive_device_connected = True
    robot_state.motor_driver_ready = True
    robot_state.odometry_source = "virtual_encoder"
    robot_state.mission_nodes_ready = True
    robot_state.localization_valid = True
    robot_state.ln150_ready = True
    robot_state.printer_ready = True
    robot_state.missing_required_nodes = []
    robot_state.battery = 86
    robot_state.linear_velocity = 0.0
    robot_state.localization_accuracy_mm = 6.2
    robot_state.ln150_status = "tracking"
    robot_state.robot_pose = {"frame_id": "map", "x": 1.2, "y": 1.0, "theta": 0.0}
    robot_state.pose_trace = [[1.2, 1.0]]
    robot_state.last_pose_update_at = time.time()
    robot_state.odometry = {"frame_id": "odom", "x": 1.2, "y": 1.0, "theta": 0.0}
    robot_state.reflector_position = {"frame_id": "map", "x": 1.18, "y": 1.02, "z": 0.0}
    robot_state.imu = {"yaw": 0.0, "angular_velocity_z": 0.0}
    robot_state.grid_map = {
        "frame_id": "map",
        "width": 80,
        "height": 52,
        "resolution": 0.1,
        "origin_x": 0.0,
        "origin_y": 0.0,
        "runs": [
            [0, 80, 100], [4080, 80, 100], [0, 52, 100], [79, 52, 100],
            [820, 13, 100], [1460, 18, 100], [2100, 10, 100], [2740, 16, 100],
        ],
    }
    robot_state.planned_paths = [
        {
            "namespace": "path_lines",
            "color": {"r": 0.1, "g": 0.8, "b": 1.0},
            "points": [[1.2, 1.0], [2.0, 1.0], [2.8, 1.0], [3.6, 1.0], [4.4, 1.0], [5.2, 1.0]],
        },
        {
            "namespace": "path_lines",
            "color": {"r": 0.1, "g": 0.8, "b": 1.0},
            "points": [[5.2, 1.5], [4.4, 1.5], [3.6, 1.5], [2.8, 1.5], [2.0, 1.5], [1.2, 1.5]],
        },
        {
            "namespace": "travel",
            "color": {"r": 1.0, "g": 0.8, "b": 0.1},
            "points": [[5.2, 1.0], [5.45, 1.25], [5.2, 1.5]],
        },
    ]
    robot_state.printer_status = {
        "printer_center": {
            "connected": True,
            "auto_connect": True,
            "enabled": True,
            "spraying": False,
            "status": "ready",
        },
    }
    robot_state.printer_status_updated_at = time.time()
    robot_state.obstacle_distances = {"front": 1.25, "back": 2.4, "left": 0.82, "right": 1.65}
    robot_state.wheel_speeds = {"left_mps": 0.0, "right_mps": 0.0, "source": "virtual_encoder"}
    robot_state.motor_status = {"connected": True, "ready": True, "error": "", "cmd_vel_timeout": False}
    robot_state.add_log("virtual ROS2 car online")


def tick_demo_state() -> None:
    if robot_state.bridge_mode != "virtual_ros2":
        return
    robot_state.last_pose_update_at = time.time()
    pose = robot_state.robot_pose
    if robot_state.mission_running and not robot_state.mission_paused:
        x = float(pose.get("x", 1.2)) + 0.06
        if x > 5.2:
            x = 1.2
            robot_state.mission_completed += 1
        pose["x"] = round(x, 2)
        pose["y"] = 1.0 if robot_state.mission_completed % 2 == 0 else 1.5
        point = [float(pose["x"]), float(pose["y"])]
        robot_state.last_pose_update_at = time.time()
        if not robot_state.pose_trace or robot_state.pose_trace[-1] != point:
            robot_state.pose_trace.append(point)
            del robot_state.pose_trace[:-1000]
        robot_state.linear_velocity = 0.18
        robot_state.mission_stage = "executing"
        robot_state.mission_current_id = robot_state.mission_completed + 1
        if robot_state.mission_completed >= robot_state.mission_total:
            robot_state.mission_running = False
            robot_state.mission_stage = "completed"
            robot_state.linear_velocity = 0.0
    else:
        robot_state.linear_velocity = 0.0
