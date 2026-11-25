"""Deterministic geometric-constraint solving for construction candidates.

The module is an adapter boundary: construction code depends on this API, not
on a specific native solver.  The built-in backend handles the small, explicit
constraint set used by the current PoC.  PlaneGCS and SolveSpace availability
is reported truthfully so a future native adapter can replace the backend
without changing the construction plan schema.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .cad_plan_references import REFERENCE_DESCRIPTION


class ConstraintSolveError(ValueError):
    def __init__(self, code: str, message: str, *, constraint_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.constraint_id = constraint_id
        self.category = ('solver_failed' if code.startswith('constraint_backend_')
                         else 'constraint_unsatisfied' if code == 'constraint_residual_exceeded' else code)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _BinaryConstraint(_StrictModel):
    constraint_id: str = Field(min_length=1, max_length=64)
    target_ref: str = Field(min_length=1, max_length=256, description=REFERENCE_DESCRIPTION + '约束目标必须恰含一个图元；仅目标可变。')
    reference_ref: str = Field(min_length=1, max_length=256, description=REFERENCE_DESCRIPTION + '约束参考必须恰含一个图元。')
    tolerance: float = Field(default=0.001, gt=0.0, le=1000.0)

    @model_validator(mode="after")
    def distinct_references(self) -> "_BinaryConstraint":
        if self.target_ref == self.reference_ref:
            raise ValueError("target_ref and reference_ref must differ")
        return self


class ConcentricConstraint(_BinaryConstraint):
    kind: Literal["concentric"]


class ParallelConstraint(_BinaryConstraint):
    kind: Literal["parallel"]
    angle_tolerance_deg: float = Field(default=0.01, gt=0.0, le=45.0)


class PerpendicularConstraint(_BinaryConstraint):
    kind: Literal["perpendicular"]
    angle_tolerance_deg: float = Field(default=0.01, gt=0.0, le=45.0)


class EqualRadiusConstraint(_BinaryConstraint):
    kind: Literal["equal_radius"]


class EqualSizeConstraint(_BinaryConstraint):
    kind: Literal["equal_size"]


class CenterDistanceConstraint(_BinaryConstraint):
    kind: Literal["center_distance"]
    distance: float = Field(ge=0.0, le=100000.0,
        description='约束使用图元固有center（圆、圆弧、椭圆），其他图元使用坐标外包框中心；按plan.units计。与center_distance断言的集合外包框中心定义不同。')


class EndpointCoincidentConstraint(_BinaryConstraint):
    """Rigidly translate one open primitive to an explicitly selected endpoint."""
    kind: Literal['endpoint_coincident'] = Field(description='仅builtin；只平移单一目标，保留长度、半径、方向，参考不变；不保证相切或其他关系。')
    target_endpoint: Literal['start', 'end']
    reference_endpoint: Literal['start', 'end']


ConstructionConstraint = Annotated[
    Union[
        ConcentricConstraint,
        ParallelConstraint,
        PerpendicularConstraint,
        EqualRadiusConstraint,
        EqualSizeConstraint,
        CenterDistanceConstraint,
        EndpointCoincidentConstraint,
    ],
    Field(discriminator="kind"),
]


def available_constraint_backends() -> dict[str, dict[str, Any]]:
    """Report native solver availability and its actual adapter transport."""
    solvespace = shutil.which("solvespace") or shutil.which("SolveSpace")
    py_slvs = importlib.util.find_spec("slvs") is not None
    py_planegcs = importlib.util.find_spec("planegcs") is not None
    solvespace_python = os.getenv("XLINE_SOLVESPACE_PYTHON", "").strip()
    planegcs_python = os.getenv("XLINE_PLANEGCS_PYTHON", "").strip()
    return {
        "builtin": {"available": True, "executable": None, "transport": "in_process"},
        "solvespace": {
            "available": bool(py_slvs or (solvespace_python and Path(solvespace_python).is_file())),
            "executable": solvespace_python or (sys.executable if py_slvs else solvespace),
            "transport": "isolated_python_worker",
            "package": "slvs",
        },
        "planegcs": {
            "available": bool(py_planegcs or (planegcs_python and Path(planegcs_python).is_file())),
            "executable": planegcs_python or (sys.executable if py_planegcs else None),
            "transport": "isolated_python_worker",
            "package": "planegcs",
        },
    }


def solve_geometric_constraints(
    geometries: list[dict[str, Any]],
    symbol_table: dict[str, list[int]],
    constraints: list[ConstructionConstraint],
    *,
    unit_scale: float,
    backend: Literal["auto", "builtin", "solvespace", "planegcs"] = "auto",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Solve constraints and verify residuals on an isolated geometry copy."""
    capabilities = available_constraint_backends()
    requested = backend
    auto_preference = os.getenv("XLINE_CONSTRAINT_BACKEND_AUTO", "builtin").strip().lower()
    if auto_preference not in {"builtin", "solvespace", "planegcs"}:
        auto_preference = "builtin"
    selected = auto_preference if backend == "auto" else backend
    if selected != "builtin" and not capabilities[selected]["available"]:
        raise ConstraintSolveError(
            "constraint_backend_unavailable",
            f"约束求解后端 {selected} 当前不可用",
        )

    for constraint in constraints:
        target = _single_geometry(geometries, symbol_table, constraint.target_ref, constraint.constraint_id)
        reference = _single_geometry(geometries, symbol_table, constraint.reference_ref, constraint.constraint_id)
        if target['id'] == reference['id']:
            raise ConstraintSolveError('constraint_overlapping_references',
                '目标与参考引用了同一图元，不能通过不同别名施加自引用约束', constraint_id=constraint.constraint_id)
        if isinstance(constraint, EndpointCoincidentConstraint):
            if selected != 'builtin':
                raise ConstraintSolveError('constraint_backend_kind_unsupported',
                    '端点重合目前只由builtin后端执行；未调用原生后端或隐式回退', constraint_id=constraint.constraint_id)
            _endpoint(target, constraint.target_endpoint, constraint.constraint_id)
            _endpoint(reference, constraint.reference_endpoint, constraint.constraint_id)

    # A bounding box midpoint of an open path is not a concentric centre.
    # Validate before either native or built-in solving can move any geometry.
    for constraint in constraints:
        if isinstance(constraint, ConcentricConstraint):
            for ref in (constraint.target_ref,constraint.reference_ref):
                g=_single_geometry(geometries,symbol_table,ref,constraint.constraint_id)
                if g.get('type')=='line' or (g.get('type') in {'polyline','spline'} and not g.get('closed')):
                    error=ConstraintSolveError('constraint_geometry_type_unsupported',
                        f'同心约束不能绑定开放路径 {ref} 的外包框中心；请引用实际圆/圆弧或闭合对象。',constraint_id=constraint.constraint_id)
                    error.details={'affected_output_refs':[constraint.target_ref,constraint.reference_ref],
                        'inapplicable_constraint':constraint.model_dump(mode='json'),
                        'repair_instruction':'修正模型自拟约束的对象范围，不得把开放曲线路径的外包框中心当成局部圆弧圆心；保留来源要求并重新验证。'}
                    raise error
    solved = deepcopy(geometries)
    native_report: dict[str, Any] | None = None
    fallback_ids: list[str] = []
    if selected == "builtin":
        for constraint in constraints:
            target = _single_geometry(solved, symbol_table, constraint.target_ref, constraint.constraint_id)
            reference = _single_geometry(
                solved, symbol_table, constraint.reference_ref, constraint.constraint_id,
            )
            _apply_constraint(target, reference, constraint, unit_scale)
    else:
        # Generic equal-size is a CAD-IR bounds operation, not a primitive
        # exposed by either native sketch solver. Keep that operation explicit
        # and report the hybrid fallback instead of pretending it was native.
        for constraint in constraints:
            if isinstance(constraint, EqualSizeConstraint):
                fallback_ids.append(constraint.constraint_id)
        before_native = deepcopy(solved)
        native_result = _run_native_solver(
            selected,
            solved,
            symbol_table,
            constraints,
            unit_scale=unit_scale,
            executable=str(capabilities[selected]["executable"]),
        )
        solved = native_result["geometries"]
        _verify_native_scope(before_native, solved, symbol_table, constraints)
        native_report = {
            key: value for key, value in native_result.items() if key != "geometries"
        }

    reports: list[dict[str, Any]] = []
    for constraint in constraints:
        target = _single_geometry(solved, symbol_table, constraint.target_ref, constraint.constraint_id)
        reference = _single_geometry(
            solved, symbol_table, constraint.reference_ref, constraint.constraint_id,
        )
        residual, metric = _constraint_residual(target, reference, constraint, unit_scale)
        tolerance = (
            constraint.angle_tolerance_deg
            if isinstance(constraint, (ParallelConstraint, PerpendicularConstraint))
            else constraint.tolerance * unit_scale
        )
        verified = math.isfinite(residual) and residual <= tolerance
        reports.append({
            "constraint_id": constraint.constraint_id,
            "kind": constraint.kind,
            "target_ref": constraint.target_ref,
            "reference_ref": constraint.reference_ref,
            "verified": verified,
            "residual": round(residual, 9),
            "tolerance": round(tolerance, 9),
            "metric": metric,
        })
    failures = [item for item in reports if not item['verified']]
    if failures:
        error = ConstraintSolveError(
            'constraint_residual_exceeded',
            '最终几何未同时满足约束：' + ', '.join(item['constraint_id'] for item in failures),
            constraint_id=failures[0]['constraint_id'],
        )
        # Sequential failure is not proof of mathematical infeasibility.
        error.category = 'constraint_unsatisfied'
        error.reports = deepcopy(reports)
        error.failed_constraints = deepcopy(failures)
        raise error
    return solved, {
        "schema": "cad.constraint-solve.v1",
        "requested_backend": requested,
        "backend": selected,
        "external_backends": capabilities,
        "verified": all(item["verified"] for item in reports),
        "constraint_count": len(reports),
        "constraints": reports,
        "native_result": native_report,
        "builtin_fallback_constraint_ids": fallback_ids,
        "geometry_is_authoritative": True,
    }


def _run_native_solver(
    backend: Literal["solvespace", "planegcs"],
    geometries: list[dict[str, Any]],
    symbol_table: dict[str, list[int]],
    constraints: list[ConstructionConstraint],
    *,
    unit_scale: float,
    executable: str,
) -> dict[str, Any]:
    timeout_seconds = float(os.getenv("XLINE_NATIVE_SOLVER_TIMEOUT_SECONDS", "8"))
    timeout_seconds = min(60.0, max(0.5, timeout_seconds))
    payload = {
        "schema": "cad.native-constraint-request.v1",
        "backend": backend,
        "geometries": geometries,
        "symbol_table": symbol_table,
        "constraints": [item.model_dump(mode="json") for item in constraints],
        "unit_scale": unit_scale,
    }
    try:
        completed = subprocess.run(
            [executable, "-m", "app.native_constraint_worker"],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(Path(__file__).resolve().parents[1]),
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ConstraintSolveError(
            "constraint_backend_timeout",
            f"约束求解后端 {backend} 超过 {timeout_seconds:g} 秒未返回",
        ) from exc
    except OSError as exc:
        raise ConstraintSolveError(
            "constraint_backend_start_failed",
            f"无法启动约束求解后端 {backend}：{exc}",
        ) from exc
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        detail = completed.stderr.strip()[-500:]
        raise ConstraintSolveError(
            "constraint_backend_invalid_response",
            f"约束求解后端 {backend} 返回了无效结果：{detail or '非 JSON 输出'}",
        ) from exc
    if completed.returncode != 0 or result.get("schema") != "cad.native-constraint-result.v1":
        message = str(result.get("message") or completed.stderr.strip() or "原生求解失败")
        raise ConstraintSolveError(
            "constraint_backend_failed",
            f"约束求解后端 {backend} 失败：{message}",
        )
    output = result.get("geometries")
    if not isinstance(output, list) or len(output) != len(geometries):
        raise ConstraintSolveError(
            "constraint_backend_invalid_response",
            f"约束求解后端 {backend} 未返回完整图元集合",
        )
    return result


def _verify_native_scope(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    symbol_table: dict[str, list[int]],
    constraints: list[ConstructionConstraint],
) -> None:
    target_ids = {
        int(geometry_id)
        for constraint in constraints
        for geometry_id in symbol_table.get(constraint.target_ref, [])
    }
    before_by_id = {int(item.get("id", -1)): item for item in before}
    after_by_id = {int(item.get("id", -1)): item for item in after}
    if set(before_by_id) != set(after_by_id):
        raise ConstraintSolveError(
            "constraint_backend_scope_violation", "原生求解器改变了图元集合",
        )
    for geometry_id, source in before_by_id.items():
        if geometry_id not in target_ids and after_by_id[geometry_id] != source:
            raise ConstraintSolveError(
                "constraint_backend_scope_violation",
                f"原生求解器越界修改了非目标图元 {geometry_id}",
            )


def _single_geometry(
    geometries: list[dict[str, Any]], refs: dict[str, list[int]],
    output_ref: str, constraint_id: str,
) -> dict[str, Any]:
    ids = refs.get(output_ref)
    if not ids:
        raise ConstraintSolveError(
            "constraint_unknown_reference",
            f"约束引用不存在：{output_ref}",
            constraint_id=constraint_id,
        )
    if len(ids) != 1:
        error = ConstraintSolveError(
            "constraint_requires_single_geometry",
            f"约束引用 {output_ref} 包含 {len(ids)} 个图元，当前约束要求单图元",
            constraint_id=constraint_id,
        )
        error.details = {'reference': output_ref, 'geometry_ids': list(ids),
                         'required_cardinality': 1, 'actual_cardinality': len(ids),
                         'repair_instruction': '当前约束只接受单图元；请引用明确部件，不得从整体中任取一个图元或删除其余部件。'}
        raise error
    geometry_id = int(ids[0])
    for geometry in geometries:
        if int(geometry.get("id", -1)) == geometry_id:
            return geometry
    raise ConstraintSolveError(
        "constraint_geometry_missing",
        f"约束引用 {output_ref} 对应图元不存在",
        constraint_id=constraint_id,
    )


def _apply_constraint(
    target: dict[str, Any], reference: dict[str, Any],
    constraint: ConstructionConstraint, unit_scale: float,
) -> None:
    if isinstance(constraint, EndpointCoincidentConstraint):
        tx, ty = _endpoint(target, constraint.target_endpoint, constraint.constraint_id)
        rx, ry = _endpoint(reference, constraint.reference_endpoint, constraint.constraint_id)
        _translate(target, rx-tx, ry-ty)
        return
    if isinstance(constraint, ConcentricConstraint):
        tx, ty = _center(target)
        rx, ry = _center(reference)
        _translate(target, rx - tx, ry - ty)
        return
    if isinstance(constraint, (ParallelConstraint, PerpendicularConstraint)):
        target_angle = _direction_angle(target)
        reference_angle = _direction_angle(reference)
        desired = reference_angle + (math.pi / 2 if isinstance(constraint, PerpendicularConstraint) else 0.0)
        _rotate(target, _normalize_signed_angle(desired - target_angle))
        return
    if isinstance(constraint, EqualRadiusConstraint):
        if target.get("type") not in {"circle", "arc"} or reference.get("type") not in {"circle", "arc"}:
            raise ConstraintSolveError(
                "constraint_geometry_type_unsupported",
                "等半径约束只支持圆或圆弧",
                constraint_id=constraint.constraint_id,
            )
        target["radius"] = float(reference["radius"])
        return
    if isinstance(constraint, EqualSizeConstraint):
        tw, th = _size(target)
        rw, rh = _size(reference)
        if tw <= 0 or th <= 0:
            raise ConstraintSolveError(
                "constraint_degenerate_geometry",
                "目标图元尺寸为零，无法应用等尺寸约束",
                constraint_id=constraint.constraint_id,
            )
        _scale(target, rw / tw, rh / th)
        return
    if isinstance(constraint, CenterDistanceConstraint):
        tx, ty = _center(target)
        rx, ry = _center(reference)
        dx, dy = tx - rx, ty - ry
        length = math.hypot(dx, dy)
        ux, uy = ((1.0, 0.0) if length <= 1e-12 else (dx / length, dy / length))
        distance = constraint.distance * unit_scale
        _translate(target, rx + ux * distance - tx, ry + uy * distance - ty)
        return
    raise ConstraintSolveError(
        "constraint_kind_unsupported", f"不支持约束 {constraint.kind}",
        constraint_id=constraint.constraint_id,
    )


def _constraint_residual(
    target: dict[str, Any], reference: dict[str, Any],
    constraint: ConstructionConstraint, unit_scale: float,
) -> tuple[float, str]:
    if isinstance(constraint, EndpointCoincidentConstraint):
        return math.dist(_endpoint(target, constraint.target_endpoint, constraint.constraint_id),
                         _endpoint(reference, constraint.reference_endpoint, constraint.constraint_id)), 'endpoint_distance_mm'
    if isinstance(constraint, ConcentricConstraint):
        tx, ty = _center(target); rx, ry = _center(reference)
        return math.hypot(tx - rx, ty - ry), "distance_mm"
    if isinstance(constraint, (ParallelConstraint, PerpendicularConstraint)):
        delta = abs(math.degrees(_normalize_signed_angle(
            _direction_angle(target) - _direction_angle(reference)
        )))
        delta = min(delta, abs(180.0 - delta))
        expected = 90.0 if isinstance(constraint, PerpendicularConstraint) else 0.0
        return abs(delta - expected), "angle_deg"
    if isinstance(constraint, EqualRadiusConstraint):
        return abs(float(target["radius"]) - float(reference["radius"])), "radius_delta_mm"
    if isinstance(constraint, EqualSizeConstraint):
        tw, th = _size(target); rw, rh = _size(reference)
        return max(abs(tw - rw), abs(th - rh)), "bounds_delta_mm"
    if isinstance(constraint, CenterDistanceConstraint):
        tx, ty = _center(target); rx, ry = _center(reference)
        return abs(math.hypot(tx - rx, ty - ry) - constraint.distance * unit_scale), "distance_delta_mm"
    return math.inf, "unsupported"


def _endpoint(geometry, selector, constraint_id):
    kind = geometry.get('type')
    if kind == 'line':
        point = geometry[selector]
    elif kind == 'polyline' and not geometry.get('closed') and len(geometry.get('vertices', [])) >= 2:
        point = geometry['vertices'][0 if selector == 'start' else -1]
    elif kind == 'arc':
        delta = float(geometry['end_angle']) - float(geometry['start_angle'])
        if abs(delta % 360) < 1e-9:
            raise ConstraintSolveError('constraint_geometry_type_unsupported',
                '零扫角或整圆没有唯一开放端点', constraint_id=constraint_id)
        angle = math.radians(float(geometry[selector + '_angle']))
        return (float(geometry['center']['x']) + float(geometry['radius'])*math.cos(angle),
                float(geometry['center']['y']) + float(geometry['radius'])*math.sin(angle))
    else:
        raise ConstraintSolveError('constraint_geometry_type_unsupported',
            '端点重合只支持直线、开放多段线和非整圆圆弧；不猜测圆或闭合对象的端点', constraint_id=constraint_id)
    return float(point['x']), float(point['y'])


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
    if not points:
        raise ConstraintSolveError("constraint_geometry_type_unsupported", "图元没有可求中心的坐标")
    xs = [float(item["x"]) for item in points]
    ys = [float(item["y"]) for item in points]
    return (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0


def _size(geometry: dict[str, Any]) -> tuple[float, float]:
    if geometry.get("type") in {"circle", "arc"}:
        diameter = 2.0 * float(geometry["radius"])
        return diameter, diameter
    points = _points(geometry)
    xs = [float(item["x"]) for item in points]
    ys = [float(item["y"]) for item in points]
    return max(xs) - min(xs), max(ys) - min(ys)


def _direction_angle(geometry: dict[str, Any]) -> float:
    if geometry.get("type") == "line":
        start, end = geometry["start"], geometry["end"]
    elif geometry.get("type") == "polyline" and len(geometry.get("vertices") or []) >= 2:
        start, end = geometry["vertices"][0], geometry["vertices"][1]
    elif geometry.get("type") == "ellipse" and isinstance(geometry.get("major_axis"), dict):
        axis = geometry["major_axis"]
        return math.atan2(float(axis["y"]), float(axis["x"]))
    else:
        raise ConstraintSolveError(
            "constraint_geometry_type_unsupported", "平行/垂直约束需要线性方向图元",
        )
    return math.atan2(float(end["y"]) - float(start["y"]), float(end["x"]) - float(start["x"]))


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
            raise ConstraintSolveError(
                "constraint_geometry_type_unsupported", "圆形等尺寸约束要求等比例缩放",
            )
        geometry["radius"] = float(geometry["radius"]) * sx
        return
    for point in _points(geometry):
        point["x"] = cx + (float(point["x"]) - cx) * sx
        point["y"] = cy + (float(point["y"]) - cy) * sy


def _normalize_signed_angle(value: float) -> float:
    return (value + math.pi) % (2.0 * math.pi) - math.pi
