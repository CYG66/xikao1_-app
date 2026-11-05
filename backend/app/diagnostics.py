from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


ISSUE_KEYWORDS = {
    "backend_offline": ("后端", "离线", "online"),
    "ros_unavailable": ("ros2", "ros", "节点"),
    "control_not_ready": ("控制", "未就绪", "control_ready"),
    "can_disconnected": ("can", "总线", "底盘连接"),
    "motor_not_ready": ("电机", "驱动", "motor"),
    "localization_invalid": ("定位", "位姿", "localization"),
    "telemetry_stale": ("遥测", "超时", "telemetry"),
    "energy_unavailable": ("电量", "能源", "bms", "电压"),
    "printer_not_ready": ("喷码", "喷墨", "喷头"),
}


def build_link_diagnosis(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Describe independent runtime links without issuing any command."""
    checked_at = datetime.now(timezone.utc)

    def last_success(age_ms: Any) -> str | None:
        if isinstance(age_ms, (int, float)) and age_ms >= 0:
            return (checked_at - timedelta(milliseconds=age_ms)).isoformat()
        return None

    def link(
        code: str,
        label: str,
        source: str,
        ok: bool | None,
        detail: str,
        *,
        age_ms: Any = None,
        available_features: list[str] | None = None,
        retry_allowed: bool = True,
        manual_required: bool = False,
    ) -> dict[str, Any]:
        state = "ok" if ok is True else "failed" if ok is False else "unknown"
        return {
            "code": code,
            "label": label,
            "source": source,
            "status": state,
            "ok": ok is True,
            "detail": detail,
            "last_success_at": last_success(age_ms),
            "last_checked_at": checked_at.isoformat(),
            "evidence_age_ms": age_ms,
            "retry_allowed": retry_allowed,
            "manual_required": manual_required,
            "available_features": available_features or [],
        }

    links = [
        link(
            "app_backend",
            "App → 小车 HTTP 后端",
            "online",
            snapshot.get("online") is True,
            "HTTP 后端在线" if snapshot.get("online") is True else "无法访问小车 HTTP 后端",
            available_features=["AI 对话", "设备诊断", "图纸编辑"]
            if snapshot.get("online") is True
            else [],
            manual_required=snapshot.get("online") is not True,
        ),
        link(
            "backend_ros2",
            "HTTP 后端 → ROS2 运行层",
            "ros_available",
            snapshot.get("ros_available") is True,
            "ROS2 运行层在线" if snapshot.get("ros_available") is True else "ROS2 运行层不可用",
            available_features=["实时状态读取"]
            if snapshot.get("ros_available") is True
            else [],
            manual_required=snapshot.get("ros_available") is not True,
        ),
        link(
            "ros2_can",
            "ROS2 → CAN 底盘总线",
            "drive_device_connected",
            snapshot.get("drive_device_connected") is True,
            "CAN 设备已连接" if snapshot.get("drive_device_connected") is True else "CAN 设备未连接",
            available_features=["底盘控制"]
            if snapshot.get("drive_device_connected") is True
            else [],
            retry_allowed=False,
            manual_required=snapshot.get("drive_device_connected") is not True,
        ),
        link(
            "can_motor",
            "CAN → 电机驱动",
            "motor_driver_ready",
            snapshot.get("motor_driver_ready") is True,
            "电机驱动已就绪" if snapshot.get("motor_driver_ready") is True else "电机驱动未就绪",
            available_features=["轮速反馈"]
            if snapshot.get("motor_driver_ready") is True
            else [],
            retry_allowed=False,
            manual_required=snapshot.get("motor_driver_ready") is not True,
        ),
        link(
            "ros2_localization",
            "ROS2 → 定位数据",
            "localization_valid",
            snapshot.get("localization_valid") is True,
            "定位数据有效" if snapshot.get("localization_valid") is True else "定位数据无效或未上报",
            age_ms=snapshot.get("telemetry_age_ms"),
            available_features=["相对定位", "任务执行"]
            if snapshot.get("localization_valid") is True
            else [],
            retry_allowed=True,
            manual_required=snapshot.get("localization_valid") is not True,
        ),
        link(
            "ros2_energy",
            "ROS2 → 能源遥测",
            "energy_source",
            snapshot.get("energy_source") not in {None, "", "unavailable"},
            "能源数据已上报"
            if snapshot.get("energy_source") not in {None, "", "unavailable"}
            else "能源数据未上报",
            age_ms=snapshot.get("energy_age_ms"),
            available_features=["电量、电压、电流、温度监控"]
            if snapshot.get("energy_source") not in {None, "", "unavailable"}
            else [],
            manual_required=snapshot.get("energy_source") in {None, "", "unavailable"},
        ),
        link(
            "ros2_printer",
            "ROS2 → 喷码机",
            "printer_ready",
            snapshot.get("printer_ready") is True,
            "喷码机已就绪" if snapshot.get("printer_ready") is True else "喷码机未就绪",
            age_ms=snapshot.get("printer_status_age_ms"),
            available_features=["喷码状态监控"]
            if snapshot.get("printer_ready") is True
            else [],
            retry_allowed=True,
            manual_required=snapshot.get("printer_ready") is not True,
        ),
    ]
    failed = [item for item in links if item["status"] == "failed"]
    primary = next(
        (item for item in links[:5] if item["status"] == "failed"),
        None,
    )
    usable = [
        "AI 对话",
        "图纸编辑与预览",
        "设备诊断",
    ] if snapshot.get("online") is True else []
    if snapshot.get("drive_device_connected") is True and snapshot.get("motor_driver_ready") is True:
        usable.append("手动底盘控制")
    if snapshot.get("localization_valid") is True and snapshot.get("mission_nodes_ready") is True:
        usable.append("任务规划与执行")
    return {
        "contract_version": "1.0",
        "checked_at": checked_at.isoformat(),
        "ok": not failed,
        "links": links,
        "failure_count": len(failed),
        "breakpoint": primary["label"] if primary else None,
        "breakpoint_code": primary["code"] if primary else None,
        "usable_features": usable,
        "retry_allowed": all(item["retry_allowed"] for item in failed),
        "manual_required": any(item["manual_required"] for item in failed),
        "requires_human_action": any(item["manual_required"] for item in failed),
    }


def build_local_diagnosis(snapshot: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []

    def add(code: str, field: str, actual: Any, message: str, action: str) -> None:
        issues.append({
            "code": code,
            "field": field,
            "actual": actual,
            "message": message,
            "recommended_check": action,
        })

    if snapshot.get("online") is not True:
        add("backend_offline", "online", snapshot.get("online"), "小车后端未在线", "检查后端服务与网络连接")
    if snapshot.get("ros_available") is not True:
        add("ros_unavailable", "ros_available", snapshot.get("ros_available"), "ROS2 运行层不可用", "检查运行层服务和 ROS2 节点")
    if snapshot.get("control_ready") is not True:
        add("control_not_ready", "control_ready", snapshot.get("control_ready"), "底盘控制尚未就绪", "检查急停、控制权和底盘联锁")
    if snapshot.get("drive_device_connected") is not True:
        add("can_disconnected", "drive_device_connected", snapshot.get("drive_device_connected"), "CAN 设备未连接", "检查 CAN 接线、供电和 can0 状态")
    if snapshot.get("motor_driver_ready") is not True:
        add("motor_not_ready", "motor_driver_ready", snapshot.get("motor_driver_ready"), "电机驱动未就绪", "检查电机驱动节点和故障反馈")
    if snapshot.get("localization_valid") is not True:
        add("localization_invalid", "localization_valid", snapshot.get("localization_valid"), "定位数据无效", "检查当前定位源、位姿话题和数据年龄")
    telemetry_age = snapshot.get("telemetry_age_ms")
    if telemetry_age is None or (isinstance(telemetry_age, (int, float)) and telemetry_age >= 3000):
        add("telemetry_stale", "telemetry_age_ms", telemetry_age, "遥测数据缺失或超时", "检查遥测发布频率和网络延迟")
    if snapshot.get("energy_source") in {None, "", "unavailable"}:
        add("energy_unavailable", "energy_source", snapshot.get("energy_source"), "能源数据未上报", "检查 BMS 或电源采集 ROS2 话题")
    if snapshot.get("printer_ready") is not True:
        add("printer_not_ready", "printer_ready", snapshot.get("printer_ready"), "喷码机未就绪", "检查喷码机连接、在线状态和错误码")
    links = build_link_diagnosis(snapshot)
    return {
        "ok": not issues,
        "issues": issues,
        "issue_codes": [item["code"] for item in issues],
        "checked_fields": list(dict.fromkeys(item["field"] for item in issues)),
        "link_diagnosis": links,
    }


def compare_api_with_local(api_result: dict[str, Any], local: dict[str, Any]) -> dict[str, Any]:
    api_ok = api_result.get("ok") is True
    text = str(api_result.get("message") or "").lower()
    local_codes = set(local.get("issue_codes") or [])
    api_codes = {
        code for code, words in ISSUE_KEYWORDS.items()
        if any(word in text for word in words)
    }
    no_issue_claim = any(word in text for word in ("无异常", "没有异常", "状态正常", "未发现异常"))
    if not api_ok:
        verdict = "api_unavailable"
    elif not local_codes and (no_issue_claim or not api_codes):
        verdict = "consistent"
    elif local_codes and local_codes.issubset(api_codes):
        verdict = "consistent"
    elif local_codes & api_codes:
        verdict = "partial"
    else:
        verdict = "conflict"
    return {
        "verdict": verdict,
        "consistent": verdict == "consistent",
        "requires_manual_check": verdict != "consistent",
        "api_issue_codes": sorted(api_codes),
        "local_issue_codes": sorted(local_codes),
        "unverified_local_codes": sorted(local_codes - api_codes),
        "api_only_codes": sorted(api_codes - local_codes),
        "execution_allowed": False,
        "message": {
            "consistent": "API 分析与本地规则结论一致。",
            "partial": "API 仅覆盖部分本地异常，请人工核验未覆盖项目。",
            "conflict": "API 分析与本地规则不一致，请人工检查，不执行自动修复。",
            "api_unavailable": "API 分析未完成，仅保留本地核验结果，不执行自动修复。",
        }[verdict],
    }
