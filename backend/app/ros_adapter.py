from __future__ import annotations

import json
import threading
from typing import Any

from .config import services, topics
from .state import robot_state

try:
    import rclpy
    from geometry_msgs.msg import Twist
    from rclpy.node import Node
    from std_msgs.msg import String

    try:
        from xline_msgs.srv import LnCommand, QuickCommand
    except Exception:  # pragma: no cover - depends on the robot workspace.
        LnCommand = None
        QuickCommand = None
except Exception:  # pragma: no cover - Windows/dev mode normally lands here.
    rclpy = None
    Node = object
    Twist = None
    String = None
    LnCommand = None
    QuickCommand = None


class RobotRosAdapter:
    def __init__(self) -> None:
        self.node: RobotBackendNode | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if rclpy is None:
            robot_state.ros_available = False
            robot_state.bridge_mode = "simulated"
            robot_state.online = True
            robot_state.add_log("ROS2 not found, backend started in simulated mode")
            return

        rclpy.init(args=None)
        self.node = RobotBackendNode()
        self.thread = threading.Thread(target=rclpy.spin, args=(self.node,), daemon=True)
        self.thread.start()
        robot_state.ros_available = True
        robot_state.bridge_mode = "rclpy"
        robot_state.online = True
        robot_state.add_log("ROS2 backend node started")

    def stop(self) -> None:
        if self.node is not None:
            self.node.destroy_node()
        if rclpy is not None and rclpy.ok():
            rclpy.shutdown()
        robot_state.online = False
        robot_state.add_log("backend stopped")

    def publish_velocity(self, linear: float, angular: float) -> None:
        robot_state.last_command = {"type": "cmd_vel", "linear": linear, "angular": angular}
        robot_state.add_log(f"cmd_vel linear={linear:.2f} angular={angular:.2f}")
        if self.node is not None:
            self.node.publish_velocity(linear, angular)
        else:
            robot_state.robot_pose["x"] = round(robot_state.robot_pose.get("x", 0) + linear * 0.1, 3)
            robot_state.robot_pose["theta"] = round(robot_state.robot_pose.get("theta", 0) + angular * 0.1, 3)

    def control_mission(self, running: bool) -> None:
        robot_state.mission_running = running
        action = "start_line_task" if running else "stop_line_task"
        robot_state.last_command = {"type": "mission", "action": action}
        robot_state.add_log(f"mission {action}")
        if self.node is not None:
            self.node.publish_mission(action)

    def call_printer(self, printer_name: str, action: str, param: int) -> bool:
        robot_state.printer_status = action
        robot_state.last_command = {
            "type": "printer",
            "printer_name": printer_name,
            "action": action,
            "param": param,
        }
        robot_state.add_log(f"printer {printer_name} {action}")
        if self.node is not None:
            return self.node.call_printer(printer_name, action, param)
        return True

    def call_ln150(self, command_type: int) -> bool:
        robot_state.last_command = {"type": "ln150", "command_type": command_type}
        robot_state.add_log(f"ln150 command_type={command_type}")
        if self.node is not None:
            return self.node.call_ln150(command_type)
        return True


class RobotBackendNode(Node):
    def __init__(self) -> None:
        super().__init__("xline_app_backend")
        self.cmd_vel_pub = self.create_publisher(Twist, topics.cmd_vel, 10)
        self.mission_pub = self.create_publisher(String, topics.mission_control, 10)
        self.printer_client = (
            self.create_client(QuickCommand, services.printer_quick_command)
            if QuickCommand is not None
            else None
        )
        self.ln150_client = (
            self.create_client(LnCommand, services.ln150_command) if LnCommand is not None else None
        )
        self._subscribe_json(topics.imu, "imu")
        self._subscribe_json(topics.robot_pose, "robot_pose")
        self._subscribe_json(topics.reflector_position, "reflector_position")
        self._subscribe_json(topics.printer_status, "printer_status")

    def _subscribe_json(self, topic: str, key: str) -> None:
        def handle(message: Any) -> None:
            value = getattr(message, "data", message)
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    pass
            setattr(robot_state, key, value)

        try:
            self.create_subscription(String, topic, handle, 10)
        except Exception:
            robot_state.add_log(f"skip subscription {topic}")

    def publish_velocity(self, linear: float, angular: float) -> None:
        message = Twist()
        message.linear.x = linear
        message.angular.z = angular
        self.cmd_vel_pub.publish(message)

    def publish_mission(self, action: str) -> None:
        message = String()
        message.data = action
        self.mission_pub.publish(message)

    def call_printer(self, printer_name: str, action: str, param: int) -> bool:
        if self.printer_client is None:
            robot_state.add_log("QuickCommand service type not available")
            return False
        request = QuickCommand.Request()
        request.printer_name = printer_name
        request.action = action
        request.param = param
        self.printer_client.call_async(request)
        return True

    def call_ln150(self, command_type: int) -> bool:
        if self.ln150_client is None:
            robot_state.add_log("LnCommand service type not available")
            return False
        request = LnCommand.Request()
        request.command_type = command_type
        self.ln150_client.call_async(request)
        return True


ros_adapter = RobotRosAdapter()
