"""Normalize natural-language CAD edits before deterministic execution."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_PARAMETER_KEYS = {
    "dx_mm", "dy_mm", "angle_degrees", "pivot", "factor", "dimension",
    "value_mm", "direction", "distance_mm", "placement", "alignment",
    "reference_instance", "new_instance", "coordinate_frame", "local_axis",
    "local_direction_explicit", "boundary_policy", "shared_geometry_ids",
    "created_geometry_ids", "created_object_ids", "constraint_kind", "constraint_type",
    "solved_width_mm", "solved_height_mm", "object_type", "quantity",
    "placements", "relations", "dimension_mode",
    "mirror_axis", "mirror_coordinate_mm", "keep_source", "offset_side",
    "array_mode", "rows", "columns", "row_spacing_mm", "column_spacing_mm", "count",
}


def _unique(items: list[Any]) -> list[Any]:
    result: list[Any] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


def _target(parsed: dict[str, Any]) -> dict[str, Any]:
    geometry_ids = [
        int(value) for value in parsed.get("geometry_ids") or []
        if isinstance(value, int) and value > 0
    ]
    object_ids = [
        str(value) for value in parsed.get("logical_object_ids") or [] if value
    ]
    if parsed.get("logical_object_id"):
        object_ids.insert(0, str(parsed["logical_object_id"]))
    if object_ids or geometry_ids and parsed.get("logical_object_id"):
        return {
            "scope": "logical_object",
            "instance_ids": [],
            "geometry_ids": _unique(geometry_ids),
            "object_ids": _unique(object_ids),
            "selector": {},
        }
    if geometry_ids:
        return {
            "scope": "geometry",
            "instance_ids": [],
            "geometry_ids": _unique(geometry_ids),
            "object_ids": [],
            "selector": {},
        }
    instances = [
        int(value) for value in parsed.get("instances") or []
        if isinstance(value, int) and value > 0
    ]
    if isinstance(parsed.get("instance"), int) and parsed["instance"] > 0:
        instances.insert(0, int(parsed["instance"]))
    if instances:
        return {
            "scope": "instance",
            "instance_ids": _unique(instances),
            "geometry_ids": [],
            "object_ids": [],
            "selector": {},
        }
    selector = parsed.get("logical_object_selector") or parsed.get("selector")
    if isinstance(selector, dict) and selector:
        return {
            "scope": "selector",
            "instance_ids": [],
            "geometry_ids": [],
            "object_ids": [],
            "selector": deepcopy(selector),
        }
    if parsed.get("position"):
        return {
            "scope": "selector",
            "instance_ids": [],
            "geometry_ids": [],
            "object_ids": [],
            "selector": {
                "kind": "spatial",
                "position": str(parsed["position"]),
            },
        }
    if parsed.get("operation") == "add_constrained":
        return {
            "scope": "selector",
            "instance_ids": [],
            "geometry_ids": [],
            "object_ids": [],
            "selector": {
                "kind": "current_primary_court",
                "required_features": ["closed_boundary", "outer_circle"],
            },
        }
    return {
        "scope": "unresolved",
        "instance_ids": [],
        "geometry_ids": [],
        "object_ids": [],
        "selector": {},
    }


def _derived_constraints(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    constraints = [
        deepcopy(item) for item in parsed.get("constraints") or []
        if isinstance(item, dict)
    ]
    if parsed.get("operation") == "add_constrained":
        placements = list(parsed.get("placements") or [])
        relations = set(parsed.get("relations") or [])
        constraints.extend([
            {
                "kind": "quantity",
                "object_type": str(parsed.get("object_type") or "rectangle"),
                "value": int(parsed.get("quantity") or 2),
            },
            {"kind": "placement", "values": placements},
            {
                "kind": "adjacency",
                "required": "adjacent_to_target" in relations,
            },
            {
                "kind": "vertices_on_boundary",
                "boundary_type": "circle",
                "vertex_role": "outer",
                "vertices_per_object": 2,
                "required": "outer_vertices_on_circle" in relations,
            },
            {"kind": "symmetry", "axis": "target_horizontal_centerline"},
        ])
    return _unique(constraints)


def _auto_decisions(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    decisions = [
        deepcopy(item) for item in parsed.get("auto_decisions") or []
        if isinstance(item, dict)
    ]
    mode = parsed.get("dimension_mode")
    if mode == "maximize_area":
        decisions.append({
            "parameter": "rectangle.dimensions",
            "policy": "auto_optimize",
            "objective": "maximize_area",
        })
    return _unique(decisions)


def _missing_parameters(
    operation: str, target: dict[str, Any], parameters: dict[str, Any]
) -> list[str]:
    missing: list[str] = []
    if target["scope"] == "unresolved":
        missing.append("target")
    required = {
        "translate": ("dx_mm", "dy_mm"),
        "rotate": ("angle_degrees", "pivot"),
        "scale": ("factor", "pivot"),
        "resize": ("dimension", "value_mm"),
        "duplicate": ("direction", "distance_mm", "placement"),
        "align": ("alignment", "reference_instance"),
    }.get(operation, ())
    for key in required:
        if parameters.get(key) is None:
            missing.append(key)
    if operation == "add_constrained":
        for key in ("object_type", "quantity", "placements", "relations", "dimension_mode"):
            if not parameters.get(key):
                missing.append(key)
    if operation == "constraint":
        if not parameters.get("constraint_type"):
            missing.append("constraint_type")
        if parameters.get("constraint_type") == "equal" and not parameters.get("dimension"):
            missing.append("equality_metric")
        elif parameters.get("constraint_type") == "equal" and parameters.get("dimension") not in {"宽度", "高度", "半径"}:
            missing.append("unsupported_equality_metric")
    return _unique(missing)


def build_cad_edit_intent(
    source_text: str,
    parsed_edit: dict[str, Any],
    *,
    inherited: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one stable intent shape for both simple and constrained edits."""
    operation = str(parsed_edit.get("operation") or "")
    target = _target(parsed_edit)
    parameters = {
        key: deepcopy(value)
        for key, value in parsed_edit.items()
        if key in _PARAMETER_KEYS and value is not None
    }
    inherited = inherited if isinstance(inherited, dict) else {}
    assumptions = _unique([
        str(value) for value in [
            *(inherited.get("assumptions") or []),
            *(parsed_edit.get("assumptions") or []),
        ] if str(value).strip()
    ])
    constraints = _unique([
        *[
            deepcopy(item) for item in inherited.get("constraints") or []
            if isinstance(item, dict)
        ],
        *_derived_constraints(parsed_edit),
    ])
    auto_decisions = _unique([
        *[
            deepcopy(item) for item in inherited.get("auto_decisions") or []
            if isinstance(item, dict)
        ],
        *_auto_decisions(parsed_edit),
    ])
    missing = _missing_parameters(operation, target, parameters)
    if parsed_edit.get("constraint_conflict"):
        missing.insert(0, "constraint_conflict")
    result = {
        "schema": "cad.edit-intent.v1",
        "source_text": source_text.strip(),
        "target": target,
        "operation": operation,
        "parameters": parameters,
        "assumptions": assumptions,
        "constraints": constraints,
        "missing_parameters": missing,
        "auto_decisions": auto_decisions,
        "confidence": min(
            float(inherited.get("confidence", 1.0)),
            1.0 if not missing else max(0.4, 1.0 - 0.12 * len(missing)),
        ),
    }
    if inherited.get("parser"):
        result["parser"] = str(inherited["parser"])
    if isinstance(inherited.get("evidence_text"), list):
        result["evidence_text"] = [
            str(value) for value in inherited["evidence_text"] if str(value).strip()
        ]
    if isinstance(inherited.get("grounding"), dict):
        result["grounding"] = deepcopy(inherited["grounding"])
    return result


def cad_edit_intent_clarification(intent: dict[str, Any]) -> str | None:
    """Ask only the first blocking question in execution order."""
    missing = list(intent.get("missing_parameters") or [])
    if not missing:
        return None
    if missing[0]=='angle_degrees':
        import re
        angle=re.search(r'旋转\s*(\d+(?:\.\d+)?)\s*度',str(intent.get('source_text') or ''))
        if angle:return f"旋转角度 {angle[1]} 度已记录，请明确顺时针还是逆时针。"
    questions = {
        "constraint_conflict": "本轮包含多个约束或否定要求，请明确本次执行哪一种约束。",
        "target": "请在右侧图纸中点选要修改的对象，或说明是第几个图形。",
        "angle_degrees": "请说明要旋转多少度。",
        "pivot": "请说明是各自绕自身中心旋转，还是作为整体绕组合中心旋转。",
        "factor": "请说明要缩放到原来的多少倍。",
        "dimension": "请说明要修改宽度、高度还是半径。",
        "value_mm": "请说明修改后的尺寸。",
        "direction": "请说明复制到目标图形的哪个方向。",
        "distance_mm": "请说明复制距离或两个图形之间的间距。",
        "placement": "请说明给出的是移动距离，还是两个图形之间的净间距。",
        "alignment": "请说明要左对齐、右对齐、顶部对齐、底部对齐或居中对齐。",
        "reference_instance": "请说明要以哪个图形作为对齐基准。",
        "constraint_type": "请说明两个对象需要满足什么几何关系。",
        "equality_metric": "请明确一样大是指宽度、高度、半径还是面积相等。",
        "unsupported_equality_metric": "当前尚不支持面积或周长相等约束；不会替换为宽度、高度或半径相等。",
    }
    return questions.get(str(missing[0]), "请补充本次修改所需的关键参数。")


def apply_intent_metadata(
    edit: dict[str, Any], intent: dict[str, Any]
) -> dict[str, Any]:
    """Attach normalized intent evidence to an executor-compatible edit."""
    result = dict(edit)
    for key in ("assumptions", "constraints", "missing_parameters", "auto_decisions"):
        result[key] = deepcopy(intent.get(key) or [])
    result["intent_schema"] = "cad.edit-intent.v1"
    if intent.get("parser"):
        result["intent_parser"] = str(intent["parser"])
    if isinstance(intent.get("evidence_text"), list):
        result["intent_evidence_text"] = list(intent["evidence_text"])
    if isinstance(intent.get("grounding"), dict):
        result["intent_grounding"] = deepcopy(intent["grounding"])
    result["intent_confidence"] = float(intent.get("confidence", 1.0))
    return result
