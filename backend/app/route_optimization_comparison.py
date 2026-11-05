from __future__ import annotations

import math
from typing import Any

from .drawing_store import geometry_preview_paths


def _distance(left: list[float], right: list[float]) -> float:
    return math.hypot(float(right[0]) - float(left[0]), float(right[1]) - float(left[1]))


def _usable_paths(geometries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload = {"lines": geometries}
    result: list[dict[str, Any]] = []
    for source_index, item in enumerate(geometry_preview_paths(payload)):
        points = item.get("points")
        if not isinstance(points, list) or len(points) < 2:
            continue
        result.append({
            "source_index": source_index,
            "geometry_id": item.get("geometry_id"),
            "points": [[float(point[0]), float(point[1])] for point in points],
        })
    return result


def _evaluate_order(
    paths: list[dict[str, Any]],
    order: list[tuple[int, bool]],
    start_point_m: list[float],
) -> dict[str, Any]:
    cursor = [float(start_point_m[0]), float(start_point_m[1])]
    transition_paths: list[dict[str, Any]] = []
    transition_length = 0.0
    printing_length = 0.0
    ordered: list[dict[str, Any]] = []
    for sequence, (path_index, reversed_path) in enumerate(order, start=1):
        path = paths[path_index]
        points = list(reversed(path["points"])) if reversed_path else path["points"]
        jump = _distance(cursor, points[0])
        if jump > 1e-9:
            transition_paths.append({
                "namespace": "route_optimization_advisory",
                "route_type": "transition_advisory",
                "points": [cursor[:], points[0][:]],
                "length_m": round(jump, 6),
            })
            transition_length += jump
        printing_length += sum(
            _distance(points[index - 1], points[index])
            for index in range(1, len(points))
        )
        ordered.append({
            "sequence": sequence,
            "source_index": path["source_index"],
            "geometry_id": path.get("geometry_id"),
            "reversed": reversed_path,
        })
        cursor = points[-1][:]
    return {
        "order": ordered,
        "printing_length_m": round(printing_length, 6),
        "transition_length_m": round(transition_length, 6),
        "total_length_m": round(printing_length + transition_length, 6),
        "transition_paths": transition_paths,
    }


def build_route_optimization_comparison(
    geometries: list[dict[str, Any]],
    *,
    start_point_m: list[float] | None = None,
) -> dict[str, Any]:
    """Build a deterministic geometric ordering suggestion.

    This is deliberately advisory. It ignores vehicle kinematics, collision
    constraints, printer timing and localization quality, so only the ROS2
    planner may produce an executable route.
    """
    start = start_point_m if isinstance(start_point_m, list) and len(start_point_m) >= 2 else [0.0, 0.0]
    paths = _usable_paths(geometries)
    if not paths:
        return {
            "schema": "route-optimization-comparison.v1",
            "status": "not_available",
            "authority": "advisory_only",
            "execution_allowed": False,
            "reason": "no_printing_paths",
        }

    baseline_order = [(index, False) for index in range(len(paths))]
    baseline = _evaluate_order(paths, baseline_order, start)

    remaining = set(range(len(paths)))
    cursor = [float(start[0]), float(start[1])]
    suggested_order: list[tuple[int, bool]] = []
    while remaining:
        candidates: list[tuple[float, int, bool]] = []
        for index in remaining:
            points = paths[index]["points"]
            candidates.append((_distance(cursor, points[0]), index, False))
            if _distance(points[0], points[-1]) > 1e-9:
                candidates.append((_distance(cursor, points[-1]), index, True))
        _, selected, reversed_path = min(candidates, key=lambda item: (item[0], item[1], item[2]))
        suggested_order.append((selected, reversed_path))
        selected_points = paths[selected]["points"]
        cursor = (selected_points[0] if reversed_path else selected_points[-1])[:]
        remaining.remove(selected)

    advisory = _evaluate_order(paths, suggested_order, start)
    saving = max(0.0, baseline["transition_length_m"] - advisory["transition_length_m"])
    ratio = saving / baseline["transition_length_m"] if baseline["transition_length_m"] > 0 else 0.0
    return {
        "schema": "route-optimization-comparison.v1",
        "status": "advisory_ready",
        "authority": "advisory_only",
        "method": "deterministic_nearest_endpoint",
        "source_path_count": len(paths),
        "start_point_m": [round(float(start[0]), 6), round(float(start[1]), 6)],
        "baseline": baseline,
        "advisory": advisory,
        "estimated_transition_saving_m": round(saving, 6),
        "estimated_transition_saving_ratio": round(ratio, 6),
        "execution_allowed": False,
        "requires_ros2_validation": True,
        "limitations": [
            "仅比较图元顺序和遍历方向",
            "未校验底盘运动学、碰撞、喷墨时序和定位质量",
            "不能替代 ROS2 规划结果",
        ],
    }


def attach_ros2_result(
    comparison: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    result = dict(comparison)
    if result.get("status") != "advisory_ready":
        return result
    try:
        actual_travel = float(summary.get("travel_length_m", 0.0) or 0.0)
        actual_total = float(summary.get("total_length_m", 0.0) or 0.0)
    except (TypeError, ValueError):
        return result
    advisory = result.get("advisory") if isinstance(result.get("advisory"), dict) else {}
    suggested_travel = float(advisory.get("transition_length_m", 0.0) or 0.0)
    result["ros2_result"] = {
        "available": True,
        "transition_length_m": round(actual_travel, 6),
        "total_length_m": round(actual_total, 6),
        "geometric_difference_m": round(actual_travel - suggested_travel, 6),
        "note": "差值仅用于诊断；ROS2 路线包含实际施工约束，不能按距离单独判定优劣。",
    }
    return result
