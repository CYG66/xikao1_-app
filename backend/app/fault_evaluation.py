"""Read-only live vehicle fault evaluation.

This module never sends ROS2, CAN, motion, printer, or mission commands.  It
only evaluates the latest live snapshot, so it can be used on the real rover
without changing its state.
"""

from __future__ import annotations

from typing import Any


def evaluate_live_vehicle(snapshot: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(code: str, label: str, ok: bool, detail: str, severity: str = "error") -> None:
        checks.append({
            "code": code,
            "label": label,
            "ok": bool(ok),
            "severity": severity if not ok else "ok",
            "detail": detail,
        })

    check("backend_online", "后端在线", snapshot.get("online") is True,
          "后端已在线" if snapshot.get("online") is True else "后端未在线")
    check("ros_available", "ROS2 可用", snapshot.get("ros_available") is True,
          "ROS2 接口可用" if snapshot.get("ros_available") is True else "ROS2 不可用")
    check("can_connected", "底盘 CAN", snapshot.get("drive_device_connected") is True,
          "CAN 设备已连接" if snapshot.get("drive_device_connected") is True else "CAN 设备未连接")
    check("motor_driver", "底盘驱动", snapshot.get("motor_driver_ready") is True,
          "电机驱动已就绪" if snapshot.get("motor_driver_ready") is True else "电机驱动未就绪")
    check("emergency_stop", "急停状态", snapshot.get("emergency_stopped") is False,
          "急停已解除" if snapshot.get("emergency_stopped") is False else "急停仍处于激活状态",
          "warning")
    check("localization", "定位", snapshot.get("localization_valid") is True,
          "定位有效" if snapshot.get("localization_valid") is True else "定位无效")
    energy_source = snapshot.get("energy_source")
    check("energy_telemetry", "能源遥测", energy_source not in {None, "", "unavailable"},
          "已收到能源遥测" if energy_source not in {None, "", "unavailable"}
          else "未收到电量、电压或电流遥测", "warning")
    printer = snapshot.get("printer_status")
    printer = printer if isinstance(printer, dict) else {}
    center = printer.get("printer_center")
    center = center if isinstance(center, dict) else {}
    check("printer_connected", "喷码机", center.get("connected") is True,
          "喷码机已连接" if center.get("connected") is True else "喷码机未连接",
          "warning")
    check("mission_nodes", "任务节点", snapshot.get("mission_nodes_ready") is True,
          "任务节点已就绪" if snapshot.get("mission_nodes_ready") is True else "任务节点未全部就绪")

    failures = [item for item in checks if not item["ok"]]
    return {
        "ok": not failures,
        "source": "live_robot_state",
        "read_only": True,
        "checked_at": snapshot.get("telemetry_age_ms"),
        "checks": checks,
        "failure_count": len(failures),
        "error_count": sum(item["severity"] == "error" for item in failures),
        "warning_count": sum(item["severity"] == "warning" for item in failures),
        "issue_codes": [item["code"] for item in failures],
    }
