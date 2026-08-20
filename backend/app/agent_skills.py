from __future__ import annotations

import math
import re
from typing import Any

from .config import WHEEL_BASE_M
from .drawing_store import preview_paths
from .mission_analysis import segment_length_m
from .state import robot_state


def _default_printer() -> str | None:
    """Select a real printer reported by the ROS2 printer status topic."""
    available: list[str] = []
    for key, value in robot_state.printer_status.items():
        if not key.startswith("printer_") or not isinstance(value, dict):
            continue
        if value.get("connected") is True and value.get("is_online", True) is not False:
            name = key.removeprefix("printer_")
            if name in {"left", "center", "right"}:
                available.append(name)
    if len(available) == 1:
        return available[0]
    return None


def parameterize_design(prompt: str) -> dict[str, Any]:
    normalized = prompt.lower().replace("×", "x").replace("*", "x")
    shape = next(
        (
            value
            for keywords, value in (
                (("矩形", "长方形", "rectangle"), "rectangle"),
                (("圆形", "圆", "circle"), "circle"),
                (("圆弧", "arc"), "arc"),
                (("折线", "polyline"), "polyline"),
                (("椭圆", "ellipse"), "ellipse"),
            )
            if any(keyword in normalized for keyword in keywords)
        ),
        None,
    )
    numbers = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", normalized)]
    size_match = re.search(r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)", normalized)
    diameter_match = re.search(r"直径\s*(\d+(?:\.\d+)?)", normalized)
    radius_match = re.search(r"半径\s*(\d+(?:\.\d+)?)", normalized)
    requested_printer = next(
        (value for keyword, value in (("左", "left"), ("中", "center"), ("右", "right")) if f"{keyword}喷" in normalized),
        None,
    )
    printer = requested_printer or _default_printer()
    dimensions: dict[str, float] = {}
    if size_match:
        dimensions = {"width_m": float(size_match.group(1)), "height_m": float(size_match.group(2))}
    elif diameter_match:
        dimensions = {"diameter_m": float(diameter_match.group(1))}
    elif radius_match:
        dimensions = {"radius_m": float(radius_match.group(1))}
    elif shape == "circle" and numbers:
        dimensions = {"radius_m": numbers[0]}

    missing = []
    if shape is None:
        missing.append("shape")
    if not dimensions:
        missing.append("dimensions")
    if printer is None:
        missing.append("printer")
    return {
        "ok": not missing,
        "shape": shape,
        "dimensions": dimensions,
        "printer": printer,
        "origin": "current_robot_pose",
        "units": "m",
        "missing": missing,
    }


def clarify_requirements(prompt: str) -> dict[str, Any]:
    requirements = parameterize_design(prompt)
    questions = {
        "shape": "需要绘制什么图形或图案？",
        "dimensions": "请提供关键尺寸和单位。",
        "printer": "当前没有唯一可用喷码机，请选择左、中或右喷码机。",
    }
    return {
        **requirements,
        "questions": [questions[item] for item in requirements["missing"] if item in questions],
        "ready_for_design": not requirements["missing"],
    }


def check_drawing_feasibility(geometries: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    ids = [item.get("id") for item in geometries]
    if len(ids) != len(set(ids)):
        errors.append("几何 ID 重复")
    valid_paths = preview_paths({"lines": geometries})
    if not valid_paths:
        errors.append("没有可规划的有效几何")

    total_length = 0.0
    for geometry in geometries:
        length = segment_length_m(geometry)
        if length is None or not math.isfinite(length) or length <= 0:
            errors.append(f"几何 {geometry.get('id', '?')} 长度无效")
            continue
        total_length += length
        if length < 0.001:
            warnings.append(f"几何 {geometry.get('id', '?')} 短于 1 mm")
        if geometry.get("type") in {"circle", "arc"}:
            radius_m = float(geometry.get("radius", 0.0)) / 1000.0
            if 0 < radius_m < WHEEL_BASE_M / 2:
                warnings.append(
                    f"几何 {geometry.get('id', '?')} 半径小于半轮距，规划后需重点检查转向"
                )
    return {
        "ok": not errors,
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
        "geometry_count": len(geometries),
        "preview_path_count": len(valid_paths),
        "printing_length_m": round(total_length, 4),
    }


def score_design_variant(geometries: list[dict[str, Any]]) -> dict[str, Any]:
    feasibility = check_drawing_feasibility(geometries)
    score = 100
    score -= min(60, len(feasibility["errors"]) * 30)
    score -= min(30, len(feasibility["warnings"]) * 5)
    if feasibility["preview_path_count"] == 0:
        score = 0
    score = max(0, score)
    grade = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "E"
    return {
        "score_type": "design_only",
        "score": score,
        "grade": grade,
        "feasibility": feasibility,
        "requires_ros_planning_score": True,
    }


def layer_drawing_paths(
    geometries: list[dict[str, Any]], printer: str = "center"
) -> dict[str, Any]:
    layered = []
    for geometry in geometries:
        item = dict(geometry)
        item["layer_id"] = 1
        layered.append(item)
    return {
        "layers": [
            {
                "layer_id": 1,
                "name": "printing",
                "route_type": "printing",
                "printer": printer,
            }
        ],
        "lines": layered,
        "travel_policy": "generated_by_xline_cyg_planner",
    }


def recommend_recovery(status: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    actions: list[str] = []
    moving = status.get("mission_running") is True or status.get("agent_motion_active") is True
    if status.get("localization_valid") is not True:
        reasons.append("定位无效或过期")
        actions.append("停车后恢复定位，重新规划当前图纸")
    if status.get("control_ready") is not True:
        reasons.append("底盘控制未就绪")
        actions.append("检查 CAN 接口、电机驱动节点和控制权")
    if status.get("printer_ready") is not True and status.get("mission_required_printers"):
        reasons.append("任务所需喷码机未就绪")
        actions.append("保持停车，恢复喷码机后从未完成分段继续")
    obstacle_values = [
        value for value in (status.get("obstacle_distances") or {}).values() if isinstance(value, (int, float))
    ]
    if obstacle_values and min(obstacle_values) < 0.35:
        reasons.append("障碍物距离小于 0.35 m")
        actions.append("清理作业区后重新规划，不自动绕行喷墨路径")
    mission_error = str(status.get("mission_error") or "").strip()
    if mission_error:
        reasons.append(mission_error)
        actions.append("保留任务账本和已完成分段，修复原因后重新预览")
    return {
        "ok": not reasons,
        "stop_required": moving and bool(reasons),
        "auto_resume_allowed": False,
        "reasons": list(dict.fromkeys(reasons)),
        "recommended_actions": list(dict.fromkeys(actions)) or ["当前未发现需要恢复的异常"],
    }
