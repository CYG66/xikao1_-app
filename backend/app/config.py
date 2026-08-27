from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Topics:
    # App 手动控制必须进入 cmd_vel_mux 的平板输入，最终 /cmd_vel 由 mux 发布。
    tablet_cmd_vel: str = "/tablet_cmd_vel"
    odom: str = "/odom"
    imu: str = "/imu"
    robot_pose: str = "/robot_pose"
    localization_valid: str = "/localization/valid"
    reflector_position: str = "/reflector_position"
    printer_status: str = "/printer_status"
    ln150_status: str = "/ln_driver/status"
    ln150_battery: str = "/ln_driver/battery"
    grid_map: str = "/foxglove/grid_map"
    planned_paths: str = "/foxglove/planned_paths"
    obstacle_detected: str = "/obstacle_detected"
    joint_states: str = "/joint_states"
    motor_status: str = "/motor_status"
    emergency_stop: str = "/emergency_stop"
    emergency_stop_status: str = "/emergency_stop/status"


@dataclass(frozen=True)
class Services:
    emergency_stop_reset: str = "/emergency_stop/reset"
    printer_quick_command: str = "/printer/quick_command"
    ln150_command: str = "/ln_driver/command_srv"
    printer_set_active: str = "/printer/set_active"
    printer_set_enabled: str = "/printer/set_enabled"
    printer_send_command: str = "/printer/send_command"
    plan_path: str = "/plan_path"
    execution_pause: str = "/execution/pause"
    execution_resume: str = "/execution/resume"
    localization_calibrate: str = "/localization/calibrate_pose"


EXECUTE_PLAN_ACTION = "/execute_plan"
PLANNED_RESULTS_DIR = os.getenv(
    "XLINE_PLANNED_RESULTS_DIR", "/home/qingz/xline_ws3/other/planned_results"
).strip()
MAX_LINEAR_VELOCITY = 1.00
DEFAULT_LINEAR_VELOCITY = 0.10
# xline_ws3 path-following configurations cap work/curve motion at 0.10 m/s.
# Keep this separate from the 1.00 m/s App manual-control ceiling.
MAX_TASK_LINEAR_VELOCITY = 0.10
MAX_ANGULAR_VELOCITY = 0.40
# The final wheel driver no longer applies fixed chassis linear/angular clamps.
# The App keeps the limit above as its configurable control ceiling. It is
# below the rated-speed conversion in the xline_ws3 documentation, but it
# remains an App control limit rather than a validated operating speed.
MAX_MOTOR_RPM = 500.0
CMD_VEL_TIMEOUT_SEC = 0.50
CONTROL_FREQUENCY_HZ = 50.0
WHEEL_RADIUS_M = 0.09115
WHEEL_BASE_M = 0.255

# The current xline_ws3 printer node creates only printer_center. Keep this
# explicit so API and Agent layers never advertise non-existent side heads.
SUPPORTED_PRINTERS = ("center",)

# Hardware runtime used when the App releases the software emergency stop.
# Keep paths configurable, but default to the current xline_ws3 deployment.
XLINE_WS_DIR = os.getenv("XLINE_WS_DIR", "/home/qingz/xline_ws3").strip()
XLINE_SETUP_FILE = os.getenv(
    "XLINE_SETUP_FILE", "/home/qingz/xline_ws3/install/setup.bash"
).strip()
USE_TOTAL_STATION = os.getenv("XLINE_USE_TOTAL_STATION", "false").strip().lower() in {
    "1", "true", "yes", "on",
}
HARDWARE_LAUNCH_LOG = os.getenv(
    "XLINE_HARDWARE_LAUNCH_LOG",
    "/home/qingz/xline_ws3_hardware_runtime.log",
).strip()
HARDWARE_LAUNCH_PID = os.getenv(
    "XLINE_HARDWARE_LAUNCH_PID",
    "/home/qingz/xline_ws3_hardware_runtime.pid",
).strip()
ENABLE_PRINTER = os.getenv("XLINE_ENABLE_PRINTER", "true").strip().lower() in {
    "1", "true", "yes", "on",
}
BACKEND_NODE_NAME = os.getenv(
    "XLINE_BACKEND_NODE_NAME", "xline_app_backend1"
).strip() or "xline_app_backend1"
RUNTIME_PROFILE = os.getenv("XLINE_RUNTIME_PROFILE", "xline_ws3").strip() or "xline_ws3"


topics = Topics()
services = Services()


# xline_ws3 uses the Orange Pi SocketCAN interface by default.
# Serial USB2CAN remains available as a legacy transport selected by env.
CAN_TRANSPORT = os.getenv("XLINE_CAN_TRANSPORT", "socketcan").strip().lower()
CAN_INTERFACE = os.getenv("XLINE_CAN_INTERFACE", "can0").strip()
USB2CAN_DEVICE = os.getenv(
    "XLINE_USB2CAN_DEVICE",
    "/dev/serial/by-id/usb-HDSC_CDC_Device_00000000050C-if00",
).strip()
