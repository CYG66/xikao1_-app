from __future__ import annotations

import json
import re
import threading
from .ros_adapter import ros_adapter
from .state import robot_state
from .tooling import authorize_emergency_stop, authorize_tool, validate_tool_arguments


def handle_rosbridge_payload(payload: dict[str, object]) -> dict[str, object]:
    op = payload.get("op")
    topic = payload.get("topic")
    service = payload.get("service")
    client_id = str(payload.get("client_id", ""))

    if op == "claim_control":
        ok = ros_adapter.claim_control(client_id)
        return {
            "op": "control_response",
            "ok": ok,
            "owner": robot_state.control_owner,
            "message": "control lease granted" if ok else "control lease is held by another client",
        }

    if op == "control_heartbeat":
        ok = ros_adapter.touch_control(client_id)
        if not ok:
            ros_adapter.fail_safe_stop("control lease lost")
        return {"op": "control_heartbeat_response", "ok": ok}

    if op == "release_control":
        ros_adapter.release_control(client_id)
        return {"op": "control_response", "ok": True, "owner": None}

    if op == "stop_agent_motion":
        ok = ros_adapter.stop_agent_motion()
        return {"op": "agent_motion_response", "ok": ok, "active": False}

    if op == "subscribe":
        robot_state.add_log(f"subscribe {topic}")
        return {"op": "subscribed", "topic": topic, "ok": True}

    if op == "publish" and topic == "/tablet_cmd_vel":
        if not ros_adapter.owns_control(client_id):
            return {"op": "published", "topic": topic, "ok": False, "message": "control lease required"}
        message = payload.get("msg")
        if isinstance(message, dict):
            linear = _nested_number(message, "linear", "x")
            angular = _nested_number(message, "angular", "z")
            arguments, error = validate_tool_arguments(
                "drive_robot",
                {"linear": linear, "angular": angular, "duration_seconds": 0.1},
            )
            if arguments is None:
                return {"op": "published", "topic": topic, "ok": False, "message": error}
            decision = authorize_tool(
                "drive_robot", arguments, confirmed=True, client_id=client_id
            )
            if not decision.allowed and (linear != 0.0 or angular != 0.0):
                return {"op": "published", "topic": topic, "ok": False, "message": decision.message}
            if robot_state.agent_motion_active:
                ros_adapter.stop_agent_motion("manual App control takeover")
            ok = ros_adapter.publish_velocity(linear, angular)
            return {
                "op": "published",
                "topic": topic,
                "ok": ok,
                "message": "velocity command sent" if ok else "CAN interface or motor driver is not ready",
            }

    if op == "emergency_stop":
        active = payload.get("active") is not False
        decision = authorize_emergency_stop(active, client_id)
        if not decision.allowed:
            return {
                "op": "emergency_stop_response",
                "ok": False,
                "active": True,
                "message": decision.message,
            }
        ok = ros_adapter.set_emergency_stop(active)
        return {
            "op": "emergency_stop_response",
            "ok": ok,
            "active": active if ok else True,
            "message": "emergency stop updated" if ok else "hardware runtime or emergency reset service is not ready",
        }

    if op == "mission_control":
        if not ros_adapter.owns_control(client_id):
            return {"op": "mission_response", "ok": False, "message": "control lease required"}
        action = str(payload.get("action", ""))
        if not action:
            action = "start" if payload.get("running") is True else "cancel"
        file_name = str(payload.get("file_name", "test_pattern.json"))
        running = action in {"start", "resume"}
        arguments, error = validate_tool_arguments(
            "set_mission", {"running": running, "file_name": file_name}
        )
        if arguments is None:
            return {"op": "mission_response", "ok": False, "message": error}
        decision = authorize_tool(
            "set_mission", arguments, confirmed=True, client_id=client_id
        )
        if not decision.allowed:
            return {"op": "mission_response", "ok": False, "message": decision.message}
        ok = ros_adapter.control_mission_action(action, file_name)
        message = robot_state.mission_error
        if ok and robot_state.bridge_mode == "virtual_ros2":
            message = "virtual mission updated"
        return {"op": "mission_response", "ok": ok, "message": message}

    if op == "call_service" and service == "/printer/quick_command":
        args = payload.get("args")
        if isinstance(args, dict):
            if robot_state.bridge_mode == "virtual_ros2":
                robot_state.add_log(f"virtual printer {args.get('action', 'beep')}")
                return {"op": "service_response", "service": service, "ok": True}
            tool_args, error = validate_tool_arguments(
                "control_printer",
                {
                    "printer_name": args.get("printer_name", "center"),
                    "action": args.get("action", "beep"),
                    "param": args.get("param", 0),
                },
            )
            if tool_args is None:
                return {"op": "service_response", "service": service, "ok": False, "message": error}
            decision = authorize_tool("control_printer", tool_args, confirmed=True, client_id=client_id)
            if not decision.allowed:
                return {"op": "service_response", "service": service, "ok": False, "message": decision.message}
            ok = ros_adapter.call_printer(
                str(tool_args["printer_name"]),
                str(tool_args["action"]),
                int(tool_args["param"]),
            )
            message = "" if ok else _printer_unready_message(str(tool_args["printer_name"]))
            return {
                "op": "service_response",
                "service": service,
                "ok": ok,
                "message": message,
            }

    if op == "printer_spray":
        printer_name = str(payload.get("printer_name", "center"))
        spraying = payload.get("spraying") is True
        if f"printer_{printer_name}" not in robot_state.printer_status:
            return {
                "op": "printer_spray_response",
                "ok": False,
                "spraying": False,
                "message": "喷码机未配置",
            }
        if not ros_adapter.owns_control(client_id):
            return {
                "op": "printer_spray_response",
                "ok": False,
                "spraying": False,
                "message": "control lease required",
            }
        if spraying:
            printer = robot_state.printer_status.get(f"printer_{printer_name}")
            if not isinstance(printer, dict) or printer.get("connected") is not True:
                return {
                    "op": "printer_spray_response",
                    "ok": False,
                    "spraying": False,
                    "message": "喷码机未连接",
                }
            if ros_adapter.node is not None:
                ros_adapter.node.set_manual_spray_state(printer_name, "starting")
            # xline_ws3's active flag only permits commands. Load a printable
            # message before triggering, otherwise the UI can appear active
            # while the print head has no content to emit.
            def start_manual_spray() -> None:
                try:
                    if not ros_adapter.ensure_printer_active(printer_name, timeout=3.0):
                        if ros_adapter.node is not None:
                            ros_adapter.node.set_manual_spray_state(
                                printer_name, "error", "喷码机激活超时"
                            )
                        robot_state.add_log(
                            f"printer {printer_name} activation timed out"
                        )
                        return
                    current = robot_state.printer_status.get(f"printer_{printer_name}")
                    if (
                        not isinstance(current, dict)
                        or current.get("spray_state") != "starting"
                    ):
                        robot_state.add_log(
                            f"printer {printer_name} manual spray start cancelled"
                        )
                        return
                    if ros_adapter.node is None:
                        raise RuntimeError("ROS2 喷码节点不可用")
                    ros_adapter.node.start_manual_line_spray(printer_name)
                except Exception as error:
                    if ros_adapter.node is not None:
                        ros_adapter.node.set_manual_spray_state(
                            printer_name, "error", f"喷墨开启异常: {error}"
                        )
                    robot_state.add_log(
                        f"printer {printer_name} manual spray crashed: {error}"
                    )

            threading.Thread(target=start_manual_spray, daemon=True).start()
            return {
                "op": "printer_spray_response",
                "ok": True,
                "spraying": False,
                "printer_name": printer_name,
                "spray_state": "starting",
                "message": "正在准备线条并确认真实喷墨，完成后可同时遥控小车",
            }

        if ros_adapter.node is not None:
            ros_adapter.node.set_manual_spray_state(printer_name, "stopping")
        stop_ok = ros_adapter.call_printer(printer_name, "stop_print", 0)
        if not stop_ok and ros_adapter.node is not None:
            ros_adapter.node.set_manual_spray_state(
                printer_name, "error", "停止喷墨请求失败"
            )
        return {
            "op": "printer_spray_response",
            "ok": stop_ok,
            "spraying": False,
            "printer_name": printer_name,
            "spray_state": "stopping" if stop_ok else "error",
            "message": "喷墨已停止" if stop_ok else "停止喷墨失败",
        }

    if op == "call_service" and service == "/printer/set_active":
        args = payload.get("args")
        if isinstance(args, dict):
            if robot_state.bridge_mode == "virtual_ros2":
                target = str(args.get("printer_name", "center"))
                status = robot_state.printer_status.get(f"printer_{target}")
                if isinstance(status, dict):
                    status["enabled"] = args.get("active") is True
                return {"op": "service_response", "service": service, "ok": True}
            printer_name = str(args.get("printer_name", "center"))
            decision = authorize_tool(
                "control_printer",
                {"printer_name": printer_name, "action": "beep", "param": 0},
                confirmed=True,
                client_id=client_id,
            )
            if not decision.allowed:
                return {"op": "service_response", "service": service, "ok": False, "message": decision.message}
            ok = ros_adapter.set_printer_active(printer_name, args.get("active") is True)
            return {
                "op": "service_response",
                "service": service,
                "ok": ok,
                "message": "" if ok else "喷码机未连接或服务调用失败",
            }

    if op == "call_service" and service == "/printer/set_enabled":
        args = payload.get("args")
        if isinstance(args, dict):
            printer_name = str(args.get("printer_name", "center"))
            if f"printer_{printer_name}" not in robot_state.printer_status:
                return {"op": "service_response", "service": service, "ok": False, "message": "喷码机未配置"}
            if not ros_adapter.owns_control(client_id):
                return {"op": "service_response", "service": service, "ok": False, "message": "control lease required"}
            enabled = args.get("enabled") is True
            if robot_state.bridge_mode == "virtual_ros2":
                robot_state.printer_status[f"printer_{printer_name}"]["auto_connect"] = enabled
                return {"op": "service_response", "service": service, "ok": True}
            ok = ros_adapter.set_printer_enabled(printer_name, enabled)
            return {
                "op": "service_response",
                "service": service,
                "ok": ok,
                "message": "" if ok else "喷码机未连接或服务调用失败",
            }

    if op == "call_service" and service == "/printer/send_command":
        args = payload.get("args")
        if isinstance(args, dict):
            printer_name = str(args.get("printer_name", "center"))
            command = str(args.get("command", "")).strip()
            json_data = str(args.get("json_data", ""))
            if f"printer_{printer_name}" not in robot_state.printer_status:
                return {"op": "service_response", "service": service, "ok": False, "message": "喷码机未配置"}
            if len(json_data.encode("utf-8")) > 8192:
                return {"op": "service_response", "service": service, "ok": False, "message": "JSON 命令过大"}
            if not ros_adapter.owns_control(client_id):
                return {"op": "service_response", "service": service, "ok": False, "message": "control lease required"}
            try:
                json.loads(json_data)
            except json.JSONDecodeError:
                return {"op": "service_response", "service": service, "ok": False, "message": "JSON 格式无效"}
            if not re.fullmatch(r"0x[0-9A-Fa-f]{2}", command):
                return {
                    "op": "service_response",
                    "service": service,
                    "ok": False,
                    "message": "command 必须是两位十六进制指令码，例如 0x34",
                }
            if robot_state.bridge_mode == "virtual_ros2":
                robot_state.add_log(
                    f"virtual printer raw command {printer_name} {command}"
                )
                return {"op": "service_response", "service": service, "ok": True}
            ok = ros_adapter.send_printer_command(printer_name, command, json_data)
            return {"op": "service_response", "service": service, "ok": ok}

    if op == "call_service" and service == "/ln_driver/command_srv":
        args = payload.get("args")
        if isinstance(args, dict):
            if robot_state.bridge_mode == "virtual_ros2":
                robot_state.ln150_status = "tracking"
                robot_state.add_log(f"virtual LN150 command {args.get('command_type', 1)}")
                return {"op": "service_response", "service": service, "ok": True}
            tool_args, error = validate_tool_arguments(
                "control_ln150", {"command_type": args.get("command_type", 1)}
            )
            if tool_args is None:
                return {"op": "service_response", "service": service, "ok": False, "message": error}
            decision = authorize_tool("control_ln150", tool_args, confirmed=True, client_id=client_id)
            if not decision.allowed:
                return {"op": "service_response", "service": service, "ok": False, "message": decision.message}
            ok = ros_adapter.call_ln150(int(tool_args["command_type"]))
            return {"op": "service_response", "service": service, "ok": ok}

    if op == "call_service" and service in {
        "/localization/prepare_calibration",
        "/localization/calibrate_pose",
    }:
        if not ros_adapter.owns_control(client_id):
            return {"op": "service_response", "service": service, "ok": False, "message": "需要小车控制权"}
        if not robot_state.localization_calibration_available:
            return {"op": "service_response", "service": service, "ok": False, "message": "当前定位模式没有校准或原点重置服务"}
        ok = (
            ros_adapter.prepare_localization_calibration()
            if service == "/localization/prepare_calibration"
            else ros_adapter.calibrate_localization()
        )
        return {"op": "service_response", "service": service, "ok": ok}

    robot_state.add_log(f"unsupported payload {payload}")
    return {"op": "error", "ok": False, "message": "unsupported payload"}



def _nested_number(data: dict[str, object], group: str, key: str) -> float:
    value = data.get(group)
    if isinstance(value, dict):
        raw = value.get(key, 0)
        if isinstance(raw, int | float):
            return float(raw)
    return 0.0



def _printer_unready_message(printer_name: str) -> str:
    status = robot_state.printer_status.get(f"printer_{printer_name}")
    if not isinstance(status, dict):
        return "喷码机未配置或状态尚未上报"
    if status.get("connected") is not True:
        return "喷码机未连接"
    if status.get("enabled") is not True:
        return "喷码机未启用"
    return "喷码服务调用失败，请检查喷码机节点日志"

