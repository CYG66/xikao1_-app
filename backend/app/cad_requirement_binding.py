"""Bind ordinary construction clauses to actual objects and measurements.

The coverage builder in :mod:`app.cad_source_acceptance` deliberately refuses
to promote a dimension fact without an independent measurement.  This module
supplies the missing link for ordinary construction commands: a source clause
that names exactly one geometric object kind is bound to that unique backend
logical object, and the existing geometry is measured again.  It never infers
an object from a dimension, never selects by expected size, and never turns a
reviewable draft into a formal pass when the binding is absent or ambiguous.
"""
from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any

from .cad_geometric_predicates import (
    closure_measure,
    corner_circle_collection,
    heart_cusp_points,
    heart_outline_measure,
    measure_geometry,
    mirror_symmetry,
    outline_points,
    rectangle_measure,
)

_TOLERANCE_MM = 0.5

_SHAPE_WORDS = (
    ("heart", re.compile(r"爱心|心形")),
    ("outline", re.compile(r"(?<!图)轮廓|外形|外廓")),
    ("rectangle", re.compile(r"矩形|长方形|方形")),
    ("circle", re.compile(r"圆形|圆(?!心|弧|周|形)")),
    ("arc", re.compile(r"圆弧|弧线|弧")),
    ("line", re.compile(r"线段|直线|一条线")),
)
_DIMENSION_WORDS = re.compile(
    r"宽|高|长|半径|直径|边长|周长|面积|尺寸|外径|内径"
)
_OPERATION_WORDS = re.compile(r"新建|创建|生成.*图纸|画.*图纸")
_DRAWING_WORDS = re.compile(r"图纸")
_NEGATED_OR_EDIT = re.compile(r"不要|不需要|无需|禁止|别|取消|删除|移除|去掉|修改|编辑|移动|旋转|缩放")
_CORNER_PLACEMENT = re.compile(r"(?:四个|4\s*个|四)\s*(?:个)?\s*(?:角|角点)|四角|各个角")
_UNSUPPORTED_OUTLINE_PROPERTY = re.compile(
    r"花瓣|齿轮|齿形|齿|开孔|孔洞|镂空|内孔|阵列|网格"
)
_CN_NUMBER = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_SYMMETRY_UNSUPPORTED = re.compile(
    r"旋转对称|中心对称|上下对称|上下镜像|前后对称|关于\s*[xX]\s*轴|关于横轴"
)
_SYMMETRY_VERTICAL = re.compile(r"左右对称|镜像对称|关于\s*[yY]\s*轴|竖直|垂直")
_SYMMETRY_EXPLICIT_X = re.compile(
    r"关于\s*[xX]\s*=\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE
)


def _mirror_axis_from_source(requirement: str,
                             measured_center_x: float
                             ) -> tuple[float, str] | None:
    """Return a supported vertical mirror axis and its source.

    A bare ``对称`` is ambiguous: it could mean rotation, centre symmetry or a
    horizontal axis.  Only an explicit left/right (vertical-line) statement is
    measured.  When the source gives an explicit ``x=...`` line, that value is
    used; otherwise the vertical line through the measured outline centre is
    recorded explicitly as an inferred location.
    """
    if _SYMMETRY_UNSUPPORTED.search(requirement):
        return None
    explicit = _SYMMETRY_EXPLICIT_X.search(requirement)
    if explicit:
        return float(explicit.group(1)), "source:explicit_x_equals"
    if _SYMMETRY_VERTICAL.search(requirement):
        return float(measured_center_x), "source:left_right_measured_center"
    return None


def bind_construction_coverage(
    coverage: dict[str, Any] | None,
    *,
    logical_objects: list[dict[str, Any]] | None = None,
    geometries: list[dict[str, Any]] | None = None,
    plan_steps: list[dict[str, Any]] | None = None,
    symbol_table: dict[str, list[int]] | None = None,
    project_evidence: dict[str, Any] | None = None,
    tolerance_mm: float = _TOLERANCE_MM,
) -> dict[str, Any]:
    """Return coverage with only independently provable clauses promoted.

    ``project_evidence`` must describe a project record that exists in the
    production store.  A missing or empty record is not evidence.  Geometry is
    measured from the backend output, not from a plan's requested dimensions.
    """
    if not isinstance(coverage, dict):
        return coverage or {}
    result = deepcopy(coverage)
    objects = [item for item in (logical_objects or []) if isinstance(item, dict)]
    geoms = [item for item in (geometries or []) if isinstance(item, dict)]
    steps = [item for item in (plan_steps or []) if isinstance(item, dict)]
    symbols = symbol_table if isinstance(symbol_table, dict) else {}
    bound_clause_ids: list[str] = []
    bound_fact_ids: list[str] = []

    for clause in result.get("clauses") or []:
        if not isinstance(clause, dict):
            continue
        if clause.get("status") == "verified":
            continue
        requirement = str(clause.get("requirement") or "").strip()
        if not requirement:
            continue
        if _NEGATED_OR_EDIT.search(requirement):
            # The binder proves creation/existence, never a negated or edit
            # instruction.  Such clauses need their own executor evidence.
            continue

        op_binding = _operation_binding(requirement, project_evidence)
        if op_binding is not None:
            _promote_clause(clause, op_binding, bound_clause_ids)
            if op_binding.get("requirement_id"):
                bound_fact_ids.append(str(op_binding["requirement_id"]))
            continue

        kind = _clause_shape_kind(requirement)
        if kind is None:
            continue
        if _DIMENSION_WORDS.search(requirement) and not (clause.get("unsupported_evidence") or []):
            # A dimension requirement without a contract fact is not provable
            # here; leave the original unverified state intact.
            continue
        candidates = [
            item for item in objects if _object_kind(item, geoms) == kind
        ]
        if not candidates:
            continue
        if kind in {"heart", "outline"}:
            _bind_outline_clause(
                clause, requirement, candidates, geoms, steps, symbols,
                bound_clause_ids, bound_fact_ids, tolerance_mm,
            )
            continue
        expected_circle_count = _expected_circle_count(requirement)
        corner_placement = bool(_CORNER_PLACEMENT.search(requirement))
        if kind == "circle" and (
            corner_placement
            or expected_circle_count not in (None, 1)
        ):
            _bind_circle_collection(
                clause, requirement, candidates, objects, geoms, steps, symbols,
                bound_clause_ids, bound_fact_ids, tolerance_mm,
                expected_circle_count, corner_placement,
            )
            continue
        if len(candidates) != 1:
            continue
        obj = candidates[0]
        refs = [int(value) for value in (obj.get("geometry_refs") or []) if isinstance(value, int)]
        if not refs:
            continue
        measured = [item for item in geoms if item.get("id") in refs]
        if len(measured) != len(refs):
            continue
        measurement = _measure_objects(measured)
        if measurement is None:
            continue
        step_binding = _unique_step_binding(refs, steps, symbols, obj)
        if step_binding is None:
            continue

        facts = [item for item in (clause.get("unsupported_evidence") or [])
                 if isinstance(item, dict)]
        evidence_items = []
        failures = []
        for fact in facts:
            field = str(fact.get("field") or "").lower()
            expected = _number(fact.get("expected_mm"))
            actual = _actual_field(measurement, field)
            if expected is None or actual is None:
                failures.append({
                    "requirement_id": fact.get("requirement_id"),
                    "field": field,
                    "reason": "该尺寸没有对应的后端几何测量",
                })
                continue
            delta = abs(actual - expected)
            passed = delta <= float(tolerance_mm)
            if not passed:
                failures.append({
                    "requirement_id": fact.get("requirement_id"),
                    "field": field,
                    "expected_mm": expected,
                    "actual_mm": actual,
                    "delta_mm": delta,
                    "reason": "独立测量与来源要求冲突",
                })
            evidence_items.append({
                "requirement_id": fact.get("requirement_id") or clause.get("requirement_id"),
                "verifier": "bind_construction_measurement",
                "status": "verified" if passed else "failed",
                "measurement": {
                    "field": field,
                    "actual_mm": actual,
                    "expected_mm": expected,
                    "delta_mm": delta,
                    "tolerance_mm": float(tolerance_mm),
                    "logical_object_id": obj.get("object_id"),
                    "object_type": obj.get("object_type"),
                    "geometry_ids": list(refs),
                    "step_id": step_binding.get("step_id"),
                    "output_ref": step_binding.get("output_ref"),
                    "authority": "backend_measured_geometry",
                },
            })

        if failures:
            _record_failure(clause, failures, evidence_items)
            continue
        if not facts:
            # A shape-only clause can be bound to exactly one measured object
            # of the named kind.  It proves existence and kind, not a size.
            evidence_items.append({
                "requirement_id": clause.get("requirement_id"),
                "verifier": "bind_construction_measurement",
                "status": "verified",
                "measurement": {
                    "kind": kind,
                    "logical_object_id": obj.get("object_id"),
                    "object_type": obj.get("object_type"),
                    "geometry_ids": list(refs),
                    "step_id": step_binding.get("step_id"),
                    "output_ref": step_binding.get("output_ref"),
                    "authority": "backend_measured_geometry",
                },
            })

        binding = {
            "schema": "cad.requirement-binding.v1",
            "requirement_id": clause.get("requirement_id"),
            "kind": kind,
            "logical_object_id": obj.get("object_id"),
            "object_type": obj.get("object_type"),
            "geometry_ids": list(refs),
            "step_id": step_binding.get("step_id"),
            "output_ref": step_binding.get("output_ref"),
            "measurement": deepcopy(measurement),
            "evidence": deepcopy(evidence_items),
            "resolved_unsupported_evidence": deepcopy(facts),
            "authority": "backend_measured_geometry",
        }
        _promote_clause(clause, binding, bound_clause_ids)
        bound_fact_ids.extend(
            str(item.get("requirement_id")) for item in facts
            if item.get("requirement_id")
        )

    result.setdefault("binding", {})
    result["binding"] = {
        "schema": "cad.requirement-binding.v1",
        "bound_clause_ids": bound_clause_ids,
        "bound_fact_ids": bound_fact_ids,
        "tolerance_mm": float(tolerance_mm),
        "authority": "backend_measured_geometry",
    }
    # Recompute after the new binding is visible.  The previous order read the
    # pre-binding fact list, leaving resolved facts in the unresolved ledger.
    _recompute(result)
    return result


def unresolved_drawing_creation_requirements(coverage: dict[str, Any] | None) -> list[str]:
    """Return create-drawing clauses that still need this commit's write proof."""
    if not isinstance(coverage, dict):
        return []
    result: list[str] = []
    for clause in coverage.get("clauses") or []:
        if not isinstance(clause, dict) or clause.get("status") == "verified":
            continue
        requirement = str(clause.get("requirement") or "")
        if _DRAWING_WORDS.search(requirement) and _OPERATION_WORDS.search(requirement) \
                and _clause_shape_kind(requirement) is None:
            result.append(str(clause.get("requirement_id") or ""))
    return result


def _refs(obj: dict[str, Any]) -> list[int]:
    return [int(value) for value in (obj.get("geometry_refs") or [])
            if isinstance(value, int)]


def _expected_circle_count(text: str) -> int | None:
    """Parse an explicit collection size, never an object's radius number."""
    if _CORNER_PLACEMENT.search(text):
        return 4
    match = re.search(
        r"(?P<count>\d+|[一二两三四五六七八九十])\s*(?:个|只|颗)?\s*"
        r"(?:半径[^，,。；;\s]*\s*)?(?:的)?\s*圆",
        text,
    )
    if not match:
        return None
    token = match.group("count")
    return int(token) if token.isdigit() else _CN_NUMBER.get(token)


def _record_failure(clause: dict[str, Any], failures: list[dict[str, Any]],
                    evidence: list[dict[str, Any]] | None = None) -> None:
    clause["status"] = "partial"
    clause["reason"] = failures[0].get("reason") if failures else "独立测量未通过"
    clause["binding_failures"] = deepcopy(failures)
    if evidence:
        clause.setdefault("evidence", [])
        if not isinstance(clause["evidence"], list):
            clause["evidence"] = []
        clause["evidence"].extend(deepcopy(item) for item in evidence)


def _record_unverified(clause: dict[str, Any], reason: str,
                       measurement: dict[str, Any] | None = None) -> None:
    clause["status"] = "unverified"
    clause["reason"] = reason
    clause.setdefault("binding_gap", {})
    if measurement:
        clause["binding_gap"] = deepcopy(measurement)


def _step_binding_for_object(obj: dict[str, Any], refs: list[int],
                             steps: list[dict[str, Any]],
                             symbol_table: dict[str, list[int]]) -> dict[str, Any] | None:
    matches = []
    for step in steps:
        output_ref = str(step.get("output_ref") or "")
        symbol_refs = symbol_table.get(output_ref)
        if isinstance(symbol_refs, list) and set(refs).intersection(
            int(value) for value in symbol_refs if isinstance(value, int)
        ):
            matches.append(step)
    if len(matches) == 1:
        return matches[0]
    if not symbol_table:
        object_id = str(obj.get("object_id") or "")
        by_output = [step for step in steps
                     if object_id and str(step.get("output_ref") or "") == object_id]
        if len(by_output) == 1:
            return by_output[0]
    return None


def _bind_circle_collection(
    clause: dict[str, Any], requirement: str,
    candidates: list[dict[str, Any]], all_objects: list[dict[str, Any]],
    geometries: list[dict[str, Any]], steps: list[dict[str, Any]],
    symbol_table: dict[str, list[int]], bound_clause_ids: list[str],
    bound_fact_ids: list[str], tolerance_mm: float,
    expected_count: int | None, corner_placement: bool,
) -> None:
    """Bind a multi-circle clause without inventing positions or sizes."""
    circle_geometries, circle_refs, step_bindings = [], [], []
    for obj in candidates:
        refs = _refs(obj)
        selected = [item for item in geometries if item.get("id") in refs]
        if len(selected) != len(refs) or len(selected) != 1:
            _record_unverified(clause, "圆形对象的几何引用不是唯一实体")
            return
        circle_geometries.append(selected[0])
        circle_refs.extend(refs)
        step_binding = _step_binding_for_object(obj, refs, steps, symbol_table)
        if step_binding is None:
            _record_unverified(clause, "圆形对象缺少可追溯的构造步骤")
            return
        step_bindings.append(step_binding)

    facts = [item for item in (clause.get("unsupported_evidence") or [])
             if isinstance(item, dict)]
    expected_radius = None
    radius_field = None
    for fact in facts:
        field = str(fact.get("field") or "").lower()
        expected = _number(fact.get("expected_mm"))
        if field == "radius" and expected is not None:
            expected_radius, radius_field = expected, field
            break
        if field == "diameter" and expected is not None:
            expected_radius, radius_field = expected / 2.0, field
            break

    if corner_placement:
        rectangles = [item for item in all_objects
                      if _object_kind(item, geometries) == "rectangle"]
        if len(rectangles) != 1:
            _record_unverified(clause, "角点集合适配需要唯一可测量的矩形作为锚点", {
                "rectangle_candidate_count": len(rectangles),
                "circle_count": len(circle_geometries),
            })
            return
        rect_obj = rectangles[0]
        rect_refs = _refs(rect_obj)
        selected_rect = [item for item in geometries if item.get("id") in rect_refs]
        if len(selected_rect) != 1:
            _record_unverified(clause, "矩形锚点的几何引用不是唯一实体")
            return
        rect_binding = _step_binding_for_object(rect_obj, rect_refs, steps, symbol_table)
        if rect_binding is None:
            _record_unverified(clause, "矩形锚点缺少可追溯的构造步骤")
            return
        measurement = corner_circle_collection(
            selected_rect[0],
            circle_geometries,
            expected_count=expected_count if expected_count is not None else 4,
            corner_tolerance_mm=float(tolerance_mm),
            radius_tolerance_mm=float(tolerance_mm),
            expected_radius_mm=expected_radius,
        )
    else:
        measurement = _measure_circle_collection(
            circle_geometries, expected_count, expected_radius, tolerance_mm,
        )

    evidence = [{
        "requirement_id": clause.get("requirement_id"),
        "verifier": "bind_circle_collection_measurement",
        "status": measurement.get("status"),
        "measurement": deepcopy(measurement),
    }]
    for fact in facts:
        evidence.append({
            "requirement_id": fact.get("requirement_id") or clause.get("requirement_id"),
            "verifier": "bind_circle_collection_measurement",
            "status": measurement.get("status"),
            "measurement": {
                "field": str(fact.get("field") or "").lower(),
                "expected_mm": _number(fact.get("expected_mm")),
                "radius_field": radius_field,
                "circle_geometry_ids": measurement.get("circle_geometry_ids"),
                "tolerance_mm": float(tolerance_mm),
                "authority": "backend_measured_geometry",
            },
        })

    if measurement.get("status") != "verified":
        if measurement.get("status") == "failed":
            _record_failure(clause, [{
                "requirement_id": clause.get("requirement_id"),
                "reason": measurement.get("reason") or "圆形集合的独立测量与要求冲突",
                "measurement": measurement,
            }], evidence)
        else:
            _record_unverified(
                clause,
                measurement.get("reason") or "圆形集合缺少可测量的锚点",
                measurement,
            )
        return

    binding = {
        "schema": "cad.requirement-binding.v1",
        "requirement_id": clause.get("requirement_id"),
        "kind": "circle_collection",
        "geometry_ids": list(circle_refs),
        "step_id": ",".join(str(item.get("step_id")) for item in step_bindings),
        "output_ref": ",".join(str(item.get("output_ref")) for item in step_bindings),
        "measurement": deepcopy(measurement),
        "evidence": deepcopy(evidence),
        "resolved_unsupported_evidence": deepcopy(facts),
        "authority": "backend_measured_geometry",
    }
    _promote_clause(clause, binding, bound_clause_ids)
    bound_fact_ids.extend(
        str(item.get("requirement_id")) for item in facts
        if item.get("requirement_id")
    )


def _measure_circle_collection(
    circles: list[dict[str, Any]], expected_count: int | None,
    expected_radius: float | None, tolerance_mm: float,
) -> dict[str, Any]:
    measures = [measure_geometry(item) for item in circles]
    if any(item is None or item["kind"] != "circle" for item in measures):
        return {"status": "unverified", "reason": "集合中包含非圆几何"}
    if expected_count is not None and len(measures) != int(expected_count):
        return {
            "status": "failed",
            "reason": "圆形数量与来源要求冲突",
            "expected_count": int(expected_count),
            "actual_count": len(measures),
            "circle_geometry_ids": [item["geometry_id"] for item in measures],
        }
    mismatches = []
    if expected_radius is not None:
        for item in measures:
            delta = abs(item["radius_mm"] - expected_radius)
            if delta > tolerance_mm:
                mismatches.append({
                    "geometry_id": item["geometry_id"],
                    "actual_radius_mm": item["radius_mm"],
                    "expected_radius_mm": expected_radius,
                    "delta_mm": delta,
                })
    return {
        "status": "failed" if mismatches else "verified",
        "reason": "圆形半径与来源要求冲突" if mismatches else None,
        "expected_count": expected_count,
        "actual_count": len(measures),
        "circle_geometry_ids": [item["geometry_id"] for item in measures],
        "radius_mismatch": mismatches,
        "radius_tolerance_mm": tolerance_mm,
        "authority": "backend_measured_geometry",
    }


def _bind_outline_clause(
    clause: dict[str, Any], requirement: str,
    candidates: list[dict[str, Any]], geometries: list[dict[str, Any]],
    steps: list[dict[str, Any]], symbol_table: dict[str, list[int]],
    bound_clause_ids: list[str], bound_fact_ids: list[str],
    tolerance_mm: float,
) -> None:
    """Prove an outline clause only when every named property is measured."""
    if _UNSUPPORTED_OUTLINE_PROPERTY.search(requirement):
        _record_unverified(clause, "该轮廓属性尚无独立几何谓词", {
            "unsupported_property": _UNSUPPORTED_OUTLINE_PROPERTY.search(requirement).group(0),
        })
        return
    if len(candidates) != 1:
        _record_unverified(clause, "多个轮廓对象无法唯一绑定", {
            "candidate_count": len(candidates),
        })
        return
    obj = candidates[0]
    refs = _refs(obj)
    selected = [item for item in geometries if item.get("id") in refs]
    if len(selected) != 1 or len(refs) != 1:
        _record_unverified(clause, "轮廓对象的几何引用不是唯一实体")
        return
    step_binding = _step_binding_for_object(obj, refs, steps, symbol_table)
    if step_binding is None:
        _record_unverified(clause, "轮廓对象缺少可追溯的构造步骤")
        return
    geometry = selected[0]
    points = outline_points(geometry)
    if len(points) < 3:
        _record_unverified(clause, "轮廓顶点不足，无法测量整体属性")
        return

    facts = [item for item in (clause.get("unsupported_evidence") or [])
             if isinstance(item, dict)]
    checks: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    is_heart = bool(re.search(r"爱心|心形", requirement))
    wants_symmetry = bool(re.search(r"左右对称|镜像对称|对称", requirement))
    wants_closure = bool(re.search(r"平滑闭合|闭合|封闭", requirement))
    wants_smooth = bool(re.search(r"平滑|光滑", requirement))
    bounds = {
        "min_x": min(point[0] for point in points),
        "max_x": max(point[0] for point in points),
        "min_y": min(point[1] for point in points),
        "max_y": max(point[1] for point in points),
    }
    center_x = (bounds["min_x"] + bounds["max_x"]) / 2.0

    heart_verified = False
    if is_heart:
        heart = heart_outline_measure(geometry)
        heart_verified = heart.get("status") == "verified"
        checks.append({"predicate": "heart_features", **heart})
        if not heart_verified:
            failures.append({"predicate": "heart_features",
                             "reason": "心形拓扑特征未全部通过",
                             "measurement": heart})
    if wants_symmetry:
        axis = _mirror_axis_from_source(requirement, center_x)
        if axis is None:
            _record_unverified(
                clause,
                "对称方向或对称轴缺少明确来源，未按包围盒中心线猜测",
                {"requirement_text": requirement,
                 "supported": "仅支持来源明确的左右/镜像对称或显式 x= 轴"},
            )
            return
        axis_x, axis_source = axis
        symmetry = mirror_symmetry(
            points, axis_x, float(tolerance_mm), axis_source=axis_source,
        )
        checks.append({"predicate": "mirror_symmetry", **symmetry})
        if symmetry.get("status") != "verified":
            failures.append({"predicate": "mirror_symmetry",
                             "reason": "轮廓线段集合与镜像不重合",
                             "measurement": symmetry})
    if wants_closure or wants_smooth:
        closure = closure_measure(
            points,
            closed=geometry.get("closed") is True,
            tolerance_mm=float(tolerance_mm),
            require_smooth=wants_smooth,
            allowed_cusp_source=("heart_features" if heart_verified else None),
            allowed_cusp_limit=(2 if heart_verified else 0),
            allowed_cusp_points=(
                heart_cusp_points(geometry) if heart_verified else None
            ),
        )
        checks.append({"predicate": "closure", **closure})
        if closure.get("status") != "verified":
            failures.append({"predicate": "closure",
                             "reason": "实际未闭合或平滑连续性超过容限",
                             "measurement": closure})

    width_mm = bounds["max_x"] - bounds["min_x"]
    height_mm = bounds["max_y"] - bounds["min_y"]
    measurement: dict[str, Any] = {
        "kind": "outline",
        "geometry_id": geometry.get("id"),
        "vertex_count": len(points),
        "closed": geometry.get("closed") is True,
        "bounds": bounds,
        "width_mm": width_mm,
        "height_mm": height_mm,
        "center_mm": [center_x, (bounds["min_y"] + bounds["max_y"]) / 2.0],
        "checks": checks,
    }
    for fact in facts:
        field = str(fact.get("field") or "").lower()
        expected = _number(fact.get("expected_mm"))
        actual = _actual_field(measurement, field)
        if expected is None or actual is None:
            failures.append({"requirement_id": fact.get("requirement_id"),
                             "field": field,
                             "reason": "该轮廓尺寸没有对应的后端几何测量"})
            continue
        delta = abs(actual - expected)
        if delta > float(tolerance_mm):
            failures.append({
                "requirement_id": fact.get("requirement_id"),
                "field": field, "expected_mm": expected, "actual_mm": actual,
                "delta_mm": delta, "reason": "独立测量与来源要求冲突",
            })

    if not is_heart and not wants_symmetry and not wants_closure and not wants_smooth \
            and not facts:
        _record_unverified(clause, "通用轮廓未声明可测量的整体属性", measurement)
        return
    if failures:
        _record_failure(clause, failures, [{
            "requirement_id": clause.get("requirement_id"),
            "verifier": "bind_outline_measurement",
            "status": "failed",
            "measurement": measurement,
        }])
        return
    evidence = [{
        "requirement_id": clause.get("requirement_id"),
        "verifier": "bind_outline_measurement",
        "status": "verified",
        "measurement": deepcopy(measurement),
    }]
    binding = {
        "schema": "cad.requirement-binding.v1",
        "requirement_id": clause.get("requirement_id"),
        "kind": "heart_outline" if is_heart else "outline",
        "logical_object_id": obj.get("object_id"),
        "object_type": obj.get("object_type"),
        "geometry_ids": list(refs),
        "step_id": step_binding.get("step_id"),
        "output_ref": step_binding.get("output_ref"),
        "measurement": deepcopy(measurement),
        "evidence": deepcopy(evidence),
        "resolved_unsupported_evidence": deepcopy(facts),
        "authority": "backend_measured_geometry",
    }
    _promote_clause(clause, binding, bound_clause_ids)
    bound_fact_ids.extend(
        str(item.get("requirement_id")) for item in facts
        if item.get("requirement_id")
    )


def _operation_binding(requirement: str, project_evidence: dict[str, Any] | None) -> dict[str, Any] | None:
    if not _DRAWING_WORDS.search(requirement) or not _OPERATION_WORDS.search(requirement):
        return None
    if _clause_shape_kind(requirement) is not None:
        return None
    evidence = project_evidence if isinstance(project_evidence, dict) else {}
    if evidence.get("project_exists") is not True or not evidence.get("project_id"):
        return None
    # A project record alone proves a container, not a new drawing.  The
    # operation is proven only when this request actually writes the first
    # candidate into the project, or when the project itself was created by
    # the commit.  An existing project with prior candidates is a follow-up
    # candidate revision, not a "new drawing".
    created = evidence.get("created_in_this_commit") is True
    write_receipt = evidence.get("write_receipt")
    write_receipt = write_receipt if isinstance(write_receipt, dict) else {}
    receipt_proven = bool(
        write_receipt.get("created") is True
        and write_receipt.get("reused_existing") is False
        and write_receipt.get("authority")
        and str(write_receipt.get("project_id") or "") == str(evidence.get("project_id") or "")
        and str(write_receipt.get("variant_id") or "")
        and write_receipt.get("before_variant_count") is not None
        and int(write_receipt["before_variant_count"])
        == int(evidence.get("prior_variant_count") or 0)
        and write_receipt.get("after_variant_count") is not None
        and int(write_receipt["after_variant_count"])
        == int(evidence.get("prior_variant_count") or 0) + 1
        and int(write_receipt.get("superseded_count") or 0) == 0
    )
    first_write = bool(
        evidence.get("candidate_write_in_commit") is True
        and evidence.get("prior_variant_count") == 0
        and receipt_proven
    )
    if not created and not first_write:
        return None
    proof = "project_created_in_commit" if created else "first_candidate_write_in_commit"
    receipt_evidence = {
        "created": write_receipt.get("created"),
        "reused_existing": write_receipt.get("reused_existing"),
        "before_variant_count": write_receipt.get("before_variant_count"),
        "after_variant_count": write_receipt.get("after_variant_count"),
        "superseded_count": write_receipt.get("superseded_count"),
        "variant_id": write_receipt.get("variant_id"),
        "authority": write_receipt.get("authority"),
    } if receipt_proven else None
    return {
        "schema": "cad.requirement-binding.v1",
        "requirement_id": None,
        "kind": "operation",
        "operation": "create_drawing",
        "project_id": str(evidence["project_id"]),
        "project_status": evidence.get("project_status"),
        "project_created_in_commit": created,
        "prior_variant_count": evidence.get("prior_variant_count"),
        "drawing_write_proof": proof,
        "write_receipt": deepcopy(receipt_evidence),
        "project_store_authority": str(evidence.get("authority") or "creative_project_store"),
        "evidence": [{
            "requirement_id": None,
            "verifier": "verify_drawing_creation",
            "status": "verified",
            "measurement": {
                "operation": "create_drawing",
                "project_id": str(evidence["project_id"]),
                "project_status": evidence.get("project_status"),
                "project_created_in_commit": created,
                "prior_variant_count": evidence.get("prior_variant_count"),
                "drawing_write_proof": proof,
                "write_receipt": deepcopy(receipt_evidence),
                "authority": str(evidence.get("authority") or "creative_project_store"),
            },
        }],
        "authority": str(evidence.get("authority") or "creative_project_store"),
    }


def _clause_shape_kind(text: str) -> str | None:
    matches = [(kind, bool(pattern.search(text))) for kind, pattern in _SHAPE_WORDS]
    found = [kind for kind, matched in matches if matched]
    if len(found) != 1:
        return None
    return found[0]


def _object_kind(obj: dict[str, Any],
                 geometries: list[dict[str, Any]] | None = None) -> str | None:
    """Return the measured kind first, declared type only as a fallback.

    Production plans often emit ``object_type='drawing_part'`` even when the
    geometry is a circle or rectangle.  Selecting by the declared label alone
    loses that binding.  Measurement is authoritative when one referenced
    geometry exists; an unmeasurable polyline is never promoted to rectangle.
    """
    value = str(obj.get("object_type") or "").strip().lower()
    aliases = {
        "rectangle": "rectangle", "rect": "rectangle", "方形": "rectangle",
        "circle": "circle", "圆形": "circle",
        "arc": "arc", "圆弧": "arc",
        "line": "line", "segment": "line", "线段": "line",
        "outline": "outline", "polyline": "outline", "轮廓": "outline",
    }
    declared = aliases.get(value)
    refs = _refs(obj)
    measured = [item for item in (geometries or []) if item.get("id") in refs]
    if len(measured) == 1:
        kind = str(measured[0].get("type") or "")
        if kind == "circle":
            return "circle"
        if kind == "polyline":
            if rectangle_measure(measured[0]) is not None:
                return "rectangle"
            if heart_outline_measure(measured[0]).get("status") == "verified":
                return "heart"
            return "outline"
    return declared


def _unique_step_binding(
    refs: list[int],
    steps: list[dict[str, Any]],
    symbol_table: dict[str, list[int]],
    obj: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    return _step_binding_for_object(obj or {}, refs, steps, symbol_table)


def _measure_objects(geometries: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(geometries) != 1:
        return None
    geometry = geometries[0]
    kind = str(geometry.get("type") or "")
    if kind == "polyline":
        vertices = geometry.get("vertices") or []
        points = [(float(item.get("x")), float(item.get("y"))) for item in vertices
                  if isinstance(item, dict) and _number(item.get("x")) is not None
                  and _number(item.get("y")) is not None]
        if len(points) >= 2 and points[0] == points[-1]:
            points = points[:-1]
        if len(points) != 4:
            return None
        if geometry.get("closed") is not True:
            return None
        sides = []
        for index, point in enumerate(points):
            nxt = points[(index + 1) % 4]
            dx = nxt[0] - point[0]
            dy = nxt[1] - point[1]
            if abs(dx) > _TOLERANCE_MM and abs(dy) > _TOLERANCE_MM:
                # Only axis-aligned rectangles can be compared to width/height
                # without guessing which rotated edge is called "width".
                return None
            length = math.hypot(dx, dy)
            if length <= _TOLERANCE_MM:
                return None
            sides.append(length)
        if not (math.isclose(sides[0], sides[2], rel_tol=0.0, abs_tol=_TOLERANCE_MM)
                and math.isclose(sides[1], sides[3], rel_tol=0.0, abs_tol=_TOLERANCE_MM)):
            return None
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        width = max(xs) - min(xs)
        height = max(ys) - min(ys)
        if width <= 0 or height <= 0:
            return None
        area = 0.0
        for index, point in enumerate(points):
            nxt = points[(index + 1) % 4]
            area += point[0] * nxt[1] - nxt[0] * point[1]
        if not math.isclose(abs(area) / 2.0, width * height,
                            rel_tol=0.0, abs_tol=_TOLERANCE_MM * max(width, height)):
            return None
        return {
            "kind": "polyline",
            "shape": "rectangle",
            "width_mm": width,
            "height_mm": height,
            "bounds": {"min_x": min(xs), "min_y": min(ys),
                       "max_x": max(xs), "max_y": max(ys)},
            "vertex_count": len(points),
            "closed": True,
        }
    if kind == "circle":
        radius = _number(geometry.get("radius"))
        if radius is None or radius <= 0:
            return None
        return {
            "kind": "circle",
            "radius_mm": radius,
            "diameter_mm": radius * 2,
            "width_mm": radius * 2,
            "height_mm": radius * 2,
            "center": deepcopy(geometry.get("center")),
        }
    return None


def _actual_field(measurement: dict[str, Any], field: str) -> float | None:
    key = {
        "width": "width_mm", "height": "height_mm",
        "radius": "radius_mm", "diameter": "diameter_mm",
        "side_length": "width_mm",
    }.get(field)
    if key is None:
        return None
    value = measurement.get(key)
    return _number(value)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    return float(value)


def _promote_clause(clause: dict[str, Any], binding: dict[str, Any], bound_ids: list[str]) -> None:
    clause["status"] = "verified"
    clause["reason"] = None
    clause["binding"] = deepcopy(binding)
    clause["resolved_unsupported_evidence"] = deepcopy(
        clause.get("unsupported_evidence") or []
    )
    clause["unsupported_evidence"] = []
    clause.setdefault("evidence", [])
    if not isinstance(clause["evidence"], list):
        clause["evidence"] = []
    clause["evidence"].extend(
        deepcopy(item) for item in (binding.get("evidence") or [])
        if isinstance(item, dict)
    )
    clause["verifier"] = "bind_construction_measurement" if binding.get("kind") != "operation" \
        else "verify_drawing_creation"
    clause["authority"] = binding.get("authority")
    if clause.get("requirement_id"):
        bound_ids.append(str(clause["requirement_id"]))


def _recompute(coverage: dict[str, Any]) -> None:
    clauses = [item for item in coverage.get("clauses") or [] if isinstance(item, dict)]
    clause_ids = {str(item.get("requirement_id")) for item in clauses}
    old_blockers = [item for item in coverage.get("blocking_requirements") or []
                    if isinstance(item, dict)]
    blockers = [item for item in old_blockers
                if str(item.get("requirement_id")) not in clause_ids]
    for clause in clauses:
        if clause.get("status") != "verified":
            blockers.append({
                "requirement_id": clause.get("requirement_id"),
                "requirement": clause.get("requirement"),
                "status": clause.get("status"),
                "reason": clause.get("reason") or "未获得完整、来源绑定的独立测量证据",
            })
    coverage["verified_requirement_count"] = sum(
        1 for item in clauses if item.get("status") == "verified"
    )
    coverage["partial_requirement_count"] = sum(
        1 for item in clauses if item.get("status") == "partial"
    )
    coverage["unverified_requirement_count"] = sum(
        1 for item in clauses
        if item.get("status") in {"unverified", "unbound", "unsupported", "unparseable"}
    )
    coverage["blocking_requirements"] = blockers
    # Rebuild unresolved IDs from the post-binding clause state instead of
    # filtering against the previous binding snapshot.  A verified clause
    # resolves both its own clause ID and every fact it bound; unresolved clauses
    # keep their clause ID and all still-open fact IDs.
    resolved_refs: set[str] = set()
    for clause in clauses:
        if clause.get("status") != "verified":
            continue
        if clause.get("requirement_id"):
            resolved_refs.add(str(clause["requirement_id"]))
        for source in (
            (clause.get("binding") or {}).get("resolved_unsupported_evidence") or [],
            clause.get("resolved_unsupported_evidence") or [],
        ):
            for item in source:
                if not isinstance(item, dict):
                    continue
                fact_id = item.get("requirement_id") or item.get("fact_id")
                if fact_id:
                    resolved_refs.add(str(fact_id))
    unresolved = [
        item for item in coverage.get("unresolved_fact_ids") or []
        if str(item) not in resolved_refs
    ]
    for clause in clauses:
        if clause.get("status") == "verified":
            continue
        clause_id = str(clause.get("requirement_id") or "")
        if clause_id and clause_id not in unresolved:
            unresolved.append(clause_id)
        for evidence in clause.get("unsupported_evidence") or []:
            if isinstance(evidence, dict):
                fact_id = evidence.get("fact_id") or evidence.get("requirement_id")
                if fact_id and str(fact_id) not in unresolved:
                    unresolved.append(str(fact_id))
        for failure in clause.get("binding_failures") or []:
            fact_id = (
                failure.get("requirement_id")
                if isinstance(failure, dict)
                else failure
            ) or clause.get("requirement_id")
            if fact_id and str(fact_id) not in unresolved:
                unresolved.append(str(fact_id))
    coverage["unresolved_fact_ids"] = unresolved
    coverage["state"] = "complete" if not blockers else "partial"
