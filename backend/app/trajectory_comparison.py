from __future__ import annotations

import math
from typing import Any


def compare_trajectories(
    planned_paths: list[dict[str, Any]],
    actual_trace: list[list[float]],
    tolerance_m: float = 0.15,
) -> dict[str, Any]:
    planned = _planned_polylines(planned_paths)
    actual = [
        (float(point[0]), float(point[1]))
        for point in actual_trace
        if isinstance(point, (list, tuple)) and len(point) >= 2
        and _finite(point[0]) and _finite(point[1])
    ]
    planned_points = [point for path in planned for point in path]
    if not planned or len(planned_points) < 2 or len(actual) < 2:
        return {
            "available": False,
            "reason": "规划轨迹或实测位姿点不足",
            "planned_point_count": len(planned_points),
            "actual_point_count": len(actual),
        }

    deviations = [min(_point_polyline_distance(point, path) for path in planned) for point in actual]
    sorted_deviations = sorted(deviations)
    p95_index = min(len(sorted_deviations) - 1, math.ceil(len(sorted_deviations) * 0.95) - 1)
    covered = sum(
        min(math.dist(point, actual_point) for actual_point in actual) <= tolerance_m
        for point in planned_points
    )
    planned_end = planned[-1][-1]
    actual_end = actual[-1]
    return {
        "available": True,
        "tolerance_m": tolerance_m,
        "planned_point_count": len(planned_points),
        "actual_point_count": len(actual),
        "mean_deviation_m": round(sum(deviations) / len(deviations), 4),
        "maximum_deviation_m": round(max(deviations), 4),
        "p95_deviation_m": round(sorted_deviations[p95_index], 4),
        "endpoint_error_m": round(math.dist(planned_end, actual_end), 4),
        "planned_vertex_coverage": round(covered / len(planned_points), 4),
    }


def _planned_polylines(paths: list[dict[str, Any]]) -> list[list[tuple[float, float]]]:
    result: list[list[tuple[float, float]]] = []
    for item in paths:
        points = item.get("points") if isinstance(item, dict) else None
        if not isinstance(points, list):
            continue
        valid = [
            (float(point[0]), float(point[1]))
            for point in points
            if isinstance(point, (list, tuple)) and len(point) >= 2
            and _finite(point[0]) and _finite(point[1])
        ]
        if len(valid) >= 2:
            result.append(valid)
    return result


def _point_polyline_distance(
    point: tuple[float, float], polyline: list[tuple[float, float]]
) -> float:
    return min(
        _point_segment_distance(point, start, end)
        for start, end in zip(polyline, polyline[1:])
    )


def _point_segment_distance(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return math.dist(point, start)
    ratio = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared))
    projection = (start[0] + ratio * dx, start[1] + ratio * dy)
    return math.dist(point, projection)


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False
