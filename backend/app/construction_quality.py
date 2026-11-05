from __future__ import annotations

import math
from typing import Any

from .config import NOZZLE_OFFSET_FORWARD_M, NOZZLE_OFFSET_LATERAL_M
from .mission_analysis import point_xy, segment_length_m


SHARP_TURN_DEGREES = 120.0
JUNCTION_WARNING_GAP_M = 0.02
CURVATURE_WARNING_PER_M = 4.0
CURVATURE_JUMP_WARNING_PER_M = 4.0


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _point_m(value: Any) -> tuple[float, float] | None:
    point = point_xy(value)
    if point is None:
        return None
    return point[0] / 1000.0, point[1] / 1000.0


def _angle_delta(left: float, right: float) -> float:
    return abs((right - left + math.pi) % (2 * math.pi) - math.pi)


def _profile(segment: dict[str, Any]) -> dict[str, Any] | None:
    kind = str(segment.get("type", "")).lower()
    points: list[tuple[float, float]] = []
    if kind in {"line", "text"}:
        start, end = _point_m(segment.get("start")), _point_m(segment.get("end"))
        if start is not None and end is not None:
            points = [start, end]
    elif kind in {"polyline", "spline"}:
        raw = segment.get("vertices", segment.get("control_points", []))
        if isinstance(raw, list):
            points = [point for value in raw if (point := _point_m(value)) is not None]
    if len(points) >= 2:
        edges = [
            (points[index - 1], points[index])
            for index in range(1, len(points))
            if math.dist(points[index - 1], points[index]) > 1e-9
        ]
        if not edges:
            return None
        headings = [
            math.atan2(end[1] - start[1], end[0] - start[0])
            for start, end in edges
        ]
        curvatures: list[float] = []
        internal_turns: list[float] = []
        for index in range(1, len(edges)):
            turn = _angle_delta(headings[index - 1], headings[index])
            average_length = (
                math.dist(*edges[index - 1]) + math.dist(*edges[index])
            ) / 2.0
            internal_turns.append(math.degrees(turn))
            if average_length > 1e-9:
                curvatures.append(turn / average_length)
        return {
            "start": edges[0][0],
            "end": edges[-1][1],
            "entry_heading": headings[0],
            "exit_heading": headings[-1],
            "entry_curvature": curvatures[0] if curvatures else 0.0,
            "exit_curvature": curvatures[-1] if curvatures else 0.0,
            "maximum_curvature": max(curvatures, default=0.0),
            "internal_turns_degrees": internal_turns,
        }

    center = _point_m(segment.get("center"))
    if center is None:
        return None
    start_degrees = _finite(segment.get("start_angle")) or 0.0
    end_degrees = _finite(segment.get("end_angle"))
    if kind == "circle":
        radius_mm = _finite(segment.get("radius"))
        if radius_mm is None or radius_mm <= 0:
            return None
        radius = radius_mm / 1000.0
        start = (center[0] + radius, center[1])
        return {
            "start": start,
            "end": start,
            "entry_heading": math.pi / 2,
            "exit_heading": math.pi / 2,
            "entry_curvature": 1.0 / radius,
            "exit_curvature": 1.0 / radius,
            "maximum_curvature": 1.0 / radius,
            "internal_turns_degrees": [],
        }
    if kind == "arc":
        radius_mm = _finite(segment.get("radius"))
        if radius_mm is None or radius_mm <= 0 or end_degrees is None:
            return None
        radius = radius_mm / 1000.0
        start_angle, end_angle = math.radians(start_degrees), math.radians(end_degrees)
        return {
            "start": (center[0] + radius * math.cos(start_angle), center[1] + radius * math.sin(start_angle)),
            "end": (center[0] + radius * math.cos(end_angle), center[1] + radius * math.sin(end_angle)),
            "entry_heading": start_angle + math.pi / 2,
            "exit_heading": end_angle + math.pi / 2,
            "entry_curvature": 1.0 / radius,
            "exit_curvature": 1.0 / radius,
            "maximum_curvature": 1.0 / radius,
            "internal_turns_degrees": [],
        }
    if kind == "ellipse":
        axis = point_xy(segment.get("major_axis"))
        ratio = _finite(segment.get("ratio"))
        if axis is None or ratio is None or ratio <= 0:
            return None
        major = math.hypot(axis[0], axis[1]) / 1000.0
        minor = major * ratio
        if major <= 0 or minor <= 0:
            return None
        rotation = math.atan2(axis[1], axis[0])
        start_angle = math.radians(start_degrees)
        end_angle = math.radians(end_degrees if end_degrees is not None else 360.0)

        def ellipse_point(angle: float) -> tuple[float, float]:
            local_x, local_y = major * math.cos(angle), minor * math.sin(angle)
            return (
                center[0] + local_x * math.cos(rotation) - local_y * math.sin(rotation),
                center[1] + local_x * math.sin(rotation) + local_y * math.cos(rotation),
            )

        def heading(angle: float) -> float:
            dx, dy = -major * math.sin(angle), minor * math.cos(angle)
            return math.atan2(
                dx * math.sin(rotation) + dy * math.cos(rotation),
                dx * math.cos(rotation) - dy * math.sin(rotation),
            )

        maximum = max(major / (minor * minor), minor / (major * major))
        return {
            "start": ellipse_point(start_angle),
            "end": ellipse_point(end_angle),
            "entry_heading": heading(start_angle),
            "exit_heading": heading(end_angle),
            "entry_curvature": maximum,
            "exit_curvature": maximum,
            "maximum_curvature": maximum,
            "internal_turns_degrees": [],
        }
    return None


def analyze_construction_quality(
    segments: list[dict[str, Any]],
    *,
    duplicate_count: int = 0,
) -> dict[str, Any]:
    """Return source-independent planning diagnostics for any executable drawing.

    Coordinates are read from the canonical millimetre mission schema. The
    result intentionally labels ink checks as predictive: actual ink quality
    requires a camera or metrology measurement and must not be inferred from
    commanded paths.
    """
    profiles: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    invalid_profile_count = 0
    for index, segment in enumerate(segments):
        profile = _profile(segment)
        if profile is None:
            invalid_profile_count += 1
            continue
        profiles.append((index, segment, profile))

    maximum_curvature = max(
        (profile["maximum_curvature"] for _, _, profile in profiles), default=0.0
    )
    curvature_jumps: list[float] = []
    heading_jumps: list[float] = []
    junction_gaps: list[float] = []
    junction_warnings: list[dict[str, Any]] = []
    for previous, current in zip(profiles, profiles[1:]):
        previous_index, _, previous_profile = previous
        current_index, _, current_profile = current
        heading_jump = math.degrees(_angle_delta(
            previous_profile["exit_heading"], current_profile["entry_heading"]
        ))
        curvature_jump = abs(
            current_profile["entry_curvature"] - previous_profile["exit_curvature"]
        )
        gap = math.dist(previous_profile["end"], current_profile["start"])
        heading_jumps.append(heading_jump)
        curvature_jumps.append(curvature_jump)
        junction_gaps.append(gap)
        if gap > JUNCTION_WARNING_GAP_M:
            junction_warnings.append({
                "from_segment": previous_index + 1,
                "to_segment": current_index + 1,
                "gap_m": round(gap, 4),
                "reason": "相邻施工段端点不连续，需要转场或接缝复核",
            })

    internal_turns = [
        turn
        for _, _, profile in profiles
        for turn in profile["internal_turns_degrees"]
    ]
    all_turns = heading_jumps + internal_turns
    sharp_turns = sum(turn > SHARP_TURN_DEGREES for turn in all_turns)
    short_printing_segments = sum(
        0 < (segment_length_m(segment) or 0.0) < 0.02
        for segment in segments
        if segment.get("work") is True
    )
    configured_offset = (
        NOZZLE_OFFSET_FORWARD_M is not None and NOZZLE_OFFSET_LATERAL_M is not None
    )
    offset_forward = NOZZLE_OFFSET_FORWARD_M or 0.0
    offset_lateral = NOZZLE_OFFSET_LATERAL_M or 0.0
    offset_magnitude = math.hypot(offset_forward, offset_lateral)

    warnings: list[str] = []
    acceptance_warnings: list[str] = []
    if maximum_curvature > CURVATURE_WARNING_PER_M:
        warning = "检测到小半径或高曲率路径，需核对底盘最小转弯半径"
        warnings.append(warning)
        acceptance_warnings.append(warning)
    maximum_curvature_jump = max(curvature_jumps, default=0.0)
    if maximum_curvature_jump > CURVATURE_JUMP_WARNING_PER_M:
        warning = "相邻路径存在较大的曲率突变"
        warnings.append(warning)
        acceptance_warnings.append(warning)
    if sharp_turns:
        warning = f"检测到 {sharp_turns} 处大角度换向"
        warnings.append(warning)
        acceptance_warnings.append(warning)
    if junction_warnings:
        warning = f"检测到 {len(junction_warnings)} 处接缝间隙需要复核"
        warnings.append(warning)
        acceptance_warnings.append(warning)
    if not configured_offset:
        warnings.append("尚未配置喷头相对底盘偏移，无法验证喷头补偿")
    if duplicate_count:
        warning = f"已过滤 {duplicate_count} 条重复喷墨路径"
        warnings.append(warning)
        acceptance_warnings.append(warning)

    risk_points = (
        min(30, sharp_turns * 4)
        + min(25, len(junction_warnings) * 3)
        + min(15, short_printing_segments * 2)
        + min(20, duplicate_count * 5)
        + (10 if maximum_curvature > CURVATURE_WARNING_PER_M else 0)
    )
    return {
        "schema": "construction-quality-diagnostics.v1",
        "scope": "all_drawing_sources",
        "measurement_level": "planned_geometry",
        "curvature": {
            "available": bool(profiles),
            "maximum_per_m": round(maximum_curvature, 4),
            "maximum_jump_per_m": round(maximum_curvature_jump, 4),
            "warning_threshold_per_m": CURVATURE_WARNING_PER_M,
        },
        "turns": {
            "available": bool(profiles),
            "maximum_heading_jump_deg": round(max(all_turns, default=0.0), 2),
            "sharp_turn_count": sharp_turns,
            "sharp_turn_threshold_deg": SHARP_TURN_DEGREES,
        },
        "junctions": {
            "available": len(profiles) >= 2,
            "checked_count": max(0, len(profiles) - 1),
            "warning_count": len(junction_warnings),
            "maximum_gap_m": round(max(junction_gaps, default=0.0), 4),
            "warning_gap_m": JUNCTION_WARNING_GAP_M,
            "items": junction_warnings,
        },
        "nozzle_offset": {
            "configured": configured_offset,
            "forward_m": round(offset_forward, 6),
            "lateral_m": round(offset_lateral, 6),
            "magnitude_m": round(offset_magnitude, 6),
            "diagnostic_only": True,
            "note": "偏移诊断不会替代 ROS2 执行器中的坐标补偿。",
        },
        "ink_quality": {
            "status": "planned_proxy_only",
            "real_measurement_available": False,
            "predicted_risk_score": min(100, risk_points),
            "short_printing_segment_count": short_printing_segments,
            "duplicate_printing_segment_count": duplicate_count,
            "note": "当前仅评估断墨、重喷和急转风险；真实线宽、覆盖率和墨迹偏差需要视觉或测量数据。",
        },
        "invalid_profile_count": invalid_profile_count,
        # Hardware calibration reminders remain visible in ``warnings``, but
        # only geometry findings lower a virtual demonstration's verdict.
        "acceptance_warnings": acceptance_warnings,
        "warnings": warnings,
    }
