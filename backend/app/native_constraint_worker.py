"""Isolated native PlaneGCS/SolveSpace worker.

The worker speaks JSON over stdin/stdout so a native crash, solver assertion,
or ABI mismatch cannot take down the FastAPI process.  It only mutates the
declared target geometry; the caller independently verifies every residual.
"""

from __future__ import annotations

import json
import math
import sys
from copy import deepcopy
from typing import Any


def _points(geometry: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for key in ("start", "end", "center"):
        if isinstance(geometry.get(key), dict):
            values.append(geometry[key])
    for key in ("vertices", "control_points"):
        if isinstance(geometry.get(key), list):
            values.extend(item for item in geometry[key] if isinstance(item, dict))
    return values


def _center(geometry: dict[str, Any]) -> tuple[float, float]:
    if isinstance(geometry.get("center"), dict):
        center = geometry["center"]
        return float(center["x"]), float(center["y"])
    points = _points(geometry)
    xs = [float(item["x"]) for item in points]
    ys = [float(item["y"]) for item in points]
    if not xs:
        raise ValueError("geometry has no center-bearing coordinates")
    return (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0


def _direction(geometry: dict[str, Any]) -> tuple[float, float]:
    if geometry.get("type") == "line":
        start, end = geometry["start"], geometry["end"]
    elif geometry.get("type") == "polyline" and len(geometry.get("vertices") or []) >= 2:
        start, end = geometry["vertices"][0], geometry["vertices"][1]
    elif geometry.get("type") == "ellipse" and isinstance(geometry.get("major_axis"), dict):
        axis = geometry["major_axis"]
        return float(axis["x"]), float(axis["y"])
    else:
        raise ValueError("direction constraint requires a linear geometry")
    return float(end["x"]) - float(start["x"]), float(end["y"]) - float(start["y"])


def _size(geometry: dict[str, Any]) -> tuple[float, float]:
    if geometry.get("type") in {"circle", "arc"}:
        diameter = 2.0 * float(geometry["radius"])
        return diameter, diameter
    points = _points(geometry)
    xs = [float(item["x"]) for item in points]
    ys = [float(item["y"]) for item in points]
    return max(xs) - min(xs), max(ys) - min(ys)


def _translate(geometry: dict[str, Any], dx: float, dy: float) -> None:
    for point in _points(geometry):
        point["x"] = float(point["x"]) + dx
        point["y"] = float(point["y"]) + dy


def _rotate(geometry: dict[str, Any], angle: float) -> None:
    cx, cy = _center(geometry)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    for point in _points(geometry):
        x, y = float(point["x"]) - cx, float(point["y"]) - cy
        point["x"] = cx + x * cos_a - y * sin_a
        point["y"] = cy + x * sin_a + y * cos_a
    if geometry.get("type") == "ellipse" and isinstance(geometry.get("major_axis"), dict):
        axis = geometry["major_axis"]
        x, y = float(axis["x"]), float(axis["y"])
        axis["x"] = x * cos_a - y * sin_a
        axis["y"] = x * sin_a + y * cos_a


def _scale(geometry: dict[str, Any], sx: float, sy: float) -> None:
    cx, cy = _center(geometry)
    if geometry.get("type") in {"circle", "arc"}:
        if abs(sx - sy) > 1e-9:
            raise ValueError("circle equal-size fallback requires uniform scale")
        geometry["radius"] = float(geometry["radius"]) * sx
        return
    for point in _points(geometry):
        point["x"] = cx + (float(point["x"]) - cx) * sx
        point["y"] = cy + (float(point["y"]) - cy) * sy


def _geometry_by_ref(
    geometries: list[dict[str, Any]], symbol_table: dict[str, list[int]], ref: str,
) -> dict[str, Any]:
    ids = symbol_table.get(ref) or []
    if len(ids) != 1:
        raise ValueError(f"native constraint reference {ref!r} is not a single geometry")
    geometry_id = int(ids[0])
    return next(item for item in geometries if int(item.get("id", -1)) == geometry_id)


def _planegcs_pair(kind: str, target: dict[str, Any], reference: dict[str, Any], distance: float) -> dict[str, Any]:
    from planegcs import Sketch, SolveStatus

    sketch = Sketch()
    if kind in {"concentric", "center_distance"}:
        rx, ry = _center(reference)
        tx, ty = _center(target)
        reference_point = sketch.add_fixed_point(rx, ry)
        target_point = sketch.add_point(tx, ty)
        if kind == "concentric":
            sketch.coincident(target_point, reference_point)
        else:
            sketch.set_p2p_distance(reference_point, target_point, distance)
        status = sketch.solve()
        sx, sy = sketch.get_point(target_point)
        _translate(target, sx - tx, sy - ty)
    elif kind in {"parallel", "perpendicular"}:
        rdx, rdy = _direction(reference)
        tdx, tdy = _direction(target)
        target_length = math.hypot(tdx, tdy)
        origin = sketch.add_fixed_point(0.0, 0.0)
        ref_end = sketch.add_fixed_point(rdx, rdy)
        target_end = sketch.add_point(tdx, tdy)
        ref_line = sketch.add_line(origin, ref_end)
        target_line = sketch.add_line(origin, target_end)
        sketch.set_p2p_distance(origin, target_end, target_length)
        if kind == "parallel":
            sketch.parallel(target_line, ref_line)
        else:
            sketch.perpendicular(target_line, ref_line)
        status = sketch.solve()
        sx, sy = sketch.get_point(target_end)
        old_angle = math.atan2(tdy, tdx)
        _rotate(target, math.atan2(sy, sx) - old_angle)
    elif kind == "equal_radius":
        if target.get("type") not in {"circle", "arc"} or reference.get("type") not in {"circle", "arc"}:
            raise ValueError("equal_radius requires circles or arcs")
        c1 = sketch.add_fixed_point(0.0, 0.0)
        c2 = sketch.add_fixed_point(10.0, 0.0)
        r1 = sketch.add_fixed_param(float(reference["radius"]))
        r2 = sketch.add_param(float(target["radius"]))
        circle1 = sketch.add_circle(c1, r1)
        circle2 = sketch.add_circle(c2, r2)
        sketch.equal_radius_cc(circle2, circle1)
        status = sketch.solve()
        target["radius"] = float(sketch.get_circle(circle2).radius)
    else:
        raise ValueError(f"unsupported PlaneGCS constraint: {kind}")
    diagnosis = sketch.diagnose()
    if status not in {SolveStatus.Success, SolveStatus.Converged}:
        raise RuntimeError(f"PlaneGCS solve failed: {status}")
    return {
        "status": status.name.lower(),
        "degrees_of_freedom": int(diagnosis.dof),
        "conflicting": [int(value) for value in diagnosis.conflicting],
        "redundant": [int(value) for value in diagnosis.redundant],
    }


def _slvs_point(slvs: Any, entity: dict[str, Any]) -> tuple[float, float]:
    return (
        float(slvs.get_param_value(int(entity["param"][0]))),
        float(slvs.get_param_value(int(entity["param"][1]))),
    )


def _solvespace_pair(kind: str, target: dict[str, Any], reference: dict[str, Any], distance: float) -> dict[str, Any]:
    import slvs

    slvs.clear_sketch()
    workplane = slvs.add_base_2d(1)
    if kind in {"concentric", "center_distance"}:
        rx, ry = _center(reference)
        tx, ty = _center(target)
        reference_point = slvs.add_point_2d(1, rx, ry, workplane)
        target_point = slvs.add_point_2d(2, tx, ty, workplane)
        if kind == "concentric":
            slvs.coincident(2, target_point, reference_point, workplane)
        else:
            slvs.distance(2, reference_point, target_point, distance, workplane)
        result, failed = slvs.solve_sketch(2, True)
        sx, sy = _slvs_point(slvs, target_point)
        _translate(target, sx - tx, sy - ty)
    elif kind in {"parallel", "perpendicular"}:
        rdx, rdy = _direction(reference)
        tdx, tdy = _direction(target)
        length = math.hypot(tdx, tdy)
        ref_start = slvs.add_point_2d(1, 0.0, 0.0, workplane)
        ref_end = slvs.add_point_2d(1, rdx, rdy, workplane)
        target_start = slvs.add_point_2d(1, 0.0, 0.0, workplane)
        target_end = slvs.add_point_2d(2, tdx, tdy, workplane)
        ref_line = slvs.add_line_2d(1, ref_start, ref_end, workplane)
        target_line = slvs.add_line_2d(2, target_start, target_end, workplane)
        slvs.distance(2, target_start, target_end, length, workplane)
        if kind == "parallel":
            slvs.parallel(2, target_line, ref_line, workplane)
        else:
            slvs.perpendicular(2, target_line, ref_line, workplane)
        result, failed = slvs.solve_sketch(2, True)
        sx, sy = _slvs_point(slvs, target_end)
        _rotate(target, math.atan2(sy, sx) - math.atan2(tdy, tdx))
    elif kind == "equal_radius":
        if target.get("type") not in {"circle", "arc"} or reference.get("type") not in {"circle", "arc"}:
            raise ValueError("equal_radius requires circles or arcs")
        ref_start = slvs.add_point_2d(1, 0.0, 0.0, workplane)
        ref_end = slvs.add_point_2d(1, float(reference["radius"]), 0.0, workplane)
        target_start = slvs.add_point_2d(1, 0.0, 10.0, workplane)
        target_end = slvs.add_point_2d(2, float(target["radius"]), 10.0, workplane)
        ref_line = slvs.add_line_2d(1, ref_start, ref_end, workplane)
        target_line = slvs.add_line_2d(2, target_start, target_end, workplane)
        slvs.equal(2, target_line, ref_line, workplane)
        result, failed = slvs.solve_sketch(2, True)
        sx, sy = _slvs_point(slvs, target_end)
        target["radius"] = math.hypot(sx, sy - 10.0)
    else:
        raise ValueError(f"unsupported SolveSpace constraint: {kind}")
    flag = int(result.get("result", -1))
    if flag not in {int(slvs.ResultFlag.OKAY), int(slvs.ResultFlag.REDUNDANT_OKAY)}:
        raise RuntimeError(f"SolveSpace solve failed: flag={flag}, failed={failed}")
    return {
        "status": "solved" if flag == int(slvs.ResultFlag.OKAY) else "redundant_okay",
        "degrees_of_freedom": int(result.get("dof", 0)),
        "failed_constraint_handles": [int(value) for value in failed],
    }


def run(payload: dict[str, Any]) -> dict[str, Any]:
    backend = str(payload["backend"])
    geometries = deepcopy(payload["geometries"])
    symbol_table = payload["symbol_table"]
    reports: list[dict[str, Any]] = []
    for constraint in payload["constraints"]:
        kind = str(constraint["kind"])
        if kind == "equal_size":
            target = _geometry_by_ref(
                geometries, symbol_table, str(constraint["target_ref"]),
            )
            reference = _geometry_by_ref(
                geometries, symbol_table, str(constraint["reference_ref"]),
            )
            target_width, target_height = _size(target)
            reference_width, reference_height = _size(reference)
            if target_width <= 0 or target_height <= 0:
                raise ValueError("equal-size target is degenerate")
            _scale(
                target,
                reference_width / target_width,
                reference_height / target_height,
            )
            reports.append({
                "constraint_id": constraint["constraint_id"],
                "status": "builtin_fallback",
                "reason": "native backends do not expose a generic bounding-box equal-size primitive",
            })
            continue
        target = _geometry_by_ref(geometries, symbol_table, str(constraint["target_ref"]))
        reference = _geometry_by_ref(geometries, symbol_table, str(constraint["reference_ref"]))
        distance = float(constraint.get("distance", 0.0)) * float(payload["unit_scale"])
        if backend == "planegcs":
            report = _planegcs_pair(kind, target, reference, distance)
        elif backend == "solvespace":
            report = _solvespace_pair(kind, target, reference, distance)
        else:
            raise ValueError(f"unknown native backend: {backend}")
        reports.append({"constraint_id": constraint["constraint_id"], **report})
    return {
        "schema": "cad.native-constraint-result.v1",
        "backend": backend,
        "geometries": geometries,
        "constraints": reports,
    }


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        json.dump(run(payload), sys.stdout, ensure_ascii=False, separators=(",", ":"))
        return 0
    except Exception as exc:
        json.dump({
            "schema": "cad.native-constraint-error.v1",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }, sys.stdout, ensure_ascii=False, separators=(",", ":"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
