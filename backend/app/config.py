from dataclasses import dataclass


@dataclass(frozen=True)
class Topics:
    # App 手动控制必须进入 cmd_vel_mux 的平板输入，最终 /cmd_vel 由 mux 发布。
    tablet_cmd_vel: str = "/tablet_cmd_vel"
    odom: str = "/odom"
    imu: str = "/imu"
    robot_pose: str = "/robot_pose"
    reflector_position: str = "/reflector_position"
    printer_status: str = "/printer_status"
    ln150_status: str = "/ln_driver/status"
    grid_map: str = "/foxglove/grid_map"
    planned_paths: str = "/foxglove/planned_paths"


@dataclass(frozen=True)
class Services:
    printer_quick_command: str = "/printer/quick_command"
    ln150_command: str = "/ln_driver/command_srv"
    printer_set_active: str = "/printer/set_active"
    plan_path: str = "/plan_path"


EXECUTE_PLAN_ACTION = "/execute_plan"
PLANNED_RESULTS_DIR = "/home/qingz/xline_ws2/other/planned_results"


topics = Topics()
services = Services()


USB2CAN_DEVICE = "/dev/serial/by-id/usb-HDSC_CDC_Device_00000000050C-if00"
