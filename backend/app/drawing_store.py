from __future__ import annotations

import os
from math import atan2, cos, hypot, pi, sin
from pathlib import Path
from typing import Any

from .config import XLINE_WS_DIR


UNIT_CONVERSION_FACTOR = 1000.0
CURVE_SAMPLES = 64


def cad_directory() -> Path:
    configured = os.getenv("XLINE_CAD_DIR")
    if configured:
        return Path(configured)
    if os.getenv("XLINE_DEMO_MODE") == "1":
        return Path(__file__).resolve().parent.parent / "demo_cad"
    return Path(XLINE_WS_DIR) / "cad"


def available_drawings() -> list[str]:
    directory = cad_directory()
    try:
        return sorted(path.name for path in directory.glob("*.json") if path.is_file())
    except OSError:
        return []


def resolve_drawing(file_name: str) -> Path | None:
    candidate = Path(file_name)
    if candidate.name != file_name or candidate.suffix.lower() != ".json":
        return None
    target = cad_directory() / file_name
    return target if target.is_file() else None


def preview_paths(payload: dict[str, Any]) -> list[list[list[float]]]:
    paths: list[list[list[float]]] = []
    geometries = payload.get("lines", [])
    if not isinstance(geometries, list):
        return paths

    for geometry in geometries:
        if not isinstance(geometry, dict) or geometry.get("selected") is False:
            continue
        points = _geometry_points(geometry)
        if len(points) >= 2:
            paths.append(points)
    return paths


def _geometry_points(geometry: dict[str, Any]) -> list[list[float]]:
    geometry_type = str(geometry.get("type", "line")).lower()
    if geometry_type == "line":
        return _valid_points([geometry.get("start"), geometry.get("end")])
    if geometry_type == "polyline":
        points = _valid_points(geometry.get("vertices", []))
        if points and bool(geometry.get("closed", geometry.get("is_closed", False))):
            points.append(points[0][:])
        return points
    if geometry_type == "circle":
        return _sample_circle(geometry)
    if geometry_type == "arc":
        return _sample_arc(geometry)
    if geometry_type == "ellipse":
        return _sample_ellipse(geometry)
    if geometry_type == "spline":
        return _sample_spline(geometry)
    if geometry_type == "text":
        return _sample_text_bounds(geometry)
    return []


def _point(value: Any) -> list[float] | None:
    if not isinstance(value, dict):
        return None
    try:
        return [
            float(value["x"]) / UNIT_CONVERSION_FACTOR,
            float(value["y"]) / UNIT_CONVERSION_FACTOR,
        ]
    except (KeyError, TypeError, ValueError):
        return None


def _valid_points(values: Any) -> list[list[float]]:
    if not isinstance(values, list):
        return []
    return [point for value in values if (point := _point(value)) is not None]


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _angle(geometry: dict[str, Any], snake: str, camel: str, default: float) -> float:
    return _number(geometry.get(snake, geometry.get(camel, default)), default) * pi / 180.0


def _sample_circle(geometry: dict[str, Any]) -> list[list[float]]:
    center = _point(geometry.get("center"))
    radius = _number(geometry.get("radius")) / UNIT_CONVERSION_FACTOR
    if center is None or radius <= 0:
        return []
    return [
        [center[0] + radius * cos(2 * pi * index / CURVE_SAMPLES),
         center[1] + radius * sin(2 * pi * index / CURVE_SAMPLES)]
        for index in range(CURVE_SAMPLES + 1)
    ]


def _positive_sweep(start: float, end: float) -> float:
    sweep = end - start
    if abs(sweep) < 1e-9:
        return 2 * pi
    while sweep < 0:
        sweep += 2 * pi
    return sweep


def _sample_arc(geometry: dict[str, Any]) -> list[list[float]]:
    center = _point(geometry.get("center"))
    radius = _number(geometry.get("radius")) / UNIT_CONVERSION_FACTOR
    if center is None or radius <= 0:
        return []
    start = _angle(geometry, "start_angle", "startAngle", 0.0)
    end = _angle(geometry, "end_angle", "endAngle", 360.0)
    sweep = _positive_sweep(start, end)
    count = max(8, round(CURVE_SAMPLES * sweep / (2 * pi)))
    return [
        [center[0] + radius * cos(start + sweep * index / count),
         center[1] + radius * sin(start + sweep * index / count)]
        for index in range(count + 1)
    ]


def _sample_ellipse(geometry: dict[str, Any]) -> list[list[float]]:
    center = _point(geometry.get("center"))
    axis = _point(geometry.get("major_axis", geometry.get("majorAxis")))
    ratio = abs(_number(geometry.get("ratio"), 1.0))
    if center is None or axis is None or ratio <= 0:
        return []
    major = hypot(axis[0], axis[1])
    minor = major * ratio
    if major <= 0 or minor <= 0:
        return []
    rotation = _angle(geometry, "rotation", "Rotation", 0.0)
    orientation = atan2(axis[1], axis[0]) + rotation
    start = _angle(geometry, "start_angle", "startAngle", 0.0)
    end = _angle(geometry, "end_angle", "endAngle", 360.0)
    sweep = _positive_sweep(start, end)
    count = max(12, round(CURVE_SAMPLES * sweep / (2 * pi)))
    result = []
    for index in range(count + 1):
        angle = start + sweep * index / count
        local_x, local_y = major * cos(angle), minor * sin(angle)
        result.append([
            center[0] + local_x * cos(orientation) - local_y * sin(orientation),
            center[1] + local_x * sin(orientation) + local_y * cos(orientation),
        ])
    return result


def _sample_spline(geometry: dict[str, Any]) -> list[list[float]]:
    vertices = _valid_points(
        geometry.get("vertices")
        or geometry.get("fit_points")
        or geometry.get("fitPoints")
        or []
    )
    if len(vertices) >= 2:
        return _close_if_needed(vertices, geometry)

    control_points = _valid_points(
        geometry.get("control_points") or geometry.get("controlPoints") or []
    )
    if len(control_points) < 2:
        return []
    degree = max(1, min(int(_number(geometry.get("degree"), 3)), len(control_points) - 1))
    knots = _numeric_list(geometry.get("knots"))
    expected_knots = len(control_points) + degree + 1
    if len(knots) != expected_knots or any(left > right for left, right in zip(knots, knots[1:])):
        knots = _clamped_knots(len(control_points), degree)
    weights = _numeric_list(geometry.get("weights"))
    if len(weights) != len(control_points):
        weights = [1.0] * len(control_points)

    start, end = knots[degree], knots[-degree - 1]
    if end <= start:
        return _close_if_needed(control_points, geometry)
    points = []
    for sample in range(CURVE_SAMPLES + 1):
        parameter = start + (end - start) * sample / CURVE_SAMPLES
        basis = _basis_values(parameter, degree, knots, len(control_points), sample == CURVE_SAMPLES)
        denominator = sum(value * weight for value, weight in zip(basis, weights))
        if abs(denominator) < 1e-12:
            continue
        points.append([
            sum(value * weight * point[0] for value, weight, point in zip(basis, weights, control_points)) / denominator,
            sum(value * weight * point[1] for value, weight, point in zip(basis, weights, control_points)) / denominator,
        ])
    return _close_if_needed(points, geometry)


def _sample_text_bounds(geometry: dict[str, Any]) -> list[list[float]]:
    position = _point(geometry.get("position"))
    content = str(geometry.get("content", ""))
    if position is None or not content:
        return []
    height = _number(geometry.get("height"), 50.0) / UNIT_CONVERSION_FACTOR
    width = len(content) * height * _number(geometry.get("width_factor"), 1.0) * 0.6
    angle = _number(geometry.get("rotation"), 0.0) * pi / 180.0
    align = geometry.get("align") if isinstance(geometry.get("align"), dict) else {}
    offset = {"center": -0.5, "right": -1.0}.get(str(align.get("horizontal")), 0.0)
    start = [position[0] + offset * width * cos(angle), position[1] + offset * width * sin(angle)]
    return [start, [start[0] + width * cos(angle), start[1] + width * sin(angle)]]


def _numeric_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return []


def _clamped_knots(control_count: int, degree: int) -> list[float]:
    interior_count = control_count - degree - 1
    return (
        [0.0] * (degree + 1)
        + [index / (interior_count + 1) for index in range(1, interior_count + 1)]
        + [1.0] * (degree + 1)
    )


def _basis_values(
    parameter: float,
    degree: int,
    knots: list[float],
    control_count: int,
    at_end: bool,
) -> list[float]:
    basis = [
        1.0 if knots[index] <= parameter < knots[index + 1] else 0.0
        for index in range(control_count)
    ]
    if at_end:
        basis[-1] = 1.0
    for order in range(1, degree + 1):
        previous = basis
        basis = [0.0] * control_count
        for index in range(control_count):
            left_span = knots[index + order] - knots[index]
            if left_span > 0:
                basis[index] += (parameter - knots[index]) / left_span * previous[index]
            if index + 1 < control_count:
                right_span = knots[index + order + 1] - knots[index + 1]
                if right_span > 0:
                    basis[index] += (knots[index + order + 1] - parameter) / right_span * previous[index + 1]
    return basis


def _close_if_needed(
    points: list[list[float]], geometry: dict[str, Any]
) -> list[list[float]]:
    if points and bool(geometry.get("closed", geometry.get("is_closed", False))):
        if points[0] != points[-1]:
            points.append(points[0][:])
    return points
