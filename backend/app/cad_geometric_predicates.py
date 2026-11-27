"""Reusable geometric predicates over backend-produced CAD geometry.

This module is measurement-only.  It never creates, edits or repairs geometry,
and it never reads a plan's requested value as evidence.  The predicates here
fill the gaps that the existing single-object binder could not express:

* mirror symmetry of a closed outline;
* closure of an outline from its actual endpoints;
* a one-to-one collection of circles placed on the corners of one rectangle.

Every predicate reports raw measurements and an explicit tolerance so a caller
can record ``verified`` / ``failed`` / ``unverified`` without guessing.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

from .cad_semantic_dispatch import heart_features

DEFAULT_TOLERANCE_MM = 0.5


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _point(item: Any) -> tuple[float, float] | None:
    if not isinstance(item, dict):
        return None
    x, y = _number(item.get("x")), _number(item.get("y"))
    return (x, y) if x is not None and y is not None else None


def outline_points(geometry: dict[str, Any]) -> list[tuple[float, float]]:
    """Return polyline vertices without an artificial duplicate endpoint."""
    if not isinstance(geometry, dict) or geometry.get("type") != "polyline":
        return []
    vertices = geometry.get("vertices") or []
    points = [point for item in vertices if (point := _point(item)) is not None]
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    return points


def measure_geometry(geometry: dict[str, Any]) -> dict[str, Any] | None:
    """Measure one backend geometry without using any requested value."""
    if not isinstance(geometry, dict):
        return None
    kind = str(geometry.get("type") or "")
    if kind == "circle":
        center = _point(geometry.get("center"))
        radius = _number(geometry.get("radius"))
        if center is None or radius is None or radius <= 0:
            return None
        return {
            "kind": "circle",
            "geometry_id": geometry.get("id"),
            "center_mm": list(center),
            "radius_mm": radius,
            "diameter_mm": radius * 2.0,
            "bounds": {
                "min_x": center[0] - radius,
                "min_y": center[1] - radius,
                "max_x": center[0] + radius,
                "max_y": center[1] + radius,
            },
        }
    if kind == "arc":
        center = _point(geometry.get("center"))
        radius = _number(geometry.get("radius"))
        start = _number(geometry.get("start_angle"))
        end = _number(geometry.get("end_angle"))
        if center is None or radius is None or radius <= 0:
            return None
        sweep = ((end - start) % 360.0) if start is not None and end is not None else None
        if sweep is not None and sweep <= 1e-9 and end is not None and start is not None \
                and end > start:
            sweep = 360.0
        angles = []
        if sweep is not None:
            count = max(2, int(abs(sweep) / 2.0) + 1)
            angles = [math.radians((start or 0.0) + sweep * index / (count - 1))
                      for index in range(count)]
        coordinates = [(center[0] + radius * math.cos(angle),
                        center[1] + radius * math.sin(angle)) for angle in angles]
        xs = [point[0] for point in coordinates] or [center[0] - radius, center[0] + radius]
        ys = [point[1] for point in coordinates] or [center[1] - radius, center[1] + radius]
        return {
            "kind": "arc",
            "geometry_id": geometry.get("id"),
            "center_mm": list(center),
            "radius_mm": radius,
            "diameter_mm": radius * 2.0,
            "start_angle_deg": start,
            "end_angle_deg": end,
            "sweep_deg": sweep,
            "bounds": {
                "min_x": min(xs), "min_y": min(ys),
                "max_x": max(xs), "max_y": max(ys),
            },
        }
    if kind == "line":
        start = _point(geometry.get("start"))
        end = _point(geometry.get("end"))
        if start is None or end is None:
            return None
        return {
            "kind": "line",
            "geometry_id": geometry.get("id"),
            "start_mm": list(start),
            "end_mm": list(end),
            "length_mm": math.dist(start, end),
            "bounds": {
                "min_x": min(start[0], end[0]), "min_y": min(start[1], end[1]),
                "max_x": max(start[0], end[0]), "max_y": max(start[1], end[1]),
            },
        }
    points = outline_points(geometry)
    if kind == "polyline" and len(points) >= 2:
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        closed = geometry.get("closed") is True
        gap = math.dist(points[-1], points[0]) if len(points) > 1 else None
        return {
            "kind": "outline",
            "geometry_id": geometry.get("id"),
            "points_mm": [list(point) for point in points],
            "vertex_count": len(points),
            "closed": closed,
            "endpoint_gap_mm": gap,
            "bounds": {
                "min_x": min(xs), "min_y": min(ys),
                "max_x": max(xs), "max_y": max(ys),
            },
            "center_mm": [(min(xs) + max(xs)) / 2.0,
                          (min(ys) + max(ys)) / 2.0],
            "width_mm": max(xs) - min(xs),
            "height_mm": max(ys) - min(ys),
        }
    return None


def rectangle_measure(geometry: dict[str, Any],
                      tolerance_mm: float = DEFAULT_TOLERANCE_MM) -> dict[str, Any] | None:
    """Return an axis-aligned rectangle measurement, or None."""
    measured = measure_geometry(geometry)
    if measured is None or measured["kind"] != "outline":
        return None
    points = [tuple(point) for point in measured["points_mm"]]
    if len(points) != 4 or not measured["closed"]:
        return None
    sides = []
    for index, point in enumerate(points):
        nxt = points[(index + 1) % 4]
        dx, dy = nxt[0] - point[0], nxt[1] - point[1]
        if abs(dx) > tolerance_mm and abs(dy) > tolerance_mm:
            return None
        length = math.hypot(dx, dy)
        if length <= tolerance_mm:
            return None
        sides.append(length)
    if not (math.isclose(sides[0], sides[2], rel_tol=0.0, abs_tol=tolerance_mm)
            and math.isclose(sides[1], sides[3], rel_tol=0.0, abs_tol=tolerance_mm)):
        return None
    return {
        **measured,
        "kind": "rectangle",
        "width_mm": measured["width_mm"],
        "height_mm": measured["height_mm"],
        "corner_points_mm": [list(point) for point in points],
    }


def _point_segment_distance(point, start, end) -> float:
    """Distance from a point to a finite segment."""
    px, py = point
    x0, y0 = start
    x1, y1 = end
    dx, dy = x1 - x0, y1 - y0
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-18:
        return math.dist(point, start)
    projection = ((px - x0) * dx + (py - y0) * dy) / length_sq
    projection = max(0.0, min(1.0, projection))
    return math.dist(point, (x0 + projection * dx, y0 + projection * dy))


def _segment_set_hausdorff(first: list[tuple], second: list[tuple]) -> float:
    """Directed segment-set Hausdorff distance (symmetric maximum).

    Each source segment is sampled at quarter points because the distance to a
    *union* of target segments is not convex; endpoint-only checks can accept
    a symmetric vertex cloud whose connecting edges differ.  This measures the
    actual rendered polyline, not only vertices.
    """
    def farthest(source: list[tuple], target: list[tuple]) -> float:
        maximum = 0.0
        for start, end in source:
            for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
                point = (start[0] + fraction * (end[0] - start[0]),
                         start[1] + fraction * (end[1] - start[1]))
                distance = min(
                    _point_segment_distance(point, t_start, t_end)
                    for t_start, t_end in target
                )
                maximum = max(maximum, distance)
        return maximum

    return max(farthest(first, second), farthest(second, first))


def mirror_symmetry(points: Iterable[tuple[float, float]], axis_x_mm: float,
                    tolerance_mm: float = DEFAULT_TOLERANCE_MM,
                    *, axis_source: str = "caller_supplied",
                    closed: bool = True) -> dict[str, Any]:
    """Measure mirror symmetry of the actual polyline segment set.

    For every vertex the mirrored point must lie on an actual original segment,
    and every original segment endpoint must lie on the mirrored segment set.
    A vertex cloud can be symmetric while its connections are not; this
    segment-set Hausdorff check rejects that case.

    ``closed`` controls whether the implicit last -> first edge exists.  An open
    polyline must never borrow a closing edge: doing so would let an open arc
    or half-outline pass a symmetry proof it does not actually have.
    """
    points = list(points)
    if len(points) < 3:
        return {"status": "unverified", "reason": "outline_has_too_few_points",
                "point_count": len(points), "tolerance_mm": tolerance_mm}
    original_segments = list(zip(points, points[1:]))
    if closed and len(points) > 2:
        original_segments.append((points[-1], points[0]))
    mirrored_points = [(2.0 * axis_x_mm - x, y) for x, y in points]
    mirrored_segments = list(zip(mirrored_points, mirrored_points[1:]))
    if closed and len(mirrored_points) > 2:
        mirrored_segments.append((mirrored_points[-1], mirrored_points[0]))
    vertex_errors = [
        min(_point_segment_distance((2.0 * axis_x_mm - x, y), start, end)
            for start, end in original_segments)
        for x, y in points
    ]
    maximum = _segment_set_hausdorff(original_segments, mirrored_segments)
    return {
        "status": "verified" if maximum <= tolerance_mm else "failed",
        "axis_x_mm": axis_x_mm,
        "axis_source": axis_source,
        "point_count": len(points),
        "closed": closed,
        "segment_count": len(original_segments),
        "max_error_mm": maximum,
        "max_vertex_to_segment_error_mm": max(vertex_errors, default=None),
        "mean_vertex_error_mm": (sum(vertex_errors) / len(vertex_errors)
                                if vertex_errors else None),
        "tolerance_mm": tolerance_mm,
        "measurement": "segment_set_hausdorff",
    }


def closure_measure(points: Iterable[tuple[float, float]], *,
                    closed: bool,
                    tolerance_mm: float = DEFAULT_TOLERANCE_MM,
                    smooth_angle_tolerance_deg: float = 5.0,
                    require_smooth: bool = False,
                    allowed_cusp_source: str | None = None,
                    allowed_cusp_limit: int = 0,
                    allowed_cusp_points: Iterable[tuple[float, float]] | None = None,
                    smooth_closure_gap: bool = False) -> dict[str, Any]:
    """Measure closure and continuity as independent geometric predicates.

    ``closed`` is the executor's actual implicit closing edge (last -> first).
    A closed polyline is therefore not failed merely because that final edge is
    long; a false flag is always a closure failure.  Continuity is measured
    separately from every measured join and is never derived from ``closed``.

    A sharp reversal is accepted only when the caller supplies both a source
    label and the source's measured cusp coordinates.  Being on the vertical
    centre line is not a source: a centre-line heuristic is not accepted.

    When ``smooth_closure_gap`` is true, a source that requires a smooth closed
    contour also requires the sampled first/last points to meet.  Otherwise
    the implicit closing edge is a long straight chord inserted into an
    otherwise smooth curve, which is a real geometric defect even though the
    executor's boolean ``closed`` flag is true.  Ordinary polygonal outlines
    leave this off because their closing edge is an intended segment.
    """
    points = list(points)
    if len(points) < 3:
        return {"status": "unverified", "reason": "outline_has_too_few_points",
                "point_count": len(points)}
    gap = math.dist(points[-1], points[0])
    edges = [math.dist(points[index], points[(index + 1) % len(points)])
             for index in range(len(points))]
    typical_edge = sorted(edges)[len(edges) // 2] if edges else 0.0
    # A dense sampled curve legitimately ends less than one sample step from
    # its start.  Half a median edge is a conservative allowance: F03's
    # 95.289 mm gap is 1.32 median edges and is a real chord; A9's 3.03 mm gap
    # is 0.04 median edges and is only the last sampling step.
    long_smooth_gap = bool(
        smooth_closure_gap and require_smooth
        and not closed
    ) or bool(
        smooth_closure_gap and require_smooth
        and gap > max(tolerance_mm, 0.5 * typical_edge)
    )
    joins = []
    for index in range(len(points)):
        prev, current, nxt = points[index - 1], points[index], points[(index + 1) % len(points)]
        u = (current[0] - prev[0], current[1] - prev[1])
        v = (nxt[0] - current[0], nxt[1] - current[1])
        lengths = math.hypot(*u) * math.hypot(*v)
        if lengths <= 1e-12:
            continue
        cosine = max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / lengths))
        joins.append({
            "index": index,
            "turn_deg": math.degrees(math.acos(cosine)),
            "point_mm": [current[0], current[1]],
        })
    reversals = [join for join in joins
                 if join["turn_deg"] > 180.0 - smooth_angle_tolerance_deg]
    intentional_cusps = []
    cusp_source_ok = bool(allowed_cusp_source and allowed_cusp_limit > 0
                          and allowed_cusp_points)
    if cusp_source_ok:
        accepted: list[dict[str, Any]] = []
        for point in allowed_cusp_points or []:
            nearest = min(
                reversals,
                key=lambda join: math.dist(join["point_mm"], point),
                default=None,
            )
            if (nearest is not None
                    and math.dist(nearest["point_mm"], point)
                    <= max(tolerance_mm, 1.0)
                    and nearest not in accepted):
                accepted.append(nearest)
        intentional_cusps = accepted[:allowed_cusp_limit]
    unexpected_reversals = [join for join in reversals
                            if join not in intentional_cusps]
    remaining = [join for join in joins if join not in intentional_cusps]
    max_smooth_turn = max((join["turn_deg"] for join in remaining), default=None)
    over_limit = [join for join in remaining
                  if join["turn_deg"] > smooth_angle_tolerance_deg]
    closure_failed = not closed or long_smooth_gap
    continuity_failed = bool(require_smooth and over_limit)
    failed = closure_failed or continuity_failed
    return {
        "status": "failed" if failed else "verified",
        "closure_status": "failed" if closure_failed else "verified",
        "closure_gap_status": (
            "failed" if long_smooth_gap else "verified"
            if smooth_closure_gap and require_smooth else "not_required"
        ),
        "continuity_status": ("failed" if continuity_failed
                              else "verified" if require_smooth
                              else "not_required"),
        "closed_flag": bool(closed),
        "endpoint_gap_mm": gap,
        "implicit_closing_edge_mm": gap,
        "tolerance_mm": tolerance_mm,
        "smooth_angle_tolerance_deg": smooth_angle_tolerance_deg,
        "max_turn_deg": max((join["turn_deg"] for join in joins), default=None),
        "max_smooth_turn_deg": max_smooth_turn,
        "sharp_join_count": len(reversals),
        "intentional_cusps": intentional_cusps,
        "cusp_source": allowed_cusp_source,
        "cusp_limit": int(allowed_cusp_limit),
        "unexpected_sharp_join_count": len(unexpected_reversals),
        "unexpected_turn_count": len(over_limit),
        "unexpected_turns": over_limit[:8],
        "require_smooth": bool(require_smooth),
    }


def heart_cusp_points(geometry: dict[str, Any]) -> list[tuple[float, float]]:
    """Return the two source-backed heart cusp coordinates in millimetres.

    The coordinates come from the same verified four-feature measurement
    (normalized centre notch and lower tip), never from the bounding-box
    centre line.  Empty output means the geometry did not prove the features.
    """
    measured = heart_features([geometry])
    features = measured.get("features") or {}
    if not features or not all(features.values()):
        return []
    points = measured.get("points") or []
    bounds = measured.get("bounds_mm") or {}
    if not points or not bounds:
        return []
    width = bounds["max_x"] - bounds["min_x"]
    height = bounds["max_y"] - bounds["min_y"]
    if width <= 0 or height <= 0:
        return []

    def millimetres(point: tuple[float, float]) -> tuple[float, float]:
        return (bounds["min_x"] + point[0] * width,
                bounds["min_y"] + point[1] * height)

    def sharp(point_index: int) -> bool:
        previous = points[point_index - 1]
        current = points[point_index]
        following = points[(point_index + 1) % len(points)]
        u = (current[0] - previous[0], current[1] - previous[1])
        v = (following[0] - current[0], following[1] - current[1])
        lengths = math.hypot(*u) * math.hypot(*v)
        if lengths <= 1e-12:
            return False
        cosine = max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / lengths))
        return math.degrees(math.acos(cosine)) > 175.0

    notch = [(index, point) for index, point in enumerate(points)
             if sharp(index)
             and abs(point[0] - 0.5) < 0.03 and 0.5 < point[1] < 0.9]
    tip = [(index, point) for index, point in enumerate(points)
           if sharp(index)
           and abs(point[0] - 0.5) < 0.10 and point[1] <= 0.01]
    cusps: list[tuple[float, float]] = []
    if notch:
        cusps.append(millimetres(min(notch, key=lambda item: item[1][1])[1]))
    if tip:
        cusps.append(millimetres(min(tip, key=lambda item: item[1][1])[1]))
    return cusps


def heart_outline_measure(geometry: dict[str, Any]) -> dict[str, Any]:
    """Reuse the existing four-feature heart measurement on one outline."""
    measured = heart_features([geometry])
    features = measured.get("features") or {}
    return {
        "status": "verified" if features and all(features.values()) else "failed",
        "geometry_id": geometry.get("id"),
        "features": features,
        "normalization": measured.get("normalization"),
    }


def corner_circle_collection(rectangle: dict[str, Any],
                             circles: list[dict[str, Any]],
                             *,
                             expected_count: int | None,
                             corner_tolerance_mm: float = DEFAULT_TOLERANCE_MM,
                             radius_tolerance_mm: float = DEFAULT_TOLERANCE_MM,
                             expected_radius_mm: float | None = None) -> dict[str, Any]:
    """Verify a one-to-one circle-to-rectangle-corner placement.

    Every circle centre must match a distinct rectangle corner, and every
    rectangle corner must be covered exactly once.  The caller supplies only
    the expected count/radius parsed from the source, never a per-case position.
    """
    rect = rectangle_measure(rectangle)
    if rect is None:
        return {"status": "unverified", "reason": "rectangle_not_measured"}
    measures = [measure_geometry(item) for item in circles]
    if any(item is None or item["kind"] != "circle" for item in measures):
        return {"status": "unverified", "reason": "collection_contains_non_circle"}
    if expected_count is not None and len(measures) != int(expected_count):
        return {
            "status": "failed",
            "reason": "collection_count_mismatch",
            "expected_count": int(expected_count),
            "actual_count": len(measures),
            "geometry_ids": [item.get("geometry_id") for item in measures],
        }
    corners = [tuple(point) for point in rect["corner_points_mm"]]
    assignments = []
    unmatched_circles = []
    used_corners: set[int] = set()
    for circle in measures:
        center = tuple(circle["center_mm"])
        distances = [math.dist(center, corner) for corner in corners]
        index = min(range(len(corners)), key=lambda i: distances[i])
        if distances[index] > corner_tolerance_mm or index in used_corners:
            unmatched_circles.append({
                "geometry_id": circle["geometry_id"],
                "center_mm": list(center),
                "nearest_corner_mm": list(corners[index]),
                "nearest_distance_mm": distances[index],
                "corner_already_used": index in used_corners,
            })
            continue
        used_corners.add(index)
        assignments.append({
            "geometry_id": circle["geometry_id"],
            "center_mm": list(center),
            "corner_mm": list(corners[index]),
            "distance_mm": distances[index],
            "radius_mm": circle["radius_mm"],
        })
    radius_mismatch = []
    if expected_radius_mm is not None:
        for circle in measures:
            if abs(circle["radius_mm"] - expected_radius_mm) > radius_tolerance_mm:
                radius_mismatch.append({
                    "geometry_id": circle["geometry_id"],
                    "actual_mm": circle["radius_mm"],
                    "expected_mm": expected_radius_mm,
                    "delta_mm": abs(circle["radius_mm"] - expected_radius_mm),
                })
    passed = (not unmatched_circles and not radius_mismatch
              and len(used_corners) == len(corners) == len(measures))
    return {
        "status": "verified" if passed else "failed",
        "expected_count": expected_count,
        "actual_count": len(measures),
        "rectangle_geometry_id": rectangle.get("id"),
        "circle_geometry_ids": [item.get("geometry_id") for item in measures],
        "assignments": assignments,
        "unmatched_circles": unmatched_circles,
        "radius_mismatch": radius_mismatch,
        "corner_tolerance_mm": corner_tolerance_mm,
        "radius_tolerance_mm": radius_tolerance_mm,
        "expected_radius_mm": expected_radius_mm,
        "authority": "backend_measured_geometry",
    }
