from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def now_text() -> str:
    return datetime.now().strftime("%H:%M:%S")


@dataclass
class RobotState:
    ros_available: bool = False
    bridge_mode: str = "simulated"
    online: bool = False
    control_ready: bool = False
    drive_transport: str = "usb2can"
    drive_device_path: str = ""
    drive_device_connected: bool = False
    motor_driver_ready: bool = False
    odometry_source: str = "commanded"
    mission_nodes_ready: bool = False
    missing_required_nodes: list[str] = field(default_factory=list)
    mission_running: bool = False
    mission_stage: str = "idle"
    mission_file: str = ""
    mission_current_id: int | None = None
    mission_completed: int = 0
    mission_total: int = 0
    mission_error: str = ""
    printer_status: dict[str, Any] = field(default_factory=dict)
    ln150_status: str = ""
    # Telemetry remains unknown until a real ROS2 source reports it.
    battery: int | None = None
    linear_velocity: float | None = None
    localization_accuracy_mm: float | None = None
    imu: dict[str, Any] = field(default_factory=dict)
    robot_pose: dict[str, Any] = field(default_factory=dict)
    odometry: dict[str, Any] = field(default_factory=dict)
    reflector_position: dict[str, Any] = field(default_factory=dict)
    grid_map: dict[str, Any] = field(default_factory=dict)
    planned_paths: list[dict[str, Any]] = field(default_factory=list)
    last_command: dict[str, Any] = field(default_factory=dict)
    logs: list[str] = field(default_factory=lambda: ["backend ready"])

    def add_log(self, message: str) -> None:
        self.logs.insert(0, f"{now_text()}  {message}")
        del self.logs[80:]

    def snapshot(self) -> dict[str, Any]:
        return {
            "ros_available": self.ros_available,
            "bridge_mode": self.bridge_mode,
            "online": self.online,
            "control_ready": self.control_ready,
            "drive_transport": self.drive_transport,
            "drive_device_path": self.drive_device_path,
            "drive_device_connected": self.drive_device_connected,
            "motor_driver_ready": self.motor_driver_ready,
            "odometry_source": self.odometry_source,
            "mission_nodes_ready": self.mission_nodes_ready,
            "missing_required_nodes": self.missing_required_nodes,
            "mission_running": self.mission_running,
            "mission_stage": self.mission_stage,
            "mission_file": self.mission_file,
            "mission_current_id": self.mission_current_id,
            "mission_completed": self.mission_completed,
            "mission_total": self.mission_total,
            "mission_error": self.mission_error,
            "printer_status": self.printer_status,
            "ln150_status": self.ln150_status,
            "battery": self.battery,
            "linear_velocity": self.linear_velocity,
            "localization_accuracy_mm": self.localization_accuracy_mm,
            "imu": self.imu,
            "robot_pose": self.robot_pose,
            "odometry": self.odometry,
            "reflector_position": self.reflector_position,
            "grid_map": self.grid_map,
            "planned_paths": self.planned_paths,
            "last_command": self.last_command,
            "logs": self.logs[:20],
        }


robot_state = RobotState()
