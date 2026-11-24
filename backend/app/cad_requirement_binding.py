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

_TOLERANCE_MM = 0.5

_SHAPE_WORDS = (
    ("rectangle", re.compile(r"矩形|长方形|方形")),
    ("circle", re.compile(r"圆形|圆(?!心|弧|周)")),
    ("arc", re.compile(r"圆弧|弧线|弧")),
    ("line", re.compile(r"线段|直线|一条线")),
)
_DIMENSION_WORDS = re.compile(
    r"宽|高|长|半径|直径|边长|周长|面积|尺寸|外径|内径"
)
_OPERATION_WORDS = re.compile(r"新建|创建|生成.*图纸|画.*图纸")
_DRAWING_WORDS = re.compile(r"图纸")
_NEGATED_OR_EDIT = re.compile(r"不要|不需要|无需|禁止|别|取消|删除|移除|去掉|修改|编辑|移动|旋转|缩放")


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
            item for item in objects if _object_kind(item) == kind
        ]
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
        step_binding = _unique_step_binding(refs, steps, symbols)
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
            clause["status"] = "partial"
            clause["reason"] = failures[0]["reason"]
            clause["binding_failures"] = deepcopy(failures)
            clause["evidence"] = deepcopy(evidence_items)
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

    _recompute(result)
    result.setdefault("binding", {})
    result["binding"] = {
        "schema": "cad.requirement-binding.v1",
        "bound_clause_ids": bound_clause_ids,
        "bound_fact_ids": bound_fact_ids,
        "tolerance_mm": float(tolerance_mm),
        "authority": "backend_measured_geometry",
    }
    return result


def _operation_binding(requirement: str, project_evidence: dict[str, Any] | None) -> dict[str, Any] | None:
    if not _DRAWING_WORDS.search(requirement) or not _OPERATION_WORDS.search(requirement):
        return None
    if _clause_shape_kind(requirement) is not None:
        return None
    evidence = project_evidence if isinstance(project_evidence, dict) else {}
    if evidence.get("project_exists") is not True or not evidence.get("project_id"):
        return None
    return {
        "schema": "cad.requirement-binding.v1",
        "requirement_id": None,
        "kind": "operation",
        "operation": "create_drawing",
        "project_id": str(evidence["project_id"]),
        "project_status": evidence.get("project_status"),
        "project_store_authority": str(evidence.get("authority") or "creative_project_store"),
        "evidence": [{
            "requirement_id": None,
            "verifier": "verify_project_creation",
            "status": "verified",
            "measurement": {
                "operation": "create_drawing",
                "project_id": str(evidence["project_id"]),
                "project_status": evidence.get("project_status"),
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


def _object_kind(obj: dict[str, Any]) -> str | None:
    value = str(obj.get("object_type") or "").strip().lower()
    aliases = {
        "rectangle": "rectangle", "rect": "rectangle", "方形": "rectangle",
        "circle": "circle", "圆形": "circle",
        "arc": "arc", "圆弧": "arc",
        "line": "line", "segment": "line", "线段": "line",
    }
    return aliases.get(value)


def _unique_step_binding(
    refs: list[int],
    steps: list[dict[str, Any]],
    symbol_table: dict[str, list[int]],
) -> dict[str, Any] | None:
    matches = []
    for step in steps:
        output_ref = str(step.get("output_ref") or "")
        symbol_refs = symbol_table.get(output_ref)
        if isinstance(symbol_refs, list) and set(refs).intersection(
            int(value) for value in symbol_refs if isinstance(value, int)
        ):
            matches.append(step)
    if len(matches) != 1:
        return None
    return matches[0]


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
        else "verify_project_creation"
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
    bound_fact_ids = {
        str(item) for item in (coverage.get("binding") or {}).get("bound_fact_ids") or []
    }
    unresolved = [
        item for item in coverage.get("unresolved_fact_ids") or []
        if str(item) not in bound_fact_ids
    ]
    for clause in clauses:
        if clause.get("status") == "verified":
            continue
        for evidence in clause.get("unsupported_evidence") or []:
            if isinstance(evidence, dict) and evidence.get("fact_id"):
                unresolved.append(evidence["fact_id"])
        for failure in clause.get("binding_failures") or []:
            fact_id = (
                failure.get("requirement_id")
                if isinstance(failure, dict)
                else failure
            ) or clause.get("requirement_id")
            if fact_id and fact_id not in unresolved:
                unresolved.append(fact_id)
    coverage["unresolved_fact_ids"] = unresolved
    coverage["state"] = "complete" if not blockers else "partial"
