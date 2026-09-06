from __future__ import annotations

import math
import re
from typing import Any

from .config import WHEEL_BASE_M
from .drawing_store import preview_paths
from .mission_analysis import segment_length_m
from .state import robot_state


# Drawing editor templates are also local Agent skills.  Keeping the aliases
# and dimensions here makes template recognition independent of an LLM call.
DRAWING_TEMPLATE_SKILLS: dict[str, dict[str, Any]] = {
    "room": {
        "label": "矩形房间",
        "aliases": ("矩形房间", "房间", "矩形室内", "room"),
        "category": "建筑",
        "width_m": 6.0,
        "height_m": 4.0,
    },
    "two_rooms": {
        "label": "两室布局",
        "aliases": ("两室布局", "两室", "双房间", "two rooms"),
        "category": "建筑",
        "width_m": 8.0,
        "height_m": 6.0,
    },
    "corridor": {
        "label": "长走廊",
        "aliases": ("长走廊", "走廊", "通道", "corridor"),
        "category": "建筑",
        "width_m": 12.0,
        "height_m": 2.0,
    },
    "parking": {
        "label": "标准车位",
        "aliases": ("标准车位", "单个车位", "停车位", "parking spot"),
        "category": "场地",
        "width_m": 2.5,
        "height_m": 5.0,
    },
    "parking_lot": {
        "label": "停车场",
        "aliases": ("停车场", "停车区", "停车位阵列", "parking lot"),
        "category": "场地",
        "width_m": 12.0,
        "height_m": 6.0,
    },
    "basketball": {
        "label": "篮球场",
        "aliases": ("篮球场", "篮球场地", "basketball court"),
        "category": "场地",
        "width_m": 28.0,
        "height_m": 15.0,
    },
    "badminton": {
        "label": "羽毛球场",
        "aliases": ("羽毛球场", "羽毛球场地", "badminton court"),
        "category": "场地",
        "width_m": 13.4,
        "height_m": 6.1,
    },
    "warehouse": {
        "label": "仓库网格",
        "aliases": ("仓库网格", "仓库", "仓储网格", "warehouse"),
        "category": "施工",
        "width_m": 20.0,
        "height_m": 12.0,
    },
    "grid": {
        "label": "施工轴网",
        "aliases": ("施工轴网", "轴网", "网格", "grid"),
        "category": "施工",
        "width_m": 4.0,
        "height_m": 4.0,
    },
    "foundation": {
        "label": "圆形基础",
        "aliases": ("圆形基础", "圆基础", "基础圆", "circular foundation"),
        "category": "施工",
        "radius_m": 3.0,
    },
}


def recognize_drawing_template(prompt: str) -> dict[str, Any] | None:
    """Recognize one editor template without spending a model request."""
    normalized = prompt.lower().replace("×", "x")
    # Longer aliases first avoids matching “停车位” inside “停车位阵列”.
    candidates = sorted(
        DRAWING_TEMPLATE_SKILLS.items(),
        key=lambda item: max(map(len, item[1]["aliases"])),
        reverse=True,
    )
    for key, skill in candidates:
        if any(alias.lower() in normalized for alias in skill["aliases"]):
            result = {"template": key, **skill}
            size_match = re.search(
                r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)", normalized
            )
            if size_match and "width_m" in result:
                result["width_m"] = float(size_match.group(1))
                result["height_m"] = float(size_match.group(2))
            radius_match = re.search(r"半径\s*(\d+(?:\.\d+)?)", normalized)
            if radius_match and "radius_m" in result:
                result["radius_m"] = float(radius_match.group(1))
            return result
    return None


def _rectangle_points(width: float, height: float) -> list[list[float]]:
    width_mm, height_mm = width * 1000, height * 1000
    return [
        [-width_mm / 2, -height_mm / 2],
        [width_mm / 2, -height_mm / 2],
        [width_mm / 2, height_mm / 2],
        [-width_mm / 2, height_mm / 2],
        [-width_mm / 2, -height_mm / 2],
    ]


def drawing_template_geometries(match: dict[str, Any]) -> list[dict[str, Any]]:
    """Build CAD JSON geometry for an identified template."""
    template = str(match["template"])
    width = float(match.get("width_m", 1.0))
    height = float(match.get("height_m", 1.0))
    geometries: list[dict[str, Any]] = [
        {
            "id": 1,
            "type": "polyline",
            "layer_id": 1,
            "vertices": [
                {"x": point[0], "y": point[1], "z": 0.0}
                for point in _rectangle_points(width, height)
            ],
            "closed": True,
        }
    ]
    def line(identifier: int, start: tuple[float, float], end: tuple[float, float]) -> dict[str, Any]:
        return {
            "id": identifier,
            "type": "line",
            "layer_id": 1,
            "start": {"x": start[0] * 1000, "y": start[1] * 1000, "z": 0.0},
            "end": {"x": end[0] * 1000, "y": end[1] * 1000, "z": 0.0},
        }

    if template == "two_rooms":
        geometries.append(line(2, (0, -height / 2), (0, height / 2)))
    elif template == "basketball":
        geometries.append(line(2, (0, -height / 2), (0, height / 2)))
        geometries.append({
            "id": 3,
            "type": "circle",
            "layer_id": 1,
            "center": {"x": 0.0, "y": 0.0, "z": 0.0},
            "radius": 1800.0,
        })
    elif template == "badminton":
        for identifier, x in enumerate((-2.1, 0.0, 2.1), start=2):
            geometries.append(line(identifier, (x, -height / 2), (x, height / 2)))
    elif template == "parking_lot":
        for identifier, x in enumerate(range(-5, 6, 2), start=2):
            geometries.append(line(identifier, (float(x), -height / 2), (float(x), height / 2)))
    elif template == "warehouse":
        for identifier, x in enumerate(range(-8, 9, 4), start=2):
            geometries.append(line(identifier, (float(x), -height / 2), (float(x), height / 2)))
    elif template == "grid":
        identifier = 2
        for value in range(-2, 3):
            geometries.append(line(identifier, (float(value), -2), (float(value), 2)))
            identifier += 1
            geometries.append(line(identifier, (-2, float(value)), (2, float(value))))
            identifier += 1
    elif template == "foundation":
        geometries = [{
            "id": 1,
            "type": "circle",
            "layer_id": 1,
            "center": {"x": 0.0, "y": 0.0, "z": 0.0},
            "radius": float(match.get("radius_m", 3.0)) * 1000,
        }]
    return geometries


def drawing_template_motion_steps(match: dict[str, Any]) -> list[dict[str, float]]:
    """Create an open-loop base-mode preview from a template perimeter."""
    geometries = drawing_template_geometries(match)
    points: list[tuple[float, float]] = []
    for geometry in geometries:
        if geometry["type"] == "polyline":
            points.extend(
                (float(point["x"]) / 1000, float(point["y"]) / 1000)
                for point in geometry["vertices"]
            )
        elif geometry["type"] == "line":
            points.extend(
                (
                    (float(geometry["start"]["x"]) / 1000, float(geometry["start"]["y"]) / 1000),
                    (float(geometry["end"]["x"]) / 1000, float(geometry["end"]["y"]) / 1000),
                )
            )
        elif geometry["type"] == "circle":
            radius = float(geometry["radius"]) / 1000
            points.extend(
                (
                    radius * math.cos(2 * math.pi * index / 24),
                    radius * math.sin(2 * math.pi * index / 24),
                )
                for index in range(25)
            )
    if len(points) < 2:
        return []
    origin_x, origin_y = points[0]
    translated = [(x - origin_x, y - origin_y) for x, y in points]
    steps: list[dict[str, float]] = []
    heading = 0.0
    for start, end in zip(translated, translated[1:]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        distance = math.hypot(dx, dy)
        if distance < 0.01:
            continue
        target = math.atan2(dy, dx)
        turn = (target - heading + math.pi) % (2 * math.pi) - math.pi
        if abs(turn) > 0.03:
            turn_duration = abs(turn) / 0.4
            steps.append({
                "linear": 0.0,
                "angular": 0.4 if turn > 0 else -0.4,
                "duration_seconds": round(turn_duration, 3),
            })
        drive_duration = distance / 0.1
        remaining = drive_duration
        while remaining > 0:
            duration = min(30.0, remaining)
            steps.append({"linear": 0.1, "angular": 0.0, "duration_seconds": round(duration, 3)})
            remaining -= duration
        heading = target
    return steps


def _default_printer() -> str | None:
    """Return the only physical printer exposed by xline_ws3 when usable."""
    status = robot_state.printer_status.get("printer_center")
    if (
        isinstance(status, dict)
        and status.get("connected") is True
        and status.get("enabled") is True
    ):
        return "center"
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
    unsupported_printer = any(
        marker in normalized for marker in ("左喷", "右喷", "left printer", "right printer")
    )
    requested_printer = "center" if any(
        marker in normalized for marker in ("中喷", "中心喷", "center printer")
    ) else None
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
    if unsupported_printer:
        missing.append("unsupported_printer:xline_ws3_only_has_center")
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
        "travel_policy": "generated_by_xline_ws3_planner",
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
