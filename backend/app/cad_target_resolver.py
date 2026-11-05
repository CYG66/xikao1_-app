"""Deterministic target resolution for structured CAD edits."""

from __future__ import annotations

import math
from typing import Any


_EPSILON = 1e-6
_MIN_TARGET_SCORE = 0.70
_MIN_TARGET_MARGIN = 0.15
_TARGET_SCORE_SCHEMA = "cad.target-score.v1"


def _authoritative_scoring(
    *,
    candidate_kind: str,
    candidate_ids: list[int | str],
    evidence_kind: str,
) -> dict[str, Any]:
    candidates = []
    id_key = {
        "instance": "instance_id",
        "geometry": "geometry_id",
        "logical_object": "object_id",
    }[candidate_kind]
    for candidate_id in candidate_ids:
        candidates.append({
            id_key: candidate_id,
            "score": 1.0,
            "evidence": [{"kind": evidence_kind, "score": 1.0}],
        })
    return {
        "schema": _TARGET_SCORE_SCHEMA,
        "decision": "authoritative",
        "minimum_score": _MIN_TARGET_SCORE,
        "minimum_margin": _MIN_TARGET_MARGIN,
        "winner_score": 1.0,
        "runner_up_score": None,
        "margin": 1.0,
        "candidates": candidates,
    }


def _score_extreme_candidates(
    *,
    candidate_ids: list[int | str],
    coordinates: dict[int | str, float],
    lower_bound: float,
    upper_bound: float,
    position: str,
    count: int,
    candidate_kind: str,
) -> tuple[list[int | str], dict[str, Any]]:
    """Rank spatial candidates and expose deterministic decision evidence."""
    id_key = {
        "instance": "instance_id",
        "logical_object": "object_id",
    }[candidate_kind]
    if len(candidate_ids) == 1:
        scoring = _authoritative_scoring(
            candidate_kind=candidate_kind,
            candidate_ids=candidate_ids,
            evidence_kind="only_candidate",
        )
        scoring["selection_count"] = count
        return list(candidate_ids), scoring
    span = max(0.0, upper_bound - lower_bound)
    positive = position in {"right", "top"}
    scored: list[dict[str, Any]] = []
    for candidate_id in candidate_ids:
        coordinate = coordinates[candidate_id]
        if span < _EPSILON:
            score = 0.5
        elif positive:
            score = (coordinate - lower_bound) / span
        else:
            score = (upper_bound - coordinate) / span
        score = round(max(0.0, min(1.0, score)), 6)
        scored.append({
            id_key: candidate_id,
            "score": score,
            "evidence": [{
                "kind": "spatial_position",
                "position": position,
                "coordinate": round(coordinate, 6),
                "drawing_span": round(span, 6),
                "score": score,
            }],
        })
    scored.sort(key=lambda item: (-item["score"], str(item[id_key])))
    ranked = [item[id_key] for item in scored]
    boundary_score = scored[count - 1]["score"]
    runner_score = scored[count]["score"] if count < len(scored) else None
    margin = 1.0 if runner_score is None else round(boundary_score - runner_score, 6)
    scoring = {
        "schema": _TARGET_SCORE_SCHEMA,
        "decision": "pending",
        "minimum_score": _MIN_TARGET_SCORE,
        "minimum_margin": _MIN_TARGET_MARGIN,
        "winner_score": scored[0]["score"],
        "runner_up_score": runner_score,
        "margin": margin,
        "selection_count": count,
        "candidates": scored,
    }
    return ranked, scoring


def _score_decision_reason(scoring: dict[str, Any]) -> str | None:
    if float(scoring["winner_score"]) < _MIN_TARGET_SCORE:
        return "target_score_too_low"
    if float(scoring["margin"]) < _MIN_TARGET_MARGIN:
        return "target_score_margin_too_small"
    return None


def _stable_spatial_candidates(
    candidates: list[dict[str, Any]], position: str,
) -> list[dict[str, Any]]:
    """Prefer persisted spatial identity over re-ranking live coordinates."""
    matched = []
    for item in candidates:
        anchor = item.get("spatial_anchor")
        if isinstance(anchor, dict) and anchor.get("position") == position:
            matched.append(item)
    return matched


def resolve_logical_object_target(
    selector: dict[str, Any], logical_objects: list[dict[str, Any]]
) -> dict[str, Any]:
    """Resolve spatial language against confirmed logical objects."""
    object_type = str(selector.get("object_type") or "").strip()
    candidates = [
        item for item in logical_objects
        if isinstance(item, dict)
        and item.get("confirmed") is not False
        and (not object_type or item.get("object_type") == object_type)
        and isinstance(item.get("bounds"), dict)
    ]
    if not candidates:
        return {
            "status": "needs_clarification",
            "reason": "logical_objects_unavailable",
            "question": "当前图纸没有可确认的逻辑对象，请在右侧画布点选目标。",
            "candidate_object_ids": [],
        }

    def center(item: dict[str, Any]) -> tuple[float, float]:
        bounds = item["bounds"]
        return (
            (float(bounds["min_x"]) + float(bounds["max_x"])) / 2,
            (float(bounds["min_y"]) + float(bounds["max_y"])) / 2,
        )

    centers = {str(item["object_id"]): center(item) for item in candidates}
    position = selector.get("position")
    stable = _stable_spatial_candidates(candidates, str(position or ""))
    if position in {"top", "bottom", "left", "right"} and len(stable) == 1:
        selected = stable[0]
        selected_objects = [selected]
        object_ids = [str(selected["object_id"])]
        geometry_ids = sorted({
            int(value) for value in selected.get("geometry_refs") or []
            if str(value).isdigit()
        })
        return {
            "status": "resolved",
            "object_id": object_ids[0],
            "object_ids": object_ids,
            "label": str(selected.get("label") or selected["object_id"]),
            "geometry_ids": geometry_ids,
            "confidence": 1.0,
            "reason": "stable_spatial_identity",
            "scoring": _authoritative_scoring(
                candidate_kind="logical_object",
                candidate_ids=object_ids,
                evidence_kind="stable_spatial_identity",
            ),
        }
    if position == "middle":
        xs = [value[0] for value in centers.values()]
        ys = [value[1] for value in centers.values()]
        axis = 0 if max(xs) - min(xs) >= max(ys) - min(ys) else 1
        ordered = sorted(
            candidates,
            key=lambda item: (
                centers[str(item["object_id"])][axis], str(item["object_id"])
            ),
        )
        requested_count = selector.get("count", 1)
        if not isinstance(requested_count, int) or requested_count < 1:
            requested_count = 1
        if requested_count > len(ordered):
            return {
                "status": "needs_clarification",
                "reason": "invalid_middle_count",
                "question": "指定的中间图形数量超过当前图纸中的对象数量。",
                "candidate_object_ids": [str(item["object_id"]) for item in ordered],
            }
        if requested_count == 1 and len(ordered) % 2 == 0:
            middle = ordered[len(ordered) // 2 - 1:len(ordered) // 2 + 1]
            return {
                "status": "needs_clarification",
                "reason": "even_middle_objects",
                "question": "当前有两个居中的对象，请在右侧画布选择其中一个。",
                "candidate_object_ids": [str(item["object_id"]) for item in middle],
            }
        start = max(0, (len(ordered) - requested_count) // 2)
        selected_objects = ordered[start:start + requested_count]
        selected = selected_objects[0]
    elif position in {"left", "right", "top", "bottom"}:
        axis = 0 if position in {"left", "right"} else 1
        candidate_ids = [str(item["object_id"]) for item in candidates]
        bounds_key = ("min_x", "max_x") if axis == 0 else ("min_y", "max_y")
        ranked_ids, scoring = _score_extreme_candidates(
            candidate_ids=candidate_ids,
            coordinates={value: centers[value][axis] for value in candidate_ids},
            lower_bound=min(float(item["bounds"][bounds_key[0]]) for item in candidates),
            upper_bound=max(float(item["bounds"][bounds_key[1]]) for item in candidates),
            position=position,
            count=1,
            candidate_kind="logical_object",
        )
        by_id = {str(item["object_id"]): item for item in candidates}
        selected = by_id[str(ranked_ids[0])]
        decision_reason = _score_decision_reason(scoring)
        if decision_reason:
            scoring["decision"] = "clarify"
            exact_tie = scoring["margin"] < _EPSILON
            return {
                "status": "needs_clarification",
                "reason": "equal_logical_position" if exact_tie else decision_reason,
                "question": (
                    "多个对象位置相同，请在右侧画布点选目标。"
                    if exact_tie else
                    "多个对象的位置过于接近，请在右侧画布点选目标。"
                ),
                "candidate_object_ids": [str(value) for value in ranked_ids],
                "confidence": 0.0,
                "scoring": scoring,
            }
        scoring["decision"] = "resolved"
    else:
        return {
            "status": "needs_clarification",
            "reason": "unsupported_logical_position",
            "question": "请说明目标位于左侧、右侧、上方、下方或中间。",
            "candidate_object_ids": [str(item["object_id"]) for item in candidates],
        }
    selected_objects = locals().get("selected_objects", [selected])
    object_ids = [str(item["object_id"]) for item in selected_objects]
    geometry_ids = sorted({
        int(value)
        for item in selected_objects
        for value in item.get("geometry_refs") or []
        if str(value).isdigit()
    })
    result = {
        "status": "resolved",
        "object_id": object_ids[0] if len(object_ids) == 1 else None,
        "object_ids": object_ids,
        "label": "、".join(str(item.get("label") or item["object_id"]) for item in selected_objects),
        "geometry_ids": geometry_ids,
        "confidence": float(scoring["winner_score"]) if position in {
            "left", "right", "top", "bottom"
        } else 1.0,
    }
    if position in {"left", "right", "top", "bottom"}:
        result["scoring"] = scoring
    return result


def validate_logical_object_target(
    object_id: str,
    geometry_ids: list[int],
    logical_objects: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate a public logical-object target against the current graph."""
    wanted = next(
        (item for item in logical_objects
         if isinstance(item, dict) and str(item.get("object_id")) == object_id),
        None,
    )
    if wanted is None:
        return {"ok": False, "reason": "unknown_object", "message": "逻辑对象已不存在，请重新选择当前图纸对象。"}
    expected = sorted({int(value) for value in wanted.get("geometry_refs") or [] if str(value).isdigit()})
    actual = sorted({int(value) for value in geometry_ids if isinstance(value, int) and value > 0})
    if actual != expected:
        return {
            "ok": False,
            "reason": "object_geometry_mismatch",
            "message": "逻辑对象的图元引用与当前图纸不一致，请重新选择对象。",
            "expected_geometry_ids": expected,
            "actual_geometry_ids": actual,
        }
    return {
        "ok": True,
        "object_id": object_id,
        "label": str(wanted.get("label") or object_id),
        "geometry_ids": expected,
    }


def logical_object_topology_conflict(
    object_id: str | list[str], topology: dict[str, Any]
) -> dict[str, Any] | None:
    object_ids = {object_id} if isinstance(object_id, str) else set(object_id)
    shared = [
        item for item in topology.get("shared_geometries", [])
        if isinstance(item, dict)
        and object_ids.intersection(item.get("object_ids") or [])
        and not set(item.get("object_ids") or []).issubset(object_ids)
    ]
    if not shared:
        return None
    return {
        "status": "needs_resolution",
        "reason": "shared_topology_conflict",
        "object_id": object_id,
        "shared_geometry_ids": sorted(
            int(item["geometry_id"]) for item in shared
            if str(item.get("geometry_id", "")).isdigit()
        ),
        "question": (
            "目标与相邻对象共享边界，不能直接单独移动。"
            "请选择调整尺寸、拆分边界后移动，或重新排列整组对象。"
        ),
        "options": ["调整目标对象尺寸", "拆分共享边界后移动", "重新排列整组对象"],
    }


def validate_split_shared_boundary_target(
    contract: dict[str, Any],
    geometries: list[dict[str, Any]],
    logical_objects: list[dict[str, Any]],
    topology: dict[str, Any],
) -> dict[str, Any]:
    """Rebind a persisted split contract to the current parent topology."""
    parameters = contract.get("parameters") if isinstance(contract.get("parameters"), dict) else {}
    if parameters.get("boundary_policy") != "split_shared":
        return {"ok": True, "enforced": False}
    target = contract.get("target") if isinstance(contract.get("target"), dict) else {}
    object_ids = {
        str(value) for value in [target.get("object_id"), *(target.get("object_ids") or [])]
        if value
    }
    objects_by_id = {
        str(item.get("object_id") or ""): item for item in logical_objects
        if isinstance(item, dict) and str(item.get("object_id") or "")
    }
    if target.get("scope") != "logical_object" or not object_ids:
        return {"ok": False, "enforced": True, "reason": "invalid_split_target",
                "message": "拆分协议没有绑定有效的逻辑对象。"}
    if any(value not in objects_by_id for value in object_ids):
        return {"ok": False, "enforced": True, "reason": "stale_split_target",
                "message": "拆分目标已不在当前候选中，请重新预览。"}
    expected_target_ids = sorted({
        int(raw) for object_id in object_ids
        for raw in objects_by_id[object_id].get("geometry_refs") or []
        if str(raw).isdigit()
    })
    actual_target_ids = sorted({
        int(raw) for raw in target.get("geometry_ids") or []
        if str(raw).isdigit()
    })
    if actual_target_ids != expected_target_ids:
        return {"ok": False, "enforced": True, "reason": "split_target_drift",
                "message": "拆分目标的边界集合已变化，请重新预览。"}
    conflict = logical_object_topology_conflict(sorted(object_ids), topology)
    expected_shared = sorted((conflict or {}).get("shared_geometry_ids") or [])
    actual_shared = sorted({
        int(raw) for raw in parameters.get("shared_geometry_ids") or []
        if str(raw).isdigit()
    })
    if not expected_shared or actual_shared != expected_shared:
        return {"ok": False, "enforced": True, "reason": "split_topology_drift",
                "message": "共享边界归属已变化，请重新预览。"}
    source_ids = sorted({
        int(item["id"]) for item in geometries
        if isinstance(item, dict) and str(item.get("id", "")).isdigit()
    })
    first_new = max(source_ids, default=0) + 1
    expected_created = list(range(first_new, first_new + len(expected_shared)))
    actual_created = sorted({
        int(raw) for raw in parameters.get("created_geometry_ids") or []
        if str(raw).isdigit()
    })
    if actual_created != expected_created:
        return {"ok": False, "enforced": True, "reason": "split_created_id_mismatch",
                "message": "新增边界 ID 与当前父候选不一致，请重新预览。"}
    return {
        "ok": True, "enforced": True,
        "object_ids": sorted(object_ids),
        "geometry_ids": expected_target_ids,
        "shared_geometry_ids": expected_shared,
        "created_geometry_ids": expected_created,
    }


def _points(geometry: dict[str, Any]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for key in ("start", "end", "center", "position"):
        value = geometry.get(key)
        if isinstance(value, dict):
            points.append(value)
    for key in ("vertices", "control_points"):
        value = geometry.get(key)
        if isinstance(value, list):
            points.extend(item for item in value if isinstance(item, dict))
    return points


def _bounds(items: list[dict[str, Any]]) -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for item in items:
        for point in _points(item):
            try:
                xs.append(float(point["x"]))
                ys.append(float(point["y"]))
            except (KeyError, TypeError, ValueError):
                continue
        center = item.get("center")
        if not isinstance(center, dict):
            continue
        try:
            cx, cy = float(center["x"]), float(center["y"])
            if item.get("type") == "ellipse":
                axis = item.get("major_axis") or {}
                radius = math.hypot(float(axis.get("x", 0)), float(axis.get("y", 0)))
                radius *= max(1.0, float(item.get("ratio", 1)))
            elif item.get("type") in {"circle", "arc"}:
                radius = float(item.get("radius", 0))
            else:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        xs.extend((cx - radius, cx + radius))
        ys.extend((cy - radius, cy + radius))
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def _clarification(
    reason: str,
    candidates: list[int],
    question: str,
    *,
    scoring: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "status": "needs_clarification",
        "reason": reason,
        "candidate_instance_ids": sorted(candidates),
        "question": question,
        "confidence": 0.0,
    }
    if scoring is not None:
        result["scoring"] = scoring
    return result


def resolve_cad_target(
    target_spec: dict[str, Any],
    geometries: list[dict[str, Any]],
    previous_contract: dict[str, Any] | None = None,
    drawing_selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve a target without guessing between equally valid candidates.

    Priority is canvas selection, explicit IDs, prior successful target, then
    deterministic positional selection. Attribute and relative selectors stay
    in the geometry executor because they can intentionally select entities.
    """
    groups = sorted({
        value for item in geometries
        if isinstance(item, dict)
        and isinstance((value := item.get("template_instance")), int)
        and value > 0
    })
    geometry_ids = {
        int(item["id"]) for item in geometries
        if isinstance(item, dict) and str(item.get("id", "")).isdigit()
    }

    if isinstance(drawing_selection, dict):
        raw_ids = drawing_selection.get("geometry_ids")
        try:
            selected = sorted({int(value) for value in raw_ids})
        except (TypeError, ValueError):
            selected = []
        if not selected or any(value not in geometry_ids for value in selected):
            return _clarification(
                "stale_canvas_selection", groups,
                "当前画布选区已失效，请在右侧图纸中重新点选目标。",
            )
        if drawing_selection.get("scope") == "logical_object":
            object_id = str(drawing_selection.get("object_id") or "")
            objects = drawing_selection.get("logical_objects")
            if isinstance(objects, list):
                checked = validate_logical_object_target(object_id, selected, objects)
                if not checked["ok"]:
                    return _clarification("invalid_logical_object_selection", groups, checked["message"])
            return {
                "status": "resolved", "scope": "logical_object",
                "object_id": object_id, "geometry_ids": selected,
                "reason": "canvas_logical_object", "confidence": 1.0,
                "scoring": _authoritative_scoring(
                    candidate_kind="logical_object", candidate_ids=[object_id],
                    evidence_kind="canvas_selection",
                ),
            }
        return {
            "status": "resolved", "scope": "geometry",
            "geometry_ids": selected, "reason": "canvas_selection",
            "confidence": 1.0,
            "scoring": _authoritative_scoring(
                candidate_kind="geometry", candidate_ids=selected,
                evidence_kind="canvas_selection",
            ),
        }

    explicit_geometry_ids = target_spec.get("geometry_ids")
    if isinstance(explicit_geometry_ids, list) and explicit_geometry_ids:
        if any(value not in geometry_ids for value in explicit_geometry_ids):
            return _clarification(
                "stale_geometry_id", groups,
                "选中的线段已不在当前图纸中，请重新点选目标。",
            )
        return {
            "status": "resolved", "scope": "geometry",
            "geometry_ids": sorted(set(explicit_geometry_ids)),
            "reason": "explicit_geometry_ids", "confidence": 1.0,
            "scoring": _authoritative_scoring(
                candidate_kind="geometry",
                candidate_ids=sorted(set(explicit_geometry_ids)),
                evidence_kind="explicit_id",
            ),
        }

    if target_spec.get("instances") == "all":
        if not groups:
            return _clarification("no_instances", [], "当前图纸中没有可修改的图形。")
        return {
            "status": "resolved", "scope": "instance",
            "instance_ids": groups, "reason": "all_instances", "confidence": 1.0,
            "scoring": _authoritative_scoring(
                candidate_kind="instance", candidate_ids=groups,
                evidence_kind="explicit_all",
            ),
        }

    explicit_instances = target_spec.get("instances")
    if not isinstance(explicit_instances, list):
        instance = target_spec.get("instance")
        explicit_instances = [instance] if isinstance(instance, int) else []
    if explicit_instances:
        missing = sorted(set(explicit_instances) - set(groups))
        if missing:
            return _clarification(
                "stale_instance_id", groups,
                f"批量修改的目标实例必须真实存在；实例 {missing} 已不在当前图纸中，请重新选择。",
            )
        return {
            "status": "resolved", "scope": "instance",
            "instance_ids": sorted(set(explicit_instances)),
            "reason": "explicit_instance_ids", "confidence": 1.0,
            "scoring": _authoritative_scoring(
                candidate_kind="instance",
                candidate_ids=sorted(set(explicit_instances)),
                evidence_kind="explicit_id",
            ),
        }

    if target_spec.get("target_reference") == "previous":
        target = previous_contract.get("target") if isinstance(previous_contract, dict) else None
        if not isinstance(target, dict):
            return _clarification(
                "missing_previous_target", groups,
                "找不到刚才修改的目标，请在右侧图纸中点选。",
            )
        ids = target.get("instance_ids")
        if target.get("scope") != "instance" or not isinstance(ids, list) or not ids:
            return _clarification(
                "unsupported_previous_target", groups,
                "刚才的目标不是完整图形，请重新点选本次要修改的目标。",
            )
        if any(value not in groups for value in ids):
            return _clarification(
                "stale_previous_target", groups,
                "刚才修改的图形已不存在，请重新点选目标。",
            )
        return {
            "status": "resolved", "scope": "instance",
            "instance_ids": sorted(set(ids)), "reason": "previous_contract",
            "confidence": 1.0,
            "scoring": _authoritative_scoring(
                candidate_kind="instance", candidate_ids=sorted(set(ids)),
                evidence_kind="explicit_previous_reference",
            ),
        }

    selector = target_spec.get("selector")
    position = target_spec.get("position")
    position_ordinal = None
    if isinstance(selector, dict) and selector.get("kind") == "position_ordinal":
        position = selector.get("position")
        position_ordinal = int(selector.get("ordinal", 1))
        count = 1
    elif isinstance(selector, dict) and selector.get("kind") == "extreme":
        position = selector.get("position")
        count = selector.get("count", 1)
    else:
        count = (target_spec.get("logical_object_selector") or {}).get("count", 1)
    object_type = (
        selector.get("object_type") if isinstance(selector, dict) else None
    ) or target_spec.get("object_type")
    if object_type and any(
        isinstance(item, dict) and item.get("template_type")
        for item in geometries
    ):
        typed_groups = sorted({
            int(item["template_instance"])
            for item in geometries
            if isinstance(item, dict)
            and str(item.get("template_type") or "") == str(object_type)
            and isinstance(item.get("template_instance"), int)
            and item["template_instance"] > 0
        })
        if not typed_groups:
            return _clarification(
                "template_type_not_found", groups,
                f"当前图纸中没有找到{object_type}，请确认目标场地类型。",
            )
        if position == "middle":
            if len(typed_groups) == 1:
                selected = typed_groups
            elif len(typed_groups) % 2 == 0:
                return _clarification(
                    "even_middle_typed_instances", typed_groups,
                    f"有多个居中的{object_type}，请在右侧画布点选目标。",
                )
            else:
                selected = [typed_groups[len(typed_groups) // 2]]
        elif len(typed_groups) == 1:
            selected = typed_groups
        elif position in {"top", "bottom", "left", "right"}:
            groups = typed_groups
        else:
            return _clarification(
                "multiple_typed_instances", typed_groups,
                f"当前有多个{object_type}，请说明位置或在右侧画布点选。",
            )
        if position == "middle" or len(typed_groups) == 1:
            return {
                "status": "resolved", "scope": "instance",
                "instance_ids": selected,
                "reason": "unique_template_type" if len(typed_groups) == 1 else "middle_template_type",
                "confidence": 1.0,
                "scoring": _authoritative_scoring(
                    candidate_kind="instance", candidate_ids=selected,
                    evidence_kind="template_type_and_position",
                ),
            }
    if position == "middle" and not object_type:
        mid_bounds = {
            group: _bounds([
                item for item in geometries
                if item.get("template_instance") == group
            ])
            for group in groups
        }
        if any(mid_bounds[group] is None for group in groups):
            return _clarification("missing_bounds", groups, "部分图形缺少可计算边界，请在右侧图纸中点选目标。")
        mid_centers = {
            group: (mid_bounds[group][0] + mid_bounds[group][2]) / 2
            for group in groups
        }
        requested = count if isinstance(count, int) and count >= 1 else 1
        if requested > len(groups):
            return _clarification(
                "invalid_middle_count", groups,
                "指定的图形数量超出当前候选，请重新说明数量。",
            )
        ordered = sorted(groups, key=lambda group: mid_centers[group])
        start = (len(groups) - requested) // 2
        selected = ordered[start: start + requested]
        return {
            "status": "resolved", "scope": "instance",
            "instance_ids": selected, "reason": "middle_count",
            "confidence": 1.0,
            "scoring": _authoritative_scoring(
                candidate_kind="instance", candidate_ids=selected,
                evidence_kind="middle_position_count",
            ),
        }
    if position in {"top", "bottom", "left", "right"}:
        bounds_by_group = {
            group: _bounds([
                item for item in geometries
                if item.get("template_instance") == group
            ])
            for group in groups
        }
        if any(bounds_by_group[group] is None for group in groups):
            return _clarification(
                "missing_bounds", groups,
                "部分图形缺少可计算边界，请在右侧图纸中点选目标。",
            )
        if position_ordinal is not None and (position_ordinal < 1 or position_ordinal > len(groups)):
            return _clarification(
                "invalid_ordinal", groups,
                "指定的第几个图形不存在，请重新说明。",
            )
        if not isinstance(count, int) or count < 1 or count > len(groups):
            return _clarification(
                "invalid_extreme_count", groups,
                "指定的图形数量超出当前候选，请重新说明数量。",
            )
        axis = 1 if position in {"top", "bottom"} else 0
        centers = {
            group: (
                (bounds_by_group[group][0] + bounds_by_group[group][2]) / 2,
                (bounds_by_group[group][1] + bounds_by_group[group][3]) / 2,
            )
            for group in groups
        }
        lower_bound = min(bounds_by_group[group][axis] for group in groups)
        upper_index = 3 if axis == 1 else 2
        upper_bound = max(bounds_by_group[group][upper_index] for group in groups)
        ranked, scoring = _score_extreme_candidates(
            candidate_ids=groups,
            coordinates={group: centers[group][axis] for group in groups},
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            position=position,
            count=count,
            candidate_kind="instance",
        )
        decision_reason = _score_decision_reason(scoring)
        if decision_reason:
            scoring["decision"] = "clarify"
            exact_tie = scoring["margin"] < _EPSILON
            boundary_score = scoring["candidates"][count - 1]["score"]
            tied = [
                item["instance_id"] for item in scoring["candidates"]
                if abs(item["score"] - boundary_score) < _EPSILON
            ]
            return _clarification(
                "equal_extreme_position" if exact_tie else decision_reason,
                tied if exact_tie else ranked,
                (
                    "多个图形在该方向位置相同，请在右侧画布点选目标。"
                    if exact_tie else
                    "多个候选图形在该方向的位置过于接近，请在右侧画布点选目标。"
                ),
                scoring=scoring,
            )
        selected = (
            [ranked[position_ordinal - 1]] if position_ordinal is not None
            else sorted(ranked[:count])
        )
        scoring["decision"] = "resolved"
        return {
            "status": "resolved", "scope": "instance",
            "instance_ids": selected, "reason": f"{position}most",
            "confidence": float(scoring["winner_score"]),
            "scoring": scoring,
        }

    if len(groups) == 1:
        return {
            "status": "resolved", "scope": "instance",
            "instance_ids": groups, "reason": "only_instance", "confidence": 1.0,
            "scoring": _authoritative_scoring(
                candidate_kind="instance", candidate_ids=groups,
                evidence_kind="only_instance",
            ),
        }
    return _clarification(
        "target_ambiguous", groups,
        "请说明要修改第几个图形，或在右侧画布直接点选目标。",
    )


def bind_resolved_target(target_spec: dict[str, Any], resolution: dict[str, Any]) -> None:
    """Write a successful resolver result back to the legacy executor shape."""
    if resolution.get("status") != "resolved":
        return
    target_spec.pop("position", None)
    if isinstance(target_spec.get("selector"), dict) and target_spec["selector"].get("kind") == "extreme":
        target_spec.pop("selector", None)
    if resolution.get("scope") == "geometry":
        target_spec.pop("instance", None)
        target_spec.pop("instances", None)
        target_spec["geometry_ids"] = list(resolution.get("geometry_ids") or [])
        return
    ids = list(resolution.get("instance_ids") or [])
    target_spec.pop("geometry_ids", None)
    if len(ids) == 1:
        target_spec["instance"] = ids[0]
        target_spec.pop("instances", None)
    else:
        target_spec["instance"] = None
        target_spec["instances"] = ids
