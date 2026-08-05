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
    mission_running: bool = False
    printer_status: str = "unknown"
    battery: int = 82
    imu: dict[str, Any] = field(default_factory=dict)
    robot_pose: dict[str, Any] = field(default_factory=lambda: {"x": 0, "y": 0, "theta": 0})
    reflector_position: dict[str, Any] = field(default_factory=dict)
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
            "mission_running": self.mission_running,
            "printer_status": self.printer_status,
            "battery": self.battery,
            "imu": self.imu,
            "robot_pose": self.robot_pose,
            "reflector_position": self.reflector_position,
            "last_command": self.last_command,
            "logs": self.logs[:20],
        }


robot_state = RobotState()
