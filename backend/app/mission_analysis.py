from __future__ import annotations

import math

from .config import MAX_TASK_LINEAR_VELOCITY
from typing import Any


SUPPORTED_TYPES = {"line", "polyline", "spline", "circle", "arc", "ellipse", "text"}
MIN_SEGMENT_LENGTH_M = 0.0001
SHORT_PRINTING_LENGTH_M = 0.0005
EFFECTIVE_SPEED_MPS = MAX_TASK_LINEAR_VELOCITY


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def point_xy(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    x = _number(value.get("x"))
    y = _number(value.get("y"))
    return (x, y) if x is not None and y is not None else None


def segment_endpoint_m(segment: dict[str, Any]) -> tuple[float, float] | None:
    geometry_type = str(segment.get("type", "")).lower()
    point = point_xy(segment.get("end"))
    if point is None and geometry_type in {"polyline", "spline"}:
        values = segment.get("vertices", segment.get("control_points", []))
        if isinstance(values, list) and values:
            point = point_xy(values[-1])
    if point is None:
        return None
    return point[0] / 1000.0, point[1] / 1000.0


def _polyline_length(values: Any) -> float | None:
    if not isinstance(values, list) or len(values) < 2:
        return None
    points = [point_xy(value) for value in values]
    if any(point is None for point in points):
        return None
    return sum(math.dist(points[index - 1], points[index]) for index in range(1, len(points)))


def segment_length_m(segment: dict[str, Any]) -> float | None:
    geometry_type = str(segment.get("type", "")).lower()
    length_mm: float | None = None
    if geometry_type in {"line", "text"}:
        start = point_xy(segment.get("start"))
        end = point_xy(segment.get("end"))
        if start is not None and end is not None:
            length_mm = math.dist(start, end)
    elif geometry_type in {"polyline", "spline"}:
        length_mm = _polyline_length(
            segment.get("vertices", segment.get("control_points", []))
        )
    elif geometry_type == "circle":
        radius = _number(segment.get("radius"))
        if radius is not None and radius > 0:
            length_mm = 2 * math.pi * radius
    elif geometry_type == "arc":
        radius = _number(segment.get("radius"))
        start = _number(segment.get("start_angle"))
        end = _number(segment.get("end_angle"))
        if radius is not None and radius > 0 and start is not None and end is not None:
            sweep = abs(end - start)
            if sweep > 2 * math.pi + 1e-6:
                sweep = math.radians(sweep)
            length_mm = radius * sweep
    elif geometry_type == "ellipse":
        major = _number(segment.get("major_axis", segment.get("radius")))
        ratio = _number(segment.get("ratio"))
        if major is not None and major > 0 and ratio is not None and ratio > 0:
            minor = major * ratio
            h = ((major - minor) ** 2) / ((major + minor) ** 2)
            length_mm = math.pi * (major + minor) * (
                1 + 3 * h / (10 + math.sqrt(4 - 3 * h))
            )
    return length_mm / 1000.0 if length_mm is not None else None


def analyze_mission(
    segments: list[dict[str, Any]],
    classify: Any,
    duplicate_count: int = 0,
    localization_source: str = "unavailable",
) -> tuple[dict[str, Any], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    printing_count = 0
    travel_count = 0
    printing_length = 0.0
    travel_length = 0.0
    printers: set[str] = set()

    if not segments:
        errors.append("规划结果中没有可执行路径")
    for index, segment in enumerate(segments):
        label = f"第 {index + 1} 段"
        segment_id = segment.get("id")
        if isinstance(segment_id, bool) or not isinstance(segment_id, (int, float, str)):
            errors.append(f"{label}缺少有效 id")
        geometry_type = str(segment.get("type", "")).lower()
        if geometry_type not in SUPPORTED_TYPES:
            errors.append(f"{label}使用不支持的几何类型: {geometry_type or '空'}")
            continue
        kind = classify(segment)
        intended_printing = (
            segment.get("work") is True
            and not (
                isinstance(segment.get("layer_id"), int)
                and segment.get("layer_id") >= 1_000_000
            )
        )
        if intended_printing:
            ink = segment.get("ink")
            if not isinstance(ink, dict) or ink.get("enabled") is not True:
                errors.append(f"{label}标记为工作路径，但喷墨配置缺失或未启用")
        length = segment_length_m(segment)
        if length is None:
            errors.append(f"{label}几何坐标无效或点数不足")
            continue
        if length < MIN_SEGMENT_LENGTH_M:
            errors.append(f"{label}长度接近零")
        if kind == "printing":
            printing_count += 1
            printing_length += length
            ink = segment.get("ink")
            if not isinstance(ink, dict) or ink.get("enabled") is not True:
                errors.append(f"{label}喷墨配置缺失或未启用")
            else:
                printer = str(ink.get("printer", "")).strip().lower()
                if not printer:
                    errors.append(f"{label}未指定喷头")
                else:
                    printers.add(printer)
            if 0 < length < SHORT_PRINTING_LENGTH_M:
                warnings.append(f"{label}喷墨长度小于 0.5 mm")
        else:
            travel_count += 1
            travel_length += length

    if duplicate_count:
        warnings.append(f"已过滤 {duplicate_count} 条重复喷墨路径")
    if localization_source == "odom_imu_relative":
        warnings.append("当前为里程计/IMU 相对定位，长距离任务可能累积漂移")

    total_length = printing_length + travel_length
    validation = {"ok": not errors, "errors": errors, "warnings": warnings}
    summary = {
        "segment_count": len(segments),
        "printing_segment_count": printing_count,
        "travel_segment_count": travel_count,
        "printing_length_m": round(printing_length, 3),
        "travel_length_m": round(travel_length, 3),
        "total_length_m": round(total_length, 3),
        "estimated_duration_seconds": int(math.ceil(total_length / EFFECTIVE_SPEED_MPS)),
        "estimated_duration_is_approximate": True,
        "required_printers": sorted(printers),
        "duplicate_ink_paths_filtered": duplicate_count,
        "localization_source": localization_source,
        "validation": validation,
    }
    return summary, validation
