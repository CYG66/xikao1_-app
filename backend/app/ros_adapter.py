from __future__ import annotations

import json
import math
import os
import threading
from pathlib import Path
from typing import Any

from .config import EXECUTE_PLAN_ACTION, PLANNED_RESULTS_DIR, USB2CAN_DEVICE, services, topics
from .state import robot_state

try:
    import rclpy
    from geometry_msgs.msg import PointStamped, PoseStamped, Twist
    from nav_msgs.msg import OccupancyGrid, Odometry
    from rclpy.action import ActionClient
    from rclpy.node import Node
    from sensor_msgs.msg import Imu
    from std_msgs.msg import String
    from visualization_msgs.msg import MarkerArray

    try:
        from xline_msgs.action import ExecutePlan
        from xline_msgs.srv import LnCommand, QuickCommand, SetPrinterActive
        from xline_path_planner.srv import PlanPath
    except Exception:  # pragma: no cover - depends on the robot workspace.
        LnCommand = None
        QuickCommand = None
        SetPrinterActive = None
        ExecutePlan = None
        PlanPath = None
except Exception:  # pragma: no cover - Windows/dev mode normally lands here.
    rclpy = None
    Node = object
    Twist = None
    PointStamped = None
    PoseStamped = None
    OccupancyGrid = None
    MarkerArray = None
    Odometry = None
    String = None
    LnCommand = None
    QuickCommand = None
    SetPrinterActive = None
    ExecutePlan = None
    PlanPath = None


class RobotRosAdapter:
    def __init__(self) -> None:
        self.node: RobotBackendNode | None = None
        self.thread: threading.Thread | None = None
        self.stop_timer: threading.Timer | None = None

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

    def publish_velocity(self, linear: float, angular: float) -> bool:
        # Match cmd_vel_mux tablet_max_* parameters even when its raw callback is active.
        linear = max(-1.0, min(1.0, linear))
        angular = max(-1.5, min(1.5, angular))
        robot_state.last_command = {"type": "cmd_vel", "linear": linear, "angular": angular}
        if (linear != 0.0 or angular != 0.0) and not robot_state.control_ready:
            robot_state.add_log("cmd_vel blocked: USB2CAN motor driver is not ready")
            return False
        robot_state.add_log(f"cmd_vel linear={linear:.2f} angular={angular:.2f}")
        if self.node is not None:
            self.node.publish_velocity(linear, angular)
        else:
            robot_state.robot_pose["x"] = round(robot_state.robot_pose.get("x", 0) + linear * 0.1, 3)
            robot_state.robot_pose["theta"] = round(robot_state.robot_pose.get("theta", 0) + angular * 0.1, 3)
        return True

    def publish_timed_velocity(self, linear: float, angular: float, duration: float) -> bool:
        if not self.publish_velocity(linear, angular):
            return False
        if self.stop_timer is not None:
            self.stop_timer.cancel()
        self.stop_timer = threading.Timer(duration, self.publish_velocity, args=(0.0, 0.0))
        self.stop_timer.daemon = True
        self.stop_timer.start()
        return True

    def control_mission(self, running: bool, file_name: str = "test_pattern.json") -> bool:
        if self.node is None:
            robot_state.add_log("mission blocked: ROS2 unavailable")
            return False
        return self.node.start_mission(file_name) if running else self.node.cancel_mission()

    def call_printer(self, printer_name: str, action: str, param: int) -> bool:
        robot_state.last_command = {
            "type": "printer",
            "printer_name": printer_name,
            "action": action,
            "param": param,
        }
        robot_state.add_log(f"printer {printer_name} {action}")
        if self.node is not None:
            return self.node.call_printer(printer_name, action, param)
        return False

    def set_printer_active(self, printer_name: str, active: bool) -> bool:
        if self.node is None:
            return False
        return self.node.set_printer_active(printer_name, active)

    def call_ln150(self, command_type: int) -> bool:
        robot_state.last_command = {"type": "ln150", "command_type": command_type}
        robot_state.add_log(f"ln150 command_type={command_type}")
        if self.node is not None:
            return self.node.call_ln150(command_type)
        return False


class RobotBackendNode(Node):
    control_nodes = {"differential_wheels_driver", "cmd_vel_mux"}
    mission_nodes = control_nodes | {
        "localization", "path_planner", "base_controller",
        "ln150_driver", "inkjet_printer_node",
    }

    def __init__(self) -> None:
        super().__init__("xline_app_backend")
        self.cmd_vel_pub = self.create_publisher(Twist, topics.tablet_cmd_vel, 10)
        self.printer_client = (
            self.create_client(QuickCommand, services.printer_quick_command)
            if QuickCommand is not None
            else None
        )
        self.ln150_client = (
            self.create_client(LnCommand, services.ln150_command) if LnCommand is not None else None
        )
        self.printer_active_client = (
            self.create_client(SetPrinterActive, services.printer_set_active)
            if SetPrinterActive is not None else None
        )
        self.plan_client = (
            self.create_client(PlanPath, services.plan_path) if PlanPath is not None else None
        )
        self.execute_client = (
            ActionClient(self, ExecutePlan, EXECUTE_PLAN_ACTION) if ExecutePlan is not None else None
        )
        self._mission_segments: list[dict[str, Any]] = []
        self._mission_index = 0
        self._goal_handle: Any = None
        self.create_subscription(Imu, topics.imu, self._handle_imu, 10)
        self.create_subscription(PoseStamped, topics.robot_pose, self._handle_robot_pose, 10)
        self.create_subscription(
            PointStamped, topics.reflector_position, self._handle_reflector_position, 10
        )
        self._subscribe_json(topics.printer_status, "printer_status")
        self._subscribe_json(topics.ln150_status, "ln150_status")
        self.create_subscription(Odometry, topics.odom, self._handle_odometry, 10)
        map_qos = rclpy.qos.QoSProfile(
            depth=1,
            durability=rclpy.qos.DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=rclpy.qos.ReliabilityPolicy.RELIABLE,
        )
        self.create_subscription(OccupancyGrid, topics.grid_map, self._handle_grid_map, map_qos)
        self.create_subscription(MarkerArray, topics.planned_paths, self._handle_paths, map_qos)
        robot_state.drive_device_path = USB2CAN_DEVICE
        self.create_timer(1.0, self._update_graph_readiness)

    def _update_graph_readiness(self) -> None:
        """Reflect ROS graph availability without inventing hardware telemetry."""
        available = set(self.get_node_names())
        robot_state.drive_device_connected = os.path.exists(USB2CAN_DEVICE)
        robot_state.motor_driver_ready = (
            "differential_wheels_driver" in available
            and robot_state.drive_device_connected
        )
        robot_state.control_ready = (
            self.control_nodes.issubset(available)
            and robot_state.motor_driver_ready
        )
        robot_state.mission_nodes_ready = self.mission_nodes.issubset(available)
        robot_state.missing_required_nodes = sorted(self.mission_nodes - available)

    def _handle_odometry(self, message: Any) -> None:
        orientation = message.pose.pose.orientation
        theta = math.atan2(
            2.0 * (orientation.w * orientation.z + orientation.x * orientation.y),
            1.0 - 2.0 * (orientation.y * orientation.y + orientation.z * orientation.z),
        )
        robot_state.linear_velocity = float(message.twist.twist.linear.x)
        robot_state.odometry = {
            "x": float(message.pose.pose.position.x),
            "y": float(message.pose.pose.position.y),
            "theta": theta,
            "frame_id": message.header.frame_id,
        }

    def _handle_imu(self, message: Any) -> None:
        robot_state.imu = {
            "frame_id": message.header.frame_id,
            "orientation": {
                "x": float(message.orientation.x), "y": float(message.orientation.y),
                "z": float(message.orientation.z), "w": float(message.orientation.w),
            },
            "angular_velocity": {
                "x": float(message.angular_velocity.x), "y": float(message.angular_velocity.y),
                "z": float(message.angular_velocity.z),
            },
            "linear_acceleration": {
                "x": float(message.linear_acceleration.x),
                "y": float(message.linear_acceleration.y),
                "z": float(message.linear_acceleration.z),
            },
        }

    @staticmethod
    def _yaw(orientation: Any) -> float:
        return math.atan2(
            2.0 * (orientation.w * orientation.z + orientation.x * orientation.y),
            1.0 - 2.0 * (orientation.y * orientation.y + orientation.z * orientation.z),
        )

    def _handle_robot_pose(self, message: Any) -> None:
        robot_state.robot_pose = {
            "x": float(message.pose.position.x),
            "y": float(message.pose.position.y),
            "theta": self._yaw(message.pose.orientation),
            "frame_id": message.header.frame_id,
        }

    def _handle_reflector_position(self, message: Any) -> None:
        robot_state.reflector_position = {
            "x": float(message.point.x),
            "y": float(message.point.y),
            "z": float(message.point.z),
            "frame_id": message.header.frame_id,
        }

    def _handle_grid_map(self, message: Any) -> None:
        # Run-length encoding keeps the 5 mm planner grid small enough for the 1 Hz WebSocket.
        runs: list[list[int]] = []
        values = list(message.data)
        if values:
            start = 0
            current = int(values[0])
            for index, raw in enumerate(values[1:], 1):
                value = int(raw)
                if value != current:
                    runs.append([start, index - start, current])
                    start, current = index, value
            runs.append([start, len(values) - start, current])
        robot_state.grid_map = {
            "frame_id": message.header.frame_id,
            "resolution": float(message.info.resolution),
            "width": int(message.info.width),
            "height": int(message.info.height),
            "origin_x": float(message.info.origin.position.x),
            "origin_y": float(message.info.origin.position.y),
            "runs": runs,
        }

    def _handle_paths(self, message: Any) -> None:
        paths: list[dict[str, Any]] = []
        for marker in message.markers:
            if marker.action == 3:  # visualization_msgs/Marker.DELETEALL
                paths.clear()
                continue
            if marker.type != 4 or len(marker.points) < 2:  # LINE_STRIP
                continue
            paths.append({
                "id": int(marker.id),
                "namespace": marker.ns,
                "frame_id": marker.header.frame_id,
                "color": {
                    "r": float(marker.color.r), "g": float(marker.color.g),
                    "b": float(marker.color.b), "a": float(marker.color.a),
                },
                "width": float(marker.scale.x),
                "points": [[float(point.x), float(point.y)] for point in marker.points],
            })
        robot_state.planned_paths = paths

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

    def set_printer_active(self, printer_name: str, active: bool) -> bool:
        if self.printer_active_client is None or not self.printer_active_client.service_is_ready():
            robot_state.add_log("printer/set_active service unavailable")
            return False
        request = SetPrinterActive.Request()
        request.printer_name = printer_name
        request.active = active
        self.printer_active_client.call_async(request)
        return True

    def start_mission(self, file_name: str) -> bool:
        if robot_state.mission_running:
            return False
        if self.plan_client is None or not self.plan_client.service_is_ready():
            robot_state.mission_error = "路径规划服务 /plan_path 不可用"
            return False
        if Path(file_name).name != file_name or Path(file_name).suffix.lower() != ".json":
            robot_state.mission_error = "任务文件必须是 cad 目录中的 JSON 文件名"
            return False
        robot_state.mission_running = True
        robot_state.mission_stage = "planning"
        robot_state.mission_file = file_name
        robot_state.mission_error = ""
        robot_state.mission_completed = 0
        robot_state.mission_total = 0
        request = PlanPath.Request()
        request.file_name = file_name
        self.plan_client.call_async(request).add_done_callback(self._on_plan_complete)
        return True

    def cancel_mission(self) -> bool:
        self._mission_segments.clear()
        if self._goal_handle is not None:
            self._goal_handle.cancel_goal_async()
        self.publish_velocity(0.0, 0.0)
        robot_state.mission_running = False
        robot_state.mission_stage = "cancelled"
        return True

    def _fail_mission(self, message: str) -> None:
        robot_state.mission_running = False
        robot_state.mission_stage = "failed"
        robot_state.mission_error = message
        self.publish_velocity(0.0, 0.0)

    def _on_plan_complete(self, future: Any) -> None:
        try:
            response = future.result()
            if not response.success:
                self._fail_mission(response.error or "路径规划失败")
                return
            stem = Path(robot_state.mission_file).stem
            plan_path = Path(os.getenv("XLINE_PLANNED_RESULTS_DIR", PLANNED_RESULTS_DIR)) / f"planned_{stem}.json"
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            segments = payload.get("lines", []) if isinstance(payload, dict) else payload
            if not isinstance(segments, list) or not segments:
                self._fail_mission("规划结果中没有可执行路径")
                return
            self._mission_segments = [item for item in segments if isinstance(item, dict)]
            self._mission_index = 0
            robot_state.mission_total = len(self._mission_segments)
            robot_state.mission_stage = "executing"
            self._send_next_segment()
        except Exception as error:
            self._fail_mission(f"读取规划结果失败: {error}")

    def _send_next_segment(self) -> None:
        if not robot_state.mission_running:
            return
        if self._mission_index >= len(self._mission_segments):
            robot_state.mission_running = False
            robot_state.mission_stage = "completed"
            self.publish_velocity(0.0, 0.0)
            return
        if self.execute_client is None or not self.execute_client.server_is_ready():
            self._fail_mission("动作服务 /execute_plan 不可用")
            return
        segment = self._mission_segments[self._mission_index]
        goal = ExecutePlan.Goal()
        goal.plan_json = json.dumps(segment, ensure_ascii=False)
        goal.plan_uid = f"app_{robot_state.mission_file}_{segment.get('id', self._mission_index)}"
        self.execute_client.send_goal_async(
            goal, feedback_callback=self._on_mission_feedback
        ).add_done_callback(self._on_goal_response)

    def _on_goal_response(self, future: Any) -> None:
        try:
            self._goal_handle = future.result()
            if not self._goal_handle.accepted:
                self._fail_mission("底盘拒绝执行路径")
                return
            self._goal_handle.get_result_async().add_done_callback(self._on_goal_result)
        except Exception as error:
            self._fail_mission(f"发送路径失败: {error}")

    def _on_mission_feedback(self, feedback: Any) -> None:
        robot_state.mission_current_id = int(feedback.feedback.current_id)

    def _on_goal_result(self, future: Any) -> None:
        try:
            result = future.result().result
            if not result.success:
                self._fail_mission(result.error_message or "路径执行失败")
                return
            self._mission_index += 1
            robot_state.mission_completed = self._mission_index
            self._send_next_segment()
        except Exception as error:
            self._fail_mission(f"路径执行异常: {error}")


ros_adapter = RobotRosAdapter()
