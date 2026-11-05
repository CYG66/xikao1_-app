from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
import os
import threading
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
    VIRTUAL_TOTAL_STATION,
    WHEEL_BASE_M,
    WHEEL_RADIUS_M,
)


def now_text() -> str:
    return datetime.now().strftime("%H:%M:%S")


MISSION_TERMINAL_STAGES = frozenset({"completed", "failed", "cancelled"})


def normalize_mission_lifecycle(
    stage: object,
    running: object,
    paused: object,
) -> dict[str, bool | str]:
    """Return the canonical mission lifecycle represented by legacy fields."""
    normalized_stage = str(stage or "idle").strip().lower() or "idle"
    terminal = normalized_stage in MISSION_TERMINAL_STAGES
    normalized_running = running is True and not terminal
    normalized_paused = paused is True and normalized_running
    return {
        "stage": normalized_stage,
        "running": normalized_running,
        "paused": normalized_paused,
        "active": normalized_running,
        "terminal": terminal,
    }


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
    agent_motion_started_at: str | None = None
    agent_motion_completed_at: str | None = None
    agent_motion_completion_reason: str | None = None
    agent_motion_outcome: str = "idle"
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
    mission_plan_generation: int = 0
    mission_prepared_file: str = ""
    mission_prepared_generation: int = 0
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
    energy_updated_at: float = 0.0
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
    virtual_mission_segments: list[dict[str, Any]] = field(default_factory=list)
    virtual_segment_index: int = 0
    virtual_point_index: int = 0
    virtual_last_tick_at: float = 0.0
    last_command: dict[str, Any] = field(default_factory=dict)
    logs: list[str] = field(default_factory=lambda: ["backend ready"])

    def add_log(self, message: str) -> None:
        self.logs.insert(0, f"{now_text()}  {message}")
        del self.logs[80:]

    def normalize_mission_state(self) -> dict[str, bool | str]:
        """Repair stale lifecycle flags before they can lock API consumers."""
        lifecycle = normalize_mission_lifecycle(
            self.mission_stage,
            self.mission_running,
            self.mission_paused,
        )
        self.mission_stage = str(lifecycle["stage"])
        self.mission_running = bool(lifecycle["running"])
        self.mission_paused = bool(lifecycle["paused"])
        if lifecycle["terminal"]:
            self.mission_current_id = None
        return lifecycle

    def snapshot(self) -> dict[str, Any]:
        mission_lifecycle = self.normalize_mission_state()
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
            "agent_motion_started_at": self.agent_motion_started_at,
            "agent_motion_completed_at": self.agent_motion_completed_at,
            "agent_motion_completion_reason": self.agent_motion_completion_reason,
            "agent_motion_outcome": self.agent_motion_outcome,
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
            "mission_running": mission_lifecycle["running"],
            "mission_paused": mission_lifecycle["paused"],
            "mission_stage": mission_lifecycle["stage"],
            "mission_active": mission_lifecycle["active"],
            "mission_terminal": mission_lifecycle["terminal"],
            "mission_file": self.mission_file,
            "mission_plan_generation": self.mission_plan_generation,
            "mission_prepared_file": self.mission_prepared_file,
            "mission_prepared_generation": self.mission_prepared_generation,
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
            "energy_age_ms": (
                max(0, int((time.time() - self.energy_updated_at) * 1000))
                if self.energy_updated_at > 0 else None
            ),
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
_virtual_mission_lock = threading.RLock()


def _set_virtual_spraying(active: bool) -> None:
    for status in robot_state.printer_status.values():
        if isinstance(status, dict):
            status["spraying"] = active


def _stop_virtual_motion() -> None:
    robot_state.linear_velocity = 0.0
    robot_state.wheel_speeds = {
        "left_mps": 0.0,
        "right_mps": 0.0,
        "source": "virtual_encoder",
    }
    _set_virtual_spraying(False)


def load_virtual_mission_segments(segments: list[dict[str, Any]]) -> int:
    """Store a validated, execution-safe copy of the virtual route preview."""
    normalized: list[dict[str, Any]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        points: list[list[float]] = []
        for point in segment.get("points", []):
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            try:
                x, y = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                continue
            if math.isfinite(x) and math.isfinite(y):
                points.append([x, y])
        if len(points) < 2:
            continue
        normalized.append({
            "route_type": str(segment.get("route_type", "printing")),
            "geometry_index": segment.get("geometry_index"),
            "points": points,
        })

    with _virtual_mission_lock:
        robot_state.virtual_mission_segments = normalized
        robot_state.virtual_segment_index = 0
        robot_state.virtual_point_index = 0
        robot_state.virtual_last_tick_at = 0.0
        robot_state.mission_total = len(normalized)
        robot_state.mission_completed = 0
        robot_state.mission_current_id = None
        _stop_virtual_motion()
    return len(normalized)


def start_virtual_mission_tracking() -> bool:
    with _virtual_mission_lock:
        if not robot_state.virtual_mission_segments:
            return False
        robot_state.virtual_segment_index = 0
        robot_state.virtual_point_index = 0
        robot_state.virtual_last_tick_at = time.monotonic()
        robot_state.mission_completed = 0
        robot_state.mission_total = len(robot_state.virtual_mission_segments)
        robot_state.mission_current_id = 1
        robot_state.pose_trace = [[
            float(robot_state.robot_pose.get("x", 0.0)),
            float(robot_state.robot_pose.get("y", 0.0)),
        ]]
        _stop_virtual_motion()
    return True


def reset_virtual_mission_tracking(*, clear_segments: bool = False) -> None:
    with _virtual_mission_lock:
        robot_state.virtual_segment_index = 0
        robot_state.virtual_point_index = 0
        robot_state.virtual_last_tick_at = 0.0
        robot_state.mission_current_id = None
        if clear_segments:
            robot_state.virtual_mission_segments = []
            robot_state.mission_total = 0
        _stop_virtual_motion()


def enable_demo_state() -> None:
    reset_virtual_mission_tracking(clear_segments=True)
    robot_state.ros_available = True
    robot_state.bridge_mode = "virtual_ros2"
    robot_state.online = True
    robot_state.emergency_stopped = True
    robot_state.control_owner = None
    robot_state.control_lease_expires_at = 0.0
    robot_state.control_ready = True
    robot_state.drive_transport = "virtual"
    robot_state.drive_device_path = "local_simulator"
    robot_state.drive_device_connected = True
    robot_state.motor_driver_ready = True
    robot_state.odometry_source = "virtual_encoder"
    robot_state.mission_nodes_ready = True
    robot_state.localization_valid = True
    robot_state.localization_source = (
        "ln150_imu" if VIRTUAL_TOTAL_STATION else "virtual_odom_imu"
    )
    robot_state.ln150_ready = True
    robot_state.printer_ready = True
    robot_state.missing_required_nodes = []
    robot_state.mission_running = False
    robot_state.mission_paused = False
    robot_state.mission_stage = "idle"
    robot_state.mission_file = ""
    robot_state.mission_plan_generation = 0
    robot_state.mission_prepared_file = ""
    robot_state.mission_prepared_generation = 0
    robot_state.mission_error = ""
    robot_state.mission_completed = 0
    robot_state.mission_current_id = None
    robot_state.battery = 86
    robot_state.battery_voltage = 25.4
    robot_state.battery_current = 1.8
    robot_state.battery_temperature = 31.0
    robot_state.energy_source = "virtual_bms"
    robot_state.energy_updated_at = time.time()
    robot_state.linear_velocity = 0.0
    robot_state.localization_accuracy_mm = 6.2
    robot_state.localization_calibration_available = VIRTUAL_TOTAL_STATION
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
    robot_state.last_map_update_at = time.time()
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
    robot_state.last_paths_update_at = time.time()
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
    robot_state.obstacle_updated_at = time.time()
    robot_state.wheel_speeds = {"left_mps": 0.0, "right_mps": 0.0, "source": "virtual_encoder"}
    robot_state.motor_status = {"connected": True, "ready": True, "error": "", "cmd_vel_timeout": False}
    robot_state.add_log("virtual ROS2 car online")


def tick_demo_state(delta_seconds: float | None = None) -> dict[str, Any]:
    events: dict[str, Any] = {
        "completed_segments": [],
        "mission_completed": False,
    }
    if robot_state.bridge_mode != "virtual_ros2":
        return events
    now = time.time()
    robot_state.last_pose_update_at = now
    robot_state.energy_updated_at = now
    robot_state.printer_status_updated_at = now
    robot_state.obstacle_updated_at = now
    robot_state.last_map_update_at = now
    with _virtual_mission_lock:
        monotonic_now = time.monotonic()
        if delta_seconds is None:
            previous_tick = robot_state.virtual_last_tick_at or monotonic_now
            elapsed = min(0.5, max(0.0, monotonic_now - previous_tick))
        else:
            elapsed = max(0.0, float(delta_seconds))
        robot_state.virtual_last_tick_at = monotonic_now

        can_move = (
            robot_state.mission_running
            and not robot_state.mission_paused
            and not robot_state.emergency_stopped
            and bool(robot_state.virtual_mission_segments)
        )
        if not can_move:
            _stop_virtual_motion()
            return events

        remaining_distance = DEFAULT_LINEAR_VELOCITY * elapsed
        moved = False
        while remaining_distance > 1e-9 and robot_state.mission_running:
            segment_index = robot_state.virtual_segment_index
            if segment_index >= len(robot_state.virtual_mission_segments):
                robot_state.mission_running = False
                robot_state.mission_paused = False
                robot_state.mission_stage = "completed"
                robot_state.mission_current_id = None
                events["mission_completed"] = True
                _stop_virtual_motion()
                break

            segment = robot_state.virtual_mission_segments[segment_index]
            points = segment["points"]
            point_index = robot_state.virtual_point_index
            if point_index >= len(points):
                robot_state.mission_completed = segment_index + 1
                events["completed_segments"].append({
                    "index": segment_index,
                    "endpoint": list(points[-1]),
                })
                robot_state.virtual_segment_index += 1
                robot_state.virtual_point_index = 0
                robot_state.mission_current_id = (
                    robot_state.virtual_segment_index + 1
                    if robot_state.virtual_segment_index < len(robot_state.virtual_mission_segments)
                    else None
                )
                continue

            pose = robot_state.robot_pose
            current_x = float(pose.get("x", 0.0))
            current_y = float(pose.get("y", 0.0))
            target_x, target_y = points[point_index]
            dx, dy = target_x - current_x, target_y - current_y
            distance = math.hypot(dx, dy)
            if distance <= 1e-9:
                robot_state.virtual_point_index += 1
                continue

            step = min(remaining_distance, distance)
            ratio = step / distance
            next_x = current_x + dx * ratio
            next_y = current_y + dy * ratio
            theta = math.atan2(dy, dx)
            pose.update({
                "frame_id": "map",
                "x": round(next_x, 4),
                "y": round(next_y, 4),
                "theta": round(theta, 6),
            })
            robot_state.odometry = {
                "frame_id": "odom",
                "x": pose["x"],
                "y": pose["y"],
                "theta": pose["theta"],
            }
            robot_state.reflector_position = {
                "frame_id": "map",
                "x": pose["x"],
                "y": pose["y"],
                "z": 0.0,
            }
            robot_state.imu = {"yaw": pose["theta"], "angular_velocity_z": 0.0}
            point = [float(pose["x"]), float(pose["y"])]
            if not robot_state.pose_trace or robot_state.pose_trace[-1] != point:
                robot_state.pose_trace.append(point)
                del robot_state.pose_trace[:-1000]
            moved = True
            remaining_distance -= step
            if step >= distance - 1e-9:
                robot_state.virtual_point_index += 1

        while robot_state.mission_running:
            segment_index = robot_state.virtual_segment_index
            if segment_index >= len(robot_state.virtual_mission_segments):
                robot_state.mission_running = False
                robot_state.mission_paused = False
                robot_state.mission_stage = "completed"
                robot_state.mission_current_id = None
                events["mission_completed"] = True
                _stop_virtual_motion()
                break
            points = robot_state.virtual_mission_segments[segment_index]["points"]
            if robot_state.virtual_point_index < len(points):
                break
            robot_state.mission_completed = segment_index + 1
            events["completed_segments"].append({
                "index": segment_index,
                "endpoint": list(points[-1]),
            })
            robot_state.virtual_segment_index += 1
            robot_state.virtual_point_index = 0
            robot_state.mission_current_id = (
                robot_state.virtual_segment_index + 1
                if robot_state.virtual_segment_index < len(robot_state.virtual_mission_segments)
                else None
            )

        if robot_state.mission_running and moved:
            robot_state.linear_velocity = DEFAULT_LINEAR_VELOCITY
            robot_state.wheel_speeds = {
                "left_mps": DEFAULT_LINEAR_VELOCITY,
                "right_mps": DEFAULT_LINEAR_VELOCITY,
                "source": "virtual_encoder",
            }
            robot_state.mission_stage = "executing"
            current = robot_state.virtual_segment_index
            spraying = (
                current < len(robot_state.virtual_mission_segments)
                and robot_state.virtual_mission_segments[current].get("route_type") == "printing"
            )
            _set_virtual_spraying(spraying)
        elif robot_state.mission_running:
            _stop_virtual_motion()
    return events
