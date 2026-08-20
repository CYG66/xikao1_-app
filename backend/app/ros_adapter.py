from __future__ import annotations

import json
import math
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import (
    CAN_INTERFACE,
    CAN_TRANSPORT,
    EXECUTE_PLAN_ACTION,
    HARDWARE_LAUNCH_LOG,
    HARDWARE_LAUNCH_PID,
    MAX_ANGULAR_VELOCITY,
    MAX_LINEAR_VELOCITY,
    PLANNED_RESULTS_DIR,
    USE_TOTAL_STATION,
    USB2CAN_DEVICE,
    XLINE_WS_DIR,
    XLINE_SETUP_FILE,
    services,
    topics,
)
from .state import robot_state
from .mission_analysis import analyze_mission, segment_endpoint_m
from .mission_ledger import mission_ledger
from .mission_quality import score_planned_mission
from .mission_reports import build_acceptance_report
from .drawing_versions import drawing_versions
from .drawing_store import preview_paths
from .oscillation import HeadingOscillationDetector


def planner_cad_path(file_name: str) -> str:
    cad_root = Path(os.getenv("XLINE_CAD_DIR", str(Path(XLINE_WS_DIR) / "cad")))
    return str((cad_root / file_name).resolve())


def classify_planned_segment(segment: dict[str, Any]) -> str:
    """Classify an xline_cyg planned segment without changing its schema."""
    ink = segment.get("ink")
    ink_enabled = isinstance(ink, dict) and ink.get("enabled") is True
    layer_id = segment.get("layer_id")
    transition = (
        segment.get("work") is False
        or (isinstance(layer_id, int) and layer_id >= 1_000_000)
        or not ink_enabled
    )
    return "travel" if transition else "printing"


def planned_ink_fingerprint(segment: dict[str, Any]) -> str | None:
    """Return a direction-independent key for duplicate printing segments."""
    if classify_planned_segment(segment) != "printing":
        return None

    def point(value: Any) -> tuple[float, float, float] | None:
        if not isinstance(value, dict):
            return None
        try:
            return tuple(round(float(value.get(axis, 0.0)), 3) for axis in ("x", "y", "z"))
        except (TypeError, ValueError):
            return None

    geometry_type = str(segment.get("type", "")).lower()
    geometry: Any
    if geometry_type == "line":
        ends = [point(segment.get("start")), point(segment.get("end"))]
        geometry = sorted(item for item in ends if item is not None)
    elif geometry_type in {"polyline", "spline"}:
        raw_points = segment.get("vertices", segment.get("control_points", []))
        points = [item for item in (point(raw) for raw in raw_points) if item is not None]
        reverse = list(reversed(points))
        geometry = min(points, reverse) if points else []
    else:
        geometry = {
            key: segment.get(key)
            for key in (
                "center", "radius", "major_axis", "ratio", "start_angle",
                "end_angle", "rotation", "position", "content",
            )
            if key in segment
        }
    ink = segment.get("ink", {})
    identity = {
        "type": geometry_type,
        "geometry": geometry,
        "printer": ink.get("printer", "center"),
        "mode": ink.get("mode", "solid"),
        "content": ink.get("content", segment.get("content", "")),
    }
    return json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

try:
    import rclpy
    from geometry_msgs.msg import PointStamped, PoseStamped, Twist
    from nav_msgs.msg import OccupancyGrid, Odometry
    from rclpy.action import ActionClient
    from rclpy.node import Node
    from sensor_msgs.msg import Imu, JointState
    from std_msgs.msg import Bool, Float32MultiArray, Int32, String
    from std_srvs.srv import Trigger
    from visualization_msgs.msg import MarkerArray

    try:
        from xline_msgs import action as xline_actions
        from xline_msgs import srv as xline_services
    except Exception:  # pragma: no cover - depends on the robot workspace.
        xline_actions = None
        xline_services = None
    ExecutePlan = getattr(xline_actions, "ExecutePlan", None)
    LnCommand = getattr(xline_services, "LnCommand", None)
    PrinterCommand = getattr(xline_services, "PrinterCommand", None)
    QuickCommand = getattr(xline_services, "QuickCommand", None)
    SetPrinterActive = getattr(xline_services, "SetPrinterActive", None)
    SetPrinterEnabled = getattr(xline_services, "SetPrinterEnabled", None)
    try:
        from xline_path_planner.srv import PlanPath
    except Exception:  # pragma: no cover - depends on the robot workspace.
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
    Bool = None
    Float32MultiArray = None
    Int32 = None
    JointState = None
    Trigger = None
    LnCommand = None
    QuickCommand = None
    SetPrinterActive = None
    SetPrinterEnabled = None
    PrinterCommand = None
    ExecutePlan = None
    PlanPath = None


class RobotRosAdapter:
    def __init__(self) -> None:
        self.node: RobotBackendNode | None = None
        self.thread: threading.Thread | None = None
        self.stop_timer: threading.Timer | None = None
        self.motion_sequence: list[dict[str, float]] = []
        self.motion_sequence_index = 0
        self.motion_step_deadline = 0.0
        self.command_watchdog: threading.Timer | None = None
        self.control_lease_timer: threading.Timer | None = None
        self.hardware_start_lock = threading.Lock()
        self._interface_cache: dict[str, Any] | None = None
        self._interface_cache_at = 0.0
        self._interface_cache_lock = threading.Lock()

    def start(self) -> None:
        if rclpy is None:
            robot_state.ros_available = False
            robot_state.bridge_mode = "simulated"
            robot_state.online = True
            robot_state.add_log("ROS2 not found, backend started in simulated mode")
            return

        rclpy.init(args=None)
        self.node = RobotBackendNode()
        self.thread = threading.Thread(target=self._spin_ros, daemon=True)
        self.thread.start()
        robot_state.ros_available = True
        robot_state.bridge_mode = "rclpy"
        robot_state.online = True
        robot_state.add_log("ROS2 backend node started")
        self.node.publish_velocity(0.0, 0.0)
        self.node.publish_emergency_stop(True)
        robot_state.emergency_stopped = True
        robot_state.add_log("startup safety stop published")

    def _spin_ros(self) -> None:
        """Treat ROS shutdown during service restart as a normal exit."""
        try:
            rclpy.spin(self.node)
        except Exception as error:
            if rclpy is not None and rclpy.ok():
                robot_state.add_log(f"ROS2 spin stopped unexpectedly: {error}")

    def stop(self) -> None:
        self.fail_safe_stop("backend shutdown")
        if self.node is not None:
            self.node.destroy_node()
        if rclpy is not None and rclpy.ok():
            rclpy.shutdown()
        robot_state.online = False
        robot_state.add_log("backend stopped")

    def interface_snapshot(self) -> dict[str, Any]:
        """Return the ROS2 interfaces visible to this backend node.

        The configured names are included even when a service is temporarily
        unavailable; the discovered names show what is actually present in
        the current ROS graph. This method is informational only.
        """
        with self._interface_cache_lock:
            if self._interface_cache is not None and time.monotonic() - self._interface_cache_at < 2.0:
                return json.loads(json.dumps(self._interface_cache))

        configured_topics = {
            name: getattr(topics, name) for name in topics.__dataclass_fields__
        }
        configured_services = {
            name: getattr(services, name) for name in services.__dataclass_fields__
        }
        configured_actions = {"execute_plan": EXECUTE_PLAN_ACTION}
        discovered_topics: dict[str, list[str]] = {}
        discovered_services: dict[str, list[str]] = {}
        if self.node is not None:
            try:
                discovered_topics = {
                    name: sorted(types)
                    for name, types in self.node.get_topic_names_and_types()
                }
            except Exception as exc:
                robot_state.add_log(f"ROS2 topic discovery unavailable: {exc}")
            try:
                discovered_services = {
                    name: sorted(types)
                    for name, types in self.node.get_service_names_and_types()
                }
            except Exception as exc:
                robot_state.add_log(f"ROS2 service discovery unavailable: {exc}")
        snapshot = {
            "configured_topics": configured_topics,
            "configured_services": configured_services,
            "configured_actions": configured_actions,
            "discovered_topics": discovered_topics,
            "discovered_services": discovered_services,
        }
        with self._interface_cache_lock:
            self._interface_cache = snapshot
            self._interface_cache_at = time.monotonic()
        return json.loads(json.dumps(snapshot))

    def publish_velocity(self, linear: float, angular: float) -> bool:
        # Match the xline_cyg wheel-driver limits.
        linear = max(-MAX_LINEAR_VELOCITY, min(MAX_LINEAR_VELOCITY, linear))
        angular = max(-MAX_ANGULAR_VELOCITY, min(MAX_ANGULAR_VELOCITY, angular))
        if robot_state.emergency_stopped and (linear != 0.0 or angular != 0.0):
            robot_state.add_log("cmd_vel blocked: emergency stop is active")
            return False
        robot_state.last_command = {"type": "cmd_vel", "linear": linear, "angular": angular}
        robot_state.last_velocity_command_at = datetime.now(timezone.utc).isoformat()
        if (linear != 0.0 or angular != 0.0) and not robot_state.control_ready:
            robot_state.add_log("cmd_vel blocked: CAN interface or motor driver is not ready")
            return False
        robot_state.add_log(f"cmd_vel linear={linear:.2f} angular={angular:.2f}")
        if self.node is not None:
            self.node.publish_velocity(linear, angular)
        else:
            robot_state.robot_pose["x"] = round(robot_state.robot_pose.get("x", 0) + linear * 0.1, 3)
            robot_state.robot_pose["theta"] = round(robot_state.robot_pose.get("theta", 0) + angular * 0.1, 3)
        if self.command_watchdog is not None:
            self.command_watchdog.cancel()
        if linear != 0.0 or angular != 0.0:
            self.command_watchdog = threading.Timer(0.35, self.fail_safe_stop, args=("velocity command timeout",))
            self.command_watchdog.daemon = True
            self.command_watchdog.start()
        return True

    def claim_control(self, client_id: str) -> bool:
        now = time.time()
        owner = robot_state.control_owner
        if owner and owner != client_id and robot_state.control_lease_expires_at > now:
            return False
        if owner and owner != client_id:
            self.fail_safe_stop("expired control replaced")
        robot_state.control_owner = client_id
        robot_state.control_lease_expires_at = now + 3.0
        self._schedule_control_lease_watchdog(client_id)
        return True

    def touch_control(self, client_id: str) -> bool:
        if robot_state.control_owner != client_id:
            return False
        robot_state.control_lease_expires_at = time.time() + 3.0
        self._schedule_control_lease_watchdog(client_id)
        return True

    def _schedule_control_lease_watchdog(self, client_id: str) -> None:
        if self.control_lease_timer is not None:
            self.control_lease_timer.cancel()
        self.control_lease_timer = threading.Timer(
            3.1, self._expire_control_lease, args=(client_id,)
        )
        self.control_lease_timer.daemon = True
        self.control_lease_timer.start()

    def _expire_control_lease(self, client_id: str) -> None:
        if (
            robot_state.control_owner == client_id
            and robot_state.control_lease_expires_at <= time.time()
        ):
            self.release_control(client_id, "control heartbeat timeout")

    def owns_control(self, client_id: str) -> bool:
        return (
            bool(client_id)
            and robot_state.control_owner == client_id
            and robot_state.control_lease_expires_at > time.time()
        )

    def release_control(self, client_id: str, reason: str = "control released") -> None:
        if robot_state.control_owner == client_id:
            if self.control_lease_timer is not None:
                self.control_lease_timer.cancel()
                self.control_lease_timer = None
            robot_state.control_owner = None
            robot_state.control_lease_expires_at = 0.0
            self.fail_safe_stop(reason)

    def fail_safe_stop(self, reason: str) -> None:
        if self.stop_timer is not None:
            self.stop_timer.cancel()
            self.stop_timer = None
        if self.command_watchdog is not None:
            self.command_watchdog.cancel()
            self.command_watchdog = None
        robot_state.last_command = {"type": "cmd_vel", "linear": 0.0, "angular": 0.0, "reason": reason}
        robot_state.linear_velocity = 0.0
        robot_state.agent_motion_active = False
        robot_state.agent_motion_deadline = 0.0
        robot_state.agent_motion_command = {}
        self.motion_sequence = []
        self.motion_sequence_index = 0
        self.motion_step_deadline = 0.0
        if self.node is not None:
            try:
                self.node.publish_velocity(0.0, 0.0)
            except Exception as exc:
                # The ROS context may already be shutting down while a
                # WebSocket disconnect handler is issuing the fail-safe stop.
                # Never let that secondary error terminate FastAPI.
                robot_state.add_log(f"fail-safe ROS publish skipped: {exc}")
        robot_state.add_log(f"fail-safe stop: {reason}")

    def set_emergency_stop(self, active: bool) -> bool:
        if not active:
            # Never release the stop into an absent or half-started drive stack.
            self.fail_safe_stop("prepare emergency stop release")
            if not self.ensure_hardware_runtime():
                robot_state.emergency_stopped = True
                if self.node is not None:
                    self.node.publish_emergency_stop(True)
                self.fail_safe_stop("hardware runtime is not ready")
                return False
            if (
                self.node is not None
                and self.node.emergency_stop_reset_available()
                and not self.node.reset_emergency_stop()
            ):
                robot_state.emergency_stopped = True
                if self.node is not None:
                    self.node.publish_emergency_stop(True)
                self.fail_safe_stop("ROS emergency stop reset failed")
                return False
            if self.node is not None and not self.node.emergency_stop_reset_available():
                robot_state.add_log(
                    "xline_cyg has no emergency reset service; releasing backend software stop"
                )

        robot_state.emergency_stopped = active
        if self.node is not None:
            self.node.publish_emergency_stop(active)
        self.fail_safe_stop("emergency stop" if active else "emergency stop released")
        if active and robot_state.mission_running:
            if self.node is not None and not self.node.pause_mission():
                # Safety takes precedence if the ROS pause service is unavailable.
                self.node.cancel_mission()
            elif self.node is None:
                robot_state.mission_paused = True
                robot_state.mission_stage = "paused"
        return True

    def ensure_hardware_runtime(self, timeout: float = 15.0) -> bool:
        """Start the configured xline_cyg launch once and wait for readiness."""
        with self.hardware_start_lock:
            if self._hardware_runtime_ready():
                robot_state.add_log("hardware runtime already ready")
                return True

            if not self._hardware_launch_running():
                robot_state.add_log(
                    f"starting xline_cyg runtime: use_total_station:={str(USE_TOTAL_STATION).lower()}"
                )
                try:
                    log_path = Path(HARDWARE_LAUNCH_LOG)
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    log_file = log_path.open("ab", buffering=0)
                    command = (
                        "source /opt/ros/humble/setup.bash && "
                        f"source {XLINE_SETUP_FILE} && "
                        "exec ros2 launch xline_bringup system_test.launch.py "
                        f"use_total_station:={str(USE_TOTAL_STATION).lower()} "
                        "enable_foxglove:=false"
                    )
                    process = subprocess.Popen(
                        ["/bin/bash", "-lc", command],
                        stdin=subprocess.DEVNULL,
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    Path(HARDWARE_LAUNCH_PID).write_text(str(process.pid), encoding="ascii")
                    log_file.close()
                except Exception as exc:
                    robot_state.add_log(f"hardware runtime start failed: {exc}")
                    return False

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self._hardware_runtime_ready():
                    robot_state.add_log("hardware runtime ready")
                    return True
                if not self._hardware_launch_running():
                    robot_state.add_log("hardware runtime exited before becoming ready")
                    return False
                time.sleep(0.25)

            robot_state.add_log("hardware runtime readiness timeout")
            return False

    def _hardware_launch_running(self) -> bool:
        try:
            pid = int(Path(HARDWARE_LAUNCH_PID).read_text(encoding="ascii").strip())
            os.kill(pid, 0)
            return True
        except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
            return False

    def _hardware_runtime_ready(self) -> bool:
        if CAN_TRANSPORT == "socketcan" and not self._can_interface_up():
            return False
        if self.node is None:
            return False
        node_names = {name.lstrip("/") for name in self.node.get_node_names()}
        required = {"differential_wheels_driver", "cmd_vel_mux"}
        return required.issubset(node_names)

    @staticmethod
    def _can_interface_up() -> bool:
        try:
            flags = int(Path(f"/sys/class/net/{CAN_INTERFACE}/flags").read_text().strip(), 16)
            return bool(flags & 0x1)
        except (FileNotFoundError, OSError, ValueError):
            return False

    def publish_timed_velocity(self, linear: float, angular: float, duration: float) -> bool:
        if self.stop_timer is not None:
            self.stop_timer.cancel()
            self.stop_timer = None
        if not self.publish_velocity(linear, angular):
            return False
        robot_state.agent_motion_active = True
        robot_state.agent_motion_deadline = time.time() + duration
        robot_state.agent_motion_command = {
            "linear": linear,
            "angular": angular,
            "duration_seconds": duration,
        }
        self.stop_timer = threading.Timer(0.1, self._continue_timed_velocity)
        self.stop_timer.daemon = True
        self.stop_timer.start()
        return True

    def publish_velocity_sequence(self, steps: list[dict[str, float]]) -> bool:
        if not steps:
            return False
        if robot_state.agent_motion_active:
            robot_state.add_log("AI motion sequence rejected: another sequence is active")
            return False
        if self.stop_timer is not None:
            self.stop_timer.cancel()
            self.stop_timer = None
        self.motion_sequence = [dict(step) for step in steps]
        self.motion_sequence_index = 0
        total_duration = sum(float(step["duration_seconds"]) for step in steps)
        robot_state.agent_motion_active = True
        robot_state.agent_motion_deadline = time.time() + total_duration
        robot_state.agent_motion_command = {"steps": self.motion_sequence}
        return self._start_velocity_sequence_step()

    def _start_velocity_sequence_step(self) -> bool:
        if self.motion_sequence_index >= len(self.motion_sequence):
            self.fail_safe_stop("AI motion sequence completed")
            return True
        step = self.motion_sequence[self.motion_sequence_index]
        if not self.publish_velocity(
            float(step["linear"]), float(step["angular"])
        ):
            self.fail_safe_stop("AI motion sequence command rejected")
            return False
        self.motion_step_deadline = time.time() + float(step["duration_seconds"])
        self.stop_timer = threading.Timer(0.1, self._continue_velocity_sequence)
        self.stop_timer.daemon = True
        self.stop_timer.start()
        return True

    def _continue_velocity_sequence(self) -> None:
        self.stop_timer = None
        if not robot_state.agent_motion_active:
            return
        if (
            not robot_state.control_owner
            or robot_state.control_lease_expires_at <= time.time()
            or robot_state.emergency_stopped
            or not robot_state.control_ready
            or robot_state.mission_running
        ):
            self.fail_safe_stop("AI motion sequence safety condition lost")
            return
        if time.time() >= self.motion_step_deadline:
            self.motion_sequence_index += 1
            self._start_velocity_sequence_step()
            return
        step = self.motion_sequence[self.motion_sequence_index]
        if not self.publish_velocity(
            float(step["linear"]), float(step["angular"])
        ):
            self.fail_safe_stop("AI motion sequence command rejected")
            return
        self.stop_timer = threading.Timer(0.1, self._continue_velocity_sequence)
        self.stop_timer.daemon = True
        self.stop_timer.start()

    def _continue_timed_velocity(self) -> None:
        self.stop_timer = None
        if not robot_state.agent_motion_active:
            return
        if time.time() >= robot_state.agent_motion_deadline:
            self.fail_safe_stop("AI motion completed")
            return
        if (
            not robot_state.control_owner
            or robot_state.control_lease_expires_at <= time.time()
            or robot_state.emergency_stopped
            or not robot_state.control_ready
            or robot_state.mission_running
        ):
            self.fail_safe_stop("AI motion safety condition lost")
            return
        command = robot_state.agent_motion_command
        if not self.publish_velocity(
            float(command.get("linear", 0.0)),
            float(command.get("angular", 0.0)),
        ):
            self.fail_safe_stop("AI motion command rejected")
            return
        self.stop_timer = threading.Timer(0.1, self._continue_timed_velocity)
        self.stop_timer.daemon = True
        self.stop_timer.start()

    def stop_agent_motion(self, reason: str = "AI motion stopped by operator") -> bool:
        self.fail_safe_stop(reason)
        return True

    def control_mission(self, running: bool, file_name: str = "test_pattern.json") -> bool:
        return self.control_mission_action("start" if running else "cancel", file_name)

    def prepare_mission(self, file_name: str) -> bool:
        if robot_state.bridge_mode == "virtual_ros2":
            robot_state.mission_file = file_name
            robot_state.mission_stage = "ready"
            robot_state.mission_running = False
            robot_state.mission_total = len(robot_state.planned_paths)
            robot_state.mission_error = ""
            return True
        if self.node is None:
            robot_state.mission_error = "ROS2 unavailable"
            return False
        return self.node.prepare_mission(file_name)

    def execute_prepared_mission(self, file_name: str) -> bool:
        if robot_state.bridge_mode == "virtual_ros2":
            return self.control_mission_action("start", file_name)
        if self.node is None:
            robot_state.mission_error = "ROS2 unavailable"
            return False
        return self.node.execute_prepared_mission(file_name)

    def prepared_mission_validation_errors(self) -> list[str]:
        if robot_state.bridge_mode == "virtual_ros2":
            return []
        if self.node is None:
            return ["ROS2 后端不可用"]
        return self.node._runtime_validation_errors()

    def control_mission_action(self, action: str, file_name: str = "test_pattern.json") -> bool:
        if action in {"start", "resume"} and robot_state.emergency_stopped:
            robot_state.mission_error = "Emergency stop is active"
            return False
        if robot_state.bridge_mode == "virtual_ros2":
            if action == "start":
                robot_state.mission_running = True
                robot_state.mission_paused = False
                robot_state.mission_completed = 0
                robot_state.mission_total = 8
                robot_state.pose_trace = [[
                    float(robot_state.robot_pose.get("x", 0)),
                    float(robot_state.robot_pose.get("y", 0)),
                ]]
            elif action == "pause":
                robot_state.mission_paused = True
            elif action == "resume":
                robot_state.mission_paused = False
                robot_state.mission_running = True
            else:
                robot_state.mission_running = False
                robot_state.mission_paused = False
            robot_state.mission_file = file_name
            robot_state.mission_stage = {
                "start": "executing", "pause": "paused",
                "resume": "executing", "cancel": "cancelled",
            }.get(action, "cancelled")
            if action in {"pause", "cancel"}:
                self.publish_velocity(0.0, 0.0)
            return True
        if self.node is None:
            robot_state.add_log("mission blocked: ROS2 unavailable")
            return False
        if action == "start":
            return self.node.start_mission(file_name)
        if action == "pause":
            return self.node.pause_mission()
        if action == "resume":
            return self.node.resume_mission()
        return self.node.cancel_mission()

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

    def set_printer_enabled(self, printer_name: str, enabled: bool) -> bool:
        if self.node is None:
            return False
        return self.node.set_printer_enabled(printer_name, enabled)

    def send_printer_command(self, printer_name: str, json_data: str) -> bool:
        if self.node is None:
            return False
        return self.node.send_printer_command(printer_name, json_data)

    def call_ln150(self, command_type: int) -> bool:
        robot_state.last_command = {"type": "ln150", "command_type": command_type}
        robot_state.add_log(f"ln150 command_type={command_type}")
        if self.node is not None:
            return self.node.call_ln150(command_type)
        return False

    def calibrate_localization(self) -> bool:
        if self.node is None:
            return False
        return self.node.calibrate_localization()


class RobotBackendNode(Node):
    # xline_cyg currently launches the wheel driver and names the C++ task
    # controller motion_control_center. Older installed deployments may use
    # base_controller, so it remains an alias without changing ROS2.
    control_node_aliases = (
        {"differential_wheels_driver"},
        {"motion_control_center"},
        {"base_controller"},
    )
    control_nodes = {"cmd_vel_mux"}
    mission_nodes = control_nodes | {"path_planner"}
    mission_controller_aliases = ("motion_control_center", "base_controller")
    localization_nodes = {"localization", "odom_imu_localization"}

    def __init__(self) -> None:
        super().__init__("xline_app_backend")
        self.cmd_vel_pub = self.create_publisher(Twist, topics.tablet_cmd_vel, 10)
        self.emergency_stop_pub = self.create_publisher(Bool, topics.emergency_stop, 10)
        self.emergency_stop_reset_client = (
            self.create_client(Trigger, services.emergency_stop_reset)
            if Trigger is not None
            else None
        )
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
        self.printer_enabled_client = (
            self.create_client(SetPrinterEnabled, services.printer_set_enabled)
            if SetPrinterEnabled is not None else None
        )
        self.printer_command_client = (
            self.create_client(PrinterCommand, services.printer_send_command)
            if PrinterCommand is not None else None
        )
        self.plan_client = (
            self.create_client(PlanPath, services.plan_path) if PlanPath is not None else None
        )
        self.execute_client = (
            ActionClient(self, ExecutePlan, EXECUTE_PLAN_ACTION) if ExecutePlan is not None else None
        )
        self.pause_client = (
            self.create_client(Trigger, services.execution_pause) if Trigger is not None else None
        )
        self.resume_client = (
            self.create_client(Trigger, services.execution_resume) if Trigger is not None else None
        )
        self.calibration_client = (
            self.create_client(Trigger, services.localization_calibrate) if Trigger is not None else None
        )
        self._mission_segments: list[dict[str, Any]] = []
        self._mission_index = 0
        self._goal_handle: Any = None
        self._mission_feedback_id: int | None = None
        self._oscillation_detector = HeadingOscillationDetector()
        self.create_subscription(Imu, topics.imu, self._handle_imu, 10)
        self.create_subscription(PoseStamped, topics.robot_pose, self._handle_robot_pose, 10)
        self.create_subscription(
            Bool, topics.localization_valid, self._handle_localization_valid, 10
        )
        self.create_subscription(
            PointStamped, topics.reflector_position, self._handle_reflector_position, 10
        )
        self._subscribe_json(topics.printer_status, "printer_status")
        self._subscribe_json(topics.ln150_status, "ln150_status")
        self.create_subscription(Int32, topics.ln150_battery, self._handle_battery, 10)
        self.create_subscription(Odometry, topics.odom, self._handle_odometry, 10)
        self.create_subscription(JointState, topics.joint_states, self._handle_joint_states, 10)
        self.create_subscription(
            Float32MultiArray, topics.obstacle_detected, self._handle_obstacles, 10
        )
        self.create_subscription(Bool, topics.emergency_stop_status, self._handle_emergency_status, 10)
        self._subscribe_json(topics.motor_status, "motor_status")
        map_qos = rclpy.qos.QoSProfile(
            depth=1,
            durability=rclpy.qos.DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=rclpy.qos.ReliabilityPolicy.RELIABLE,
        )
        self.create_subscription(OccupancyGrid, topics.grid_map, self._handle_grid_map, map_qos)
        self.create_subscription(MarkerArray, topics.planned_paths, self._handle_paths, map_qos)
        robot_state.drive_transport = CAN_TRANSPORT
        robot_state.drive_device_path = (
            CAN_INTERFACE if CAN_TRANSPORT == "socketcan" else USB2CAN_DEVICE
        )
        self.create_timer(1.0, self._update_graph_readiness)

    @staticmethod
    def _socketcan_ready(interface: str) -> bool:
        """Return true only when the configured Linux CAN network link is UP."""
        flags_path = Path("/sys/class/net") / interface / "flags"
        try:
            flags = int(flags_path.read_text(encoding="ascii").strip(), 16)
        except (OSError, ValueError):
            return False
        return bool(flags & 0x1)  # Linux IFF_UP

    def _update_graph_readiness(self) -> None:
        """Reflect ROS graph availability without inventing hardware telemetry."""
        available = set(self.get_node_names())
        if CAN_TRANSPORT == "socketcan":
            robot_state.drive_device_connected = self._socketcan_ready(CAN_INTERFACE)
        else:
            robot_state.drive_device_connected = os.path.exists(USB2CAN_DEVICE)
        motor_node_ready = any(alias & available for alias in self.control_node_aliases)
        robot_state.motor_driver_ready = motor_node_ready and robot_state.drive_device_connected
        robot_state.control_ready = (
            self.control_nodes.issubset(available)
            and robot_state.motor_driver_ready
        )
        localization_ready = bool(self.localization_nodes & available)
        mission_controller_ready = any(
            name in available for name in self.mission_controller_aliases
        )
        robot_state.mission_nodes_ready = (
            self.mission_nodes.issubset(available)
            and mission_controller_ready
            and localization_ready
        )
        missing = set(self.mission_nodes - available)
        if not mission_controller_ready:
            missing.add("motion_control_center|base_controller")
        if not localization_ready:
            missing.add("localization|odom_imu_localization")
        robot_state.missing_required_nodes = sorted(missing)
        robot_state.ln150_ready = "ln150_driver" in available
        if "localization" in available and robot_state.ln150_ready:
            robot_state.localization_source = "ln150_imu"
        elif "odom_imu_localization" in available:
            robot_state.localization_source = "odom_imu_relative"
        else:
            robot_state.localization_source = "unavailable"
        robot_state.printer_ready = "inkjet_printer_node" in available
        robot_state.localization_calibration_available = (
            self.calibration_client is not None
            and self.calibration_client.service_is_ready()
        )

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

    def _handle_joint_states(self, message: Any) -> None:
        velocities = dict(zip(message.name, message.velocity))
        robot_state.wheel_speeds = {
            "joints_rad_s": {name: float(value) for name, value in velocities.items()},
            "source": "joint_states",
        }

    def _handle_obstacles(self, message: Any) -> None:
        values = list(message.data)
        if len(values) >= 4:
            robot_state.obstacle_distances = dict(zip(
                ("front", "back", "left", "right"),
                (float(value) if float(value) > 0 else None for value in values[:4]),
            ))
            robot_state.obstacle_updated_at = time.time()

    def _handle_battery(self, message: Any) -> None:
        robot_state.battery = max(0, min(100, int(message.data)))

    def _handle_emergency_status(self, message: Any) -> None:
        robot_state.emergency_stopped = bool(message.data)

    def _handle_localization_valid(self, message: Any) -> None:
        robot_state.localization_valid = bool(message.data)

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
        if robot_state.mission_running and not robot_state.mission_paused:
            pose = robot_state.robot_pose
            try:
                event = self._oscillation_detector.add(
                    time.time(), float(message.angular_velocity.z),
                    float(pose.get("x")), float(pose.get("y")),
                )
            except (TypeError, ValueError):
                event = None
            if event is not None:
                event.update({"segment_index": self._mission_index,
                              "detected_at": datetime.now(timezone.utc).isoformat()})
                robot_state.oscillation_detected = True
                if robot_state.mission_ledger_id:
                    mission_ledger.append_oscillation(robot_state.mission_ledger_id, event)
                self._fail_mission("检测到航向左右摆动，任务已停车，禁止自动恢复")

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
        robot_state.last_pose_update_at = time.time()
        point = [robot_state.robot_pose["x"], robot_state.robot_pose["y"]]
        if not robot_state.pose_trace or math.dist(robot_state.pose_trace[-1], point) >= 0.02:
            robot_state.pose_trace.append(point)
            del robot_state.pose_trace[:-2000]

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
        robot_state.last_map_update_at = time.time()

    def _handle_paths(self, message: Any) -> None:
        paths: list[dict[str, Any]] = []
        annotations: list[dict[str, Any]] = []
        for marker in message.markers:
            if marker.action == 3:  # visualization_msgs/Marker.DELETEALL
                paths.clear()
                annotations.clear()
                continue
            if marker.type == 9 and marker.ns == "path_texts":  # TEXT_VIEW_FACING
                annotations.append({
                    "id": int(marker.id),
                    "text": str(marker.text),
                    "frame_id": marker.header.frame_id,
                    "x": float(marker.pose.position.x),
                    "y": float(marker.pose.position.y),
                    "height": float(marker.scale.z),
                })
                continue
            if marker.type != 4 or len(marker.points) < 2:  # LINE_STRIP
                continue
            route_type = "drawing" if float(marker.color.b) > 0.8 else "transition"
            paths.append({
                "id": int(marker.id),
                "namespace": marker.ns,
                "frame_id": marker.header.frame_id,
                "color": {
                    "r": float(marker.color.r), "g": float(marker.color.g),
                    "b": float(marker.color.b), "a": float(marker.color.a),
                },
                "width": float(marker.scale.x),
                "route_type": route_type,
                "points": [[float(point.x), float(point.y)] for point in marker.points],
            })
        robot_state.planned_paths = paths
        robot_state.path_annotations = annotations
        robot_state.last_paths_update_at = time.time()

    def _subscribe_json(self, topic: str, key: str) -> None:
        def handle(message: Any) -> None:
            value = getattr(message, "data", message)
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    pass
            setattr(robot_state, key, value)
            if key == "motor_status" and isinstance(value, dict):
                robot_state.motor_driver_ready = value.get("ready") is True
                robot_state.drive_device_connected = value.get("connected") is True
                robot_state.wheel_speeds = {
                    "left_mps": value.get("left_wheel_mps"),
                    "right_mps": value.get("right_wheel_mps"),
                    "source": value.get("velocity_source", "unknown"),
                }
            if key == "ln150_status":
                text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
                match = re.search(r"(?:battery|电池)[^0-9]{0,20}(\d{1,3})(?:\s*%)?", text, re.IGNORECASE)
                if match:
                    robot_state.battery = max(0, min(100, int(match.group(1))))

        try:
            self.create_subscription(String, topic, handle, 10)
        except Exception:
            robot_state.add_log(f"skip subscription {topic}")

    def publish_velocity(self, linear: float, angular: float) -> bool:
        message = Twist()
        message.linear.x = linear
        message.angular.z = angular
        try:
            self.cmd_vel_pub.publish(message)
            return True
        except Exception as exc:
            robot_state.add_log(f"ROS cmd_vel publish failed: {exc}")
            return False

    def publish_emergency_stop(self, active: bool) -> bool:
        message = Bool()
        message.data = active
        try:
            self.emergency_stop_pub.publish(message)
            return True
        except Exception as exc:
            robot_state.add_log(f"ROS emergency stop publish failed: {exc}")
            return False

    def reset_emergency_stop(self, timeout: float = 3.0) -> bool:
        client = self.emergency_stop_reset_client
        if client is None or not client.wait_for_service(timeout_sec=timeout):
            robot_state.add_log("emergency stop reset service unavailable")
            return False

        completed = threading.Event()
        outcome = {"success": False}

        def handle_response(future: Any) -> None:
            try:
                response = future.result()
                outcome["success"] = bool(response and response.success)
                if response is not None and response.message:
                    robot_state.add_log(f"emergency reset: {response.message}")
            except Exception as exc:
                robot_state.add_log(f"emergency reset failed: {exc}")
            finally:
                completed.set()

        client.call_async(Trigger.Request()).add_done_callback(handle_response)
        if not completed.wait(timeout):
            robot_state.add_log("emergency stop reset response timeout")
            return False
        return outcome["success"]

    def emergency_stop_reset_available(self) -> bool:
        client = self.emergency_stop_reset_client
        return client is not None and client.service_is_ready()

    def calibrate_localization(self) -> bool:
        if self.calibration_client is None or not self.calibration_client.service_is_ready():
            robot_state.localization_calibration = "unavailable"
            robot_state.add_log("localization calibration service unavailable")
            return False
        robot_state.localization_calibration = "calibrating"
        self.calibration_client.call_async(Trigger.Request()).add_done_callback(
            self._on_calibration_response
        )
        return True

    def _on_calibration_response(self, future: Any) -> None:
        try:
            response = future.result()
            robot_state.localization_calibration = "accepted" if response.success else "failed"
            robot_state.add_log(f"localization calibration: {response.message}")
        except Exception as error:
            robot_state.localization_calibration = "failed"
            robot_state.add_log(f"localization calibration failed: {error}")

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

    def set_printer_enabled(self, printer_name: str, enabled: bool) -> bool:
        if self.printer_enabled_client is None or not self.printer_enabled_client.service_is_ready():
            robot_state.add_log("printer/set_enabled service unavailable")
            return False
        request = SetPrinterEnabled.Request()
        request.printer_name = printer_name
        request.enabled = enabled
        self.printer_enabled_client.call_async(request)
        return True

    def send_printer_command(self, printer_name: str, json_data: str) -> bool:
        if self.printer_command_client is None or not self.printer_command_client.service_is_ready():
            robot_state.add_log("printer/send_command service unavailable")
            return False
        try:
            json.loads(json_data)
        except json.JSONDecodeError:
            robot_state.add_log("printer command rejected: invalid JSON")
            return False
        request = PrinterCommand.Request()
        request.printer_name = printer_name
        request.json_data = json_data
        self.printer_command_client.call_async(request)
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
        robot_state.mission_paused = False
        robot_state.mission_stage = "planning"
        robot_state.mission_file = file_name
        robot_state.mission_error = ""
        robot_state.mission_completed = 0
        robot_state.pose_trace = []
        robot_state.mission_total = 0
        robot_state.mission_required_printers = []
        request = PlanPath.Request()
        request.file_name = planner_cad_path(file_name)
        self.plan_client.call_async(request).add_done_callback(self._on_plan_complete)
        return True

    def prepare_mission(self, file_name: str) -> bool:
        """Plan and publish a preview without sending any ExecutePlan goal."""
        if robot_state.mission_running:
            robot_state.mission_error = "任务正在执行，不能重新规划"
            return False
        if self.plan_client is None or not self.plan_client.service_is_ready():
            robot_state.mission_error = "路径规划服务 /plan_path 不可用"
            return False
        if Path(file_name).name != file_name or Path(file_name).suffix.lower() != ".json":
            robot_state.mission_error = "任务文件必须是 cad 目录中的 JSON 文件名"
            return False
        self._mission_segments.clear()
        robot_state.mission_running = False
        robot_state.mission_paused = False
        robot_state.mission_stage = "planning_preview"
        robot_state.mission_file = file_name
        robot_state.mission_error = ""
        robot_state.mission_completed = 0
        robot_state.mission_total = 0
        robot_state.mission_summary = {}
        robot_state.mission_validation = {"ok": False, "errors": [], "warnings": []}
        robot_state.mission_ledger_id = None
        robot_state.mission_segment_verification = {}
        robot_state.mission_last_verified_id = None
        request = PlanPath.Request()
        request.file_name = planner_cad_path(file_name)
        self.plan_client.call_async(request).add_done_callback(self._on_preview_plan_complete)
        return True

    def execute_prepared_mission(self, file_name: str) -> bool:
        if robot_state.mission_running:
            robot_state.mission_error = "任务已经在执行"
            return False
        if robot_state.mission_stage != "ready" or robot_state.mission_file != file_name:
            robot_state.mission_error = "该图纸尚未完成规划预览"
            return False
        if not self._mission_segments:
            robot_state.mission_error = "没有已准备的可执行路径"
            return False
        runtime_errors = self._runtime_validation_errors()
        if runtime_errors:
            robot_state.mission_validation = {
                **robot_state.mission_validation,
                "ok": False,
                "errors": list(dict.fromkeys(
                    list(robot_state.mission_validation.get("errors", [])) + runtime_errors
                )),
            }
            robot_state.mission_error = "；".join(runtime_errors)
            return False
        unavailable = self._unavailable_required_printers()
        if unavailable:
            robot_state.mission_error = "Required printers unavailable: " + ", ".join(unavailable)
            return False
        robot_state.mission_running = True
        robot_state.mission_paused = False
        robot_state.mission_stage = "executing"
        robot_state.mission_error = ""
        robot_state.mission_completed = 0
        robot_state.pose_trace = []
        self._mission_index = 0
        if robot_state.mission_ledger_id:
            mission_ledger.set_mission_state(robot_state.mission_ledger_id, "executing")
        self._send_next_segment()
        return True

    def cancel_mission(self) -> bool:
        self._mission_segments.clear()
        if self._goal_handle is not None:
            self._goal_handle.cancel_goal_async()
        self.publish_velocity(0.0, 0.0)
        robot_state.mission_running = False
        robot_state.mission_paused = False
        robot_state.mission_stage = "cancelled"
        if robot_state.mission_ledger_id:
            mission_ledger.set_mission_state(robot_state.mission_ledger_id, "cancelled")
            self._finalize_report("cancelled")
        return True

    def pause_mission(self) -> bool:
        if not robot_state.mission_running or robot_state.mission_paused:
            return False
        if self.pause_client is None or not self.pause_client.service_is_ready():
            robot_state.mission_error = "暂停服务 /execution/pause 不可用"
            return False
        robot_state.mission_paused = True
        robot_state.mission_stage = "paused"
        robot_state.mission_error = ""
        self.publish_velocity(0.0, 0.0)
        self.pause_client.call_async(Trigger.Request()).add_done_callback(
            self._on_pause_response
        )
        return True

    def resume_mission(self) -> bool:
        if not robot_state.mission_running or not robot_state.mission_paused:
            return False
        if self.resume_client is None or not self.resume_client.service_is_ready():
            robot_state.mission_error = "恢复服务 /execution/resume 不可用"
            return False
        robot_state.mission_paused = False
        robot_state.mission_stage = "executing"
        robot_state.mission_error = ""
        self.resume_client.call_async(Trigger.Request()).add_done_callback(
            self._on_resume_response
        )
        return True

    def _on_pause_response(self, future: Any) -> None:
        try:
            response = future.result()
            if response is None or not response.success:
                robot_state.mission_paused = False
                robot_state.mission_stage = "executing"
                robot_state.mission_error = (
                    response.message if response is not None else "暂停服务无响应"
                )
                robot_state.add_log(f"mission pause failed: {robot_state.mission_error}")
                return
            robot_state.add_log(f"mission paused: {response.message}")
        except Exception as error:
            robot_state.mission_paused = False
            robot_state.mission_stage = "executing"
            robot_state.mission_error = f"暂停服务调用异常: {error}"

    def _on_resume_response(self, future: Any) -> None:
        try:
            response = future.result()
            if response is None or not response.success:
                robot_state.mission_paused = True
                robot_state.mission_stage = "paused"
                robot_state.mission_error = (
                    response.message if response is not None else "恢复服务无响应"
                )
                robot_state.add_log(f"mission resume failed: {robot_state.mission_error}")
                return
            robot_state.add_log(f"mission resumed: {response.message}")
        except Exception as error:
            robot_state.mission_paused = True
            robot_state.mission_stage = "paused"
            robot_state.mission_error = f"恢复服务调用异常: {error}"

    def _fail_mission(self, message: str) -> None:
        robot_state.mission_running = False
        robot_state.mission_stage = "failed"
        robot_state.mission_error = message
        self.publish_velocity(0.0, 0.0)
        if robot_state.mission_ledger_id:
            mission_ledger.set_mission_state(robot_state.mission_ledger_id, "failed")
            self._finalize_report("failed")

    def _finalize_report(self, final_state: str) -> None:
        mission_id = robot_state.mission_ledger_id
        if mission_id:
            mission_ledger.set_actual_trace(str(mission_id), list(robot_state.pose_trace))
        mission = mission_ledger.get(mission_id) if mission_id else None
        if mission is None:
            return
        report = build_acceptance_report(
            mission, final_state, robot_state.localization_source,
            list(mission.get("oscillation_events", [])),
        )
        mission_ledger.set_report(str(mission_id), report)
        robot_state.mission_report = report

    def _on_plan_complete(self, future: Any) -> None:
        try:
            response = future.result()
            if not response.success:
                self._fail_mission(response.error or "路径规划失败")
                return
            if not self._load_planned_segments():
                self._fail_mission(robot_state.mission_error)
                return
            unavailable = self._unavailable_required_printers()
            if unavailable:
                self._fail_mission(
                    "Required printers unavailable: " + ", ".join(unavailable)
                )
                return
            self._mission_index = 0
            robot_state.mission_total = len(self._mission_segments)
            robot_state.mission_stage = "executing"
            self._send_next_segment()
        except Exception as error:
            self._fail_mission(f"读取规划结果失败: {error}")

    def _on_preview_plan_complete(self, future: Any) -> None:
        try:
            response = future.result()
            if not response.success:
                robot_state.mission_stage = "failed"
                robot_state.mission_error = response.error or "路径规划失败"
                return
            if not self._load_planned_segments():
                robot_state.mission_stage = "failed"
                return
            robot_state.mission_stage = "ready"
            robot_state.mission_running = False
            robot_state.add_log(f"mission preview ready {robot_state.mission_file}")
        except Exception as error:
            robot_state.mission_stage = "failed"
            robot_state.mission_error = f"读取规划结果失败: {error}"

    def _load_planned_segments(self) -> bool:
        stem = Path(robot_state.mission_file).stem
        file_name = f"planned_{stem}.json"
        configured_dir = os.getenv("XLINE_PLANNED_RESULTS_DIR", "").strip()
        candidate_dirs = [
            Path(configured_dir) if configured_dir else Path(PLANNED_RESULTS_DIR),
            Path(PLANNED_RESULTS_DIR),
            Path(XLINE_WS_DIR) / "other" / "planned_results",
            Path("/home/qingz/xline_ws3/other/planned_results"),
        ]
        plan_path = next(
            (directory / file_name for directory in candidate_dirs
             if (directory / file_name).is_file()),
            None,
        )
        if plan_path is None:
            searched = ", ".join(str(directory / file_name) for directory in candidate_dirs)
            robot_state.mission_error = f"规划服务已返回成功，但找不到规划结果文件；已检查：{searched}"
            return False
        try:
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            robot_state.mission_error = f"规划结果文件无法读取：{plan_path}（{error}）"
            return False
        segments = payload.get("lines", []) if isinstance(payload, dict) else payload
        if not isinstance(segments, list) or not segments:
            robot_state.mission_error = "规划结果中没有可执行路径"
            return False
        filtered: list[dict[str, Any]] = []
        seen_ink_paths: set[str] = set()
        duplicate_count = 0
        for item in segments:
            if not isinstance(item, dict):
                continue
            fingerprint = planned_ink_fingerprint(item)
            if fingerprint is not None and fingerprint in seen_ink_paths:
                duplicate_count += 1
                continue
            if fingerprint is not None:
                seen_ink_paths.add(fingerprint)
            filtered.append(item)
        self._mission_segments = filtered
        robot_state.mission_duplicate_ink_paths = duplicate_count
        if duplicate_count:
            robot_state.add_log(f"filtered {duplicate_count} duplicate ink paths")
        robot_state.mission_required_printers = sorted({
            str(item.get("ink", {}).get("printer", "center")).lower()
            for item in self._mission_segments
            if isinstance(item.get("ink"), dict) and item["ink"].get("enabled") is True
        })
        summary, validation = analyze_mission(
            self._mission_segments,
            classify_planned_segment,
            duplicate_count,
            robot_state.localization_source,
        )
        robot_state.mission_summary = summary
        robot_state.mission_validation = validation
        quality = score_planned_mission(self._mission_segments, summary, validation)
        robot_state.mission_quality = quality
        robot_state.mission_total = len(self._mission_segments)
        if not validation["ok"]:
            robot_state.mission_error = "；".join(validation["errors"])
            return False
        ledger = mission_ledger.create(
            robot_state.mission_file,
            summary,
            self._mission_segments,
            classify_planned_segment,
            quality,
            drawing_versions.find_by_file(robot_state.mission_file),
            [
                {
                    "namespace": "planned_mission",
                    "route_type": "planned",
                    "points": points,
                }
                for points in preview_paths({"lines": self._mission_segments})
                if len(points) >= 2
            ],
            project_id=(drawing_versions.find_by_file(robot_state.mission_file) or {}).get("project_id"),
        )
        robot_state.mission_ledger_id = str(ledger["id"])
        robot_state.mission_error = ""
        return True

    def _runtime_validation_errors(self) -> list[str]:
        errors: list[str] = []
        if robot_state.emergency_stopped:
            errors.append("急停仍处于激活状态")
        if not robot_state.mission_nodes_ready:
            errors.append("路径规划或执行节点未就绪")
        if not robot_state.localization_valid:
            errors.append("定位无效，禁止执行规划路径")
        pose_age = time.time() - robot_state.last_pose_update_at if robot_state.last_pose_update_at else math.inf
        if pose_age > 2.0:
            errors.append("位姿遥测已超过 2 秒未更新")
        unavailable = self._unavailable_required_printers()
        if unavailable:
            errors.append("喷头未连接或未启用: " + ", ".join(unavailable))
        return errors

    def _unavailable_required_printers(self) -> list[str]:
        unavailable: list[str] = []
        for printer in robot_state.mission_required_printers:
            status = robot_state.printer_status.get(f"printer_{printer}", {})
            if not isinstance(status, dict) or status.get("connected") is not True or status.get("enabled") is not True:
                unavailable.append(printer)
        return unavailable

    def _send_next_segment(self) -> None:
        if not robot_state.mission_running or robot_state.mission_paused:
            return
        if self._mission_index >= len(self._mission_segments):
            robot_state.mission_running = False
            robot_state.mission_stage = "completed"
            if robot_state.mission_ledger_id:
                mission_ledger.set_mission_state(robot_state.mission_ledger_id, "completed")
                self._finalize_report("completed")
            self.publish_velocity(0.0, 0.0)
            return
        if self.execute_client is None or not self.execute_client.server_is_ready():
            self._fail_mission("动作服务 /execute_plan 不可用")
            return
        segment = self._mission_segments[self._mission_index]
        precheck = self._precheck_segment(segment)
        robot_state.mission_checkpoint = precheck
        if robot_state.mission_ledger_id:
            mission_ledger.record_precheck(robot_state.mission_ledger_id, self._mission_index, precheck)
        if not precheck["ok"]:
            self._fail_mission("分段执行前检查失败: " + "；".join(precheck["errors"]))
            return
        self._mission_feedback_id = None
        if robot_state.mission_ledger_id:
            mission_ledger.start_segment(robot_state.mission_ledger_id, self._mission_index)
        goal = ExecutePlan.Goal()
        goal.plan_json = json.dumps(segment, ensure_ascii=False)
        goal.plan_uid = f"app_{robot_state.mission_file}_{segment.get('id', self._mission_index)}"
        self.execute_client.send_goal_async(
            goal, feedback_callback=self._on_mission_feedback
        ).add_done_callback(self._on_goal_response)

    def _precheck_segment(self, segment: dict[str, Any]) -> dict[str, Any]:
        errors = self._runtime_validation_errors()
        if classify_planned_segment(segment) == "printing":
            ink = segment.get("ink", {})
            printer = str(ink.get("printer", "center")).lower()
            status = robot_state.printer_status.get(f"printer_{printer}", {})
            if not isinstance(status, dict) or status.get("connected") is not True or status.get("enabled") is not True:
                errors.append(f"当前分段喷头 {printer} 未连接或未启用")
        return {"ok": not errors, "segment_id": segment.get("id"), "errors": errors,
                "checked_at": datetime.now(timezone.utc).isoformat()}

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
        self._mission_feedback_id = int(feedback.feedback.current_id)
        robot_state.mission_current_id = self._mission_feedback_id

    def _verify_completed_segment(self, segment: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        expected_id = segment.get("id")
        if self._mission_feedback_id is not None and str(self._mission_feedback_id) != str(expected_id):
            errors.append(
                f"执行反馈段 id {self._mission_feedback_id} 与预期 {expected_id} 不一致"
            )
        if robot_state.emergency_stopped:
            errors.append("分段完成时急停已激活")
        if not robot_state.localization_valid:
            errors.append("分段完成后定位无效")
        pose_age = time.time() - robot_state.last_pose_update_at if robot_state.last_pose_update_at else math.inf
        if pose_age > 2.0:
            errors.append("分段完成后位姿遥测过期")

        kind = classify_planned_segment(segment)
        if kind == "printing":
            ink = segment.get("ink", {})
            printer = str(ink.get("printer", "center")).lower()
            status = robot_state.printer_status.get(f"printer_{printer}", {})
            if not isinstance(status, dict) or status.get("connected") is not True:
                errors.append(f"喷头 {printer} 已断开")
            elif status.get("enabled") is not True:
                errors.append(f"喷头 {printer} 已停用")

        endpoint = segment_endpoint_m(segment)
        pose_x = robot_state.robot_pose.get("x")
        pose_y = robot_state.robot_pose.get("y")
        distance = None
        try:
            if endpoint is not None:
                distance = math.dist((float(pose_x), float(pose_y)), endpoint)
        except (TypeError, ValueError):
            distance = None
        if distance is None:
            if kind == "printing":
                errors.append("无法验证喷墨段终点位姿")
            else:
                warnings.append("无法验证转场段终点位姿")
        elif distance > 0.35:
            errors.append(f"分段终点偏差 {distance:.3f} m，超过 0.350 m")

        return {
            "ok": not errors,
            "segment_id": expected_id,
            "kind": kind,
            "feedback_id": self._mission_feedback_id,
            "endpoint_error_m": round(distance, 4) if distance is not None else None,
            "pose_age_ms": int(pose_age * 1000) if math.isfinite(pose_age) else None,
            "errors": errors,
            "warnings": warnings,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }

    def _on_goal_result(self, future: Any) -> None:
        if robot_state.mission_paused or not robot_state.mission_running:
            return
        try:
            result = future.result().result
            if not result.success:
                self._fail_mission(result.error_message or "路径执行失败")
                return
            segment = self._mission_segments[self._mission_index]
            verification = self._verify_completed_segment(segment)
            robot_state.mission_segment_verification = verification
            robot_state.mission_checkpoint = verification
            if robot_state.mission_ledger_id:
                mission_ledger.verify_segment(
                    robot_state.mission_ledger_id, self._mission_index, verification
                )
            if not verification["ok"]:
                self._fail_mission("分段验证失败: " + "；".join(verification["errors"]))
                return
            robot_state.mission_last_verified_id = segment.get("id")
            self._mission_index += 1
            robot_state.mission_completed = self._mission_index
            self._send_next_segment()
        except Exception as error:
            self._fail_mission(f"路径执行异常: {error}")


ros_adapter = RobotRosAdapter()
