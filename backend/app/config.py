from dataclasses import dataclass


@dataclass(frozen=True)
class Topics:
    cmd_vel: str = "/cmd_vel"
    imu: str = "/imu"
    robot_pose: str = "/robot_pose"
    reflector_position: str = "/reflector_position"
    printer_status: str = "/printer_status"
    mission_control: str = "/xline/mission_control"


@dataclass(frozen=True)
class Services:
    printer_quick_command: str = "/printer/quick_command"
    ln150_command: str = "/ln_driver/command_srv"


topics = Topics()
services = Services()
