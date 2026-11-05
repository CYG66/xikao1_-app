"""Pure candidate-selection and whole-design geometry transforms."""

from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any

from .agent_service_context import merge_design_requirements, template_geometry_count
from .agent_skills import (
    DRAWING_TEMPLATE_SKILLS,
    build_template_logical_object_graph,
    compose_template_instance_count,
    heart_outline_geometry,
    normalize_template_layout_for_matches,
    parameterize_design,
    recognize_drawing_template,
    recognize_drawing_template_set,
    score_design_variant,
    validate_template_layout,
)
from .drawing_store import preview_paths
from .logical_topology import validate_logical_object_graph
from .cad_candidate_state import candidate_is_accepted


def assess_reusable_variant(
    variant: object,
    *,
    expected_geometries: list[dict[str, Any]] | None,
    expected_template_name: str,
    expected_quantity: int,
    source_drawing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Determine whether an existing candidate exactly satisfies expectations."""
    if not isinstance(variant, dict):
        return {"reusable": False, "reason": "invalid_variant"}
    if not candidate_is_accepted(variant):
        return {"reusable": False, "reason": "acceptance_not_passed"}
    geometries = variant.get("geometries")
    if not isinstance(geometries, list) or not geometries:
        return {"reusable": False, "reason": "missing_geometries"}
    if isinstance(expected_geometries, list) and geometries != expected_geometries:
        return {"reusable": False, "reason": "geometry_mismatch"}
    if not expected_template_name:
        return {"reusable": True, "reason": "geometry_match"}

    assessment = template_instance_assessment(
        geometries,
        expected_template_name,
        source_drawing=source_drawing,
        allow_legacy_migration=True,
        expected_geometries=expected_geometries,
    )
    if assessment.get("authoritative") is not True:
        return {
            "reusable": False,
            "reason": "instance_count_not_authoritative",
            "instance_assessment": assessment,
        }
    actual_quantity = int(assessment.get("count") or 0)
    return {
        "reusable": actual_quantity == expected_quantity,
        "reason": (
            "instance_count_match"
            if actual_quantity == expected_quantity
            else "instance_count_mismatch"
        ),
        "instance_assessment": assessment,
        "migrated_geometries": assessment.get("migrated_geometries"),
    }


def candidate_variant_metadata(
    context: dict[str, Any], *, quantity_mismatch: bool
) -> dict[str, Any]:
    """Build candidate title, change note, and logical-object template inputs."""
    expected_template = context.get("expected_template")
    expected_template = expected_template if isinstance(expected_template, dict) else {}
    expected_template_name = str(context.get("expected_template_name") or "")
    expected_quantity = max(1, int(context.get("expected_quantity") or 1))
    requirements = context.get("requirements")
    requirements = requirements if isinstance(requirements, dict) else {}
    template_set = context.get("template_set")

    graph_match = dict(expected_template)
    if expected_template_name:
        graph_match.setdefault("template", expected_template_name)
    graph_match["quantity"] = expected_quantity
    dimensions = requirements.get("dimensions")
    if isinstance(dimensions, dict):
        for key in ("width_m", "height_m", "radius_m"):
            if isinstance(dimensions.get(key), (int, float)):
                graph_match[key] = float(dimensions[key])

    composite_name = None
    if isinstance(template_set, list) and len(template_set) > 1:
        composite_name = " + ".join(
            str(
                DRAWING_TEMPLATE_SKILLS.get(str(item["template"]), {}).get("label")
                or item["template"]
            )
            for item in template_set
        ) + "组合方案"

    template_key = str(expected_template.get("template") or "")
    object_label = (
        "车位"
        if template_key in {"parking", "parking_lot"}
        else str(expected_template.get("label") or "图形")
    )
    title = (
        composite_name
        or (
            f"{expected_quantity} 个{object_label}修正方案"
            if quantity_mismatch
            else "标准候选方案"
        )
    )
    description = (
        "检测到旧方案未包含全部复合场地，已按原始需求重新生成；未启动小车。"
        if composite_name and quantity_mismatch
        else (
            f"检测到旧方案未满足 {expected_quantity} 个{object_label}，"
            "已按原始需求重新生成；未启动小车。"
            if quantity_mismatch
            else "根据已确认的图形、尺寸和中心喷码机生成；未启动小车。"
        )
    )
    return {
        "title": title,
        "description": description,
        "graph_match": graph_match,
        "composite": composite_name is not None,
    }


def candidate_requirement_readiness(
    project: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Read readiness exclusively from the persisted requirement contract.

    ``context.prompt`` and conversation memory are deliberately ignored here.
    They may help produce a proposed contract, but only ``project`` represents
    the committed truth used by the construction gate.
    """
    requirements = project.get("requirements")
    requirements = requirements if isinstance(requirements, dict) else {}
    from .cad_requirement_contract import project_requirement_state
    state = project.get('requirement_state')
    if not isinstance(state, dict):
        state = project_requirement_state(project)
    unresolved = list(dict.fromkeys(
        str(item).strip() for item in project.get("missing_parameters") or []
        if str(item).strip()
    ))
    return {
        "ready": state.get('status') == 'ready',
        "missing": list(state.get('missing') or []),
        "conflicts": list(state.get('conflicts') or []),
        "revision": state.get('revision'),
        "apply_default_printer": False,
        "default_requirements": {},
        "requirements": deepcopy(requirements),
        "source": "persisted_project_requirement_contract",
    }


# Generator-supported shape enum used by design_geometries_for_project.
# Keep this in sync with the shape branches there so a normalized value is
# always actually generatable.
_SHAPE_ENUM_HINTS = (
    ("closed_semicircular_arch", ("半圆拱门", "拱门", "semicircular arch", "arch")),
    ("heart_outline", ("爱心", "心形", "心型", "heart")),
    ("rectangle", ("矩形", "长方形", "正方形", "rect", "rectangle")),
    ("circle", ("圆形", "圆", "circle")),
)
_KNOWN_SHAPE_VALUES = {
    "closed_semicircular_arch", "semicircular_arch", "arch", "半圆拱门", "拱门",
    "heart_outline", "heart", "爱心", "心形", "心型",
    "rectangle", "rect", "长方形", "矩形",
    "circle", "圆", "圆形",
}


def is_generator_supported_shape(shape: Any) -> bool:
    """Whether the deterministic generator can build this shape.

    Non-enum descriptive shapes (e.g. ``bezier``) are valid user-provided
    shapes that must go through the construction / direct-injection paths;
    the confirmation gate must not report them as "missing shape".
    """
    return str(shape or "").strip().lower() in _KNOWN_SHAPE_VALUES


def _normalize_shape_value(shape: Any, prompt: str) -> Any:
    """Map a descriptive shape value onto a generator-supported enum."""
    text = str(shape or "").strip().lower()
    prompt_text = str(prompt or "").strip().lower()
    if text in _KNOWN_SHAPE_VALUES:
        return shape
    for enum_value, keywords in _SHAPE_ENUM_HINTS:
        if any(keyword in text for keyword in keywords) or (
            not text and any(keyword in prompt_text for keyword in keywords)
        ):
            return enum_value
    if not text:
        inferred = parameterize_design(prompt_text)
        if isinstance(inferred, dict) and inferred.get("shape"):
            return inferred["shape"]
    return shape


def _normalize_dimensions(requirements: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the dimensions sub-dict from top-level metric fields when needed.

    LLM-authored requirements may use descriptive key names (total_height_m /
    arc_radius_m / straight_side_height_m / leg_height_m) instead of the
    standard generator keys (height_m / radius_m / leg_height_m). Map them
    onto the standard keys so the confirmation gate, unit normalization and
    the generator all read the same values.
    """
    dimensions = requirements.get("dimensions")
    dimensions = dict(dimensions) if isinstance(dimensions, dict) else {}
    # 非标准键 → 标准键（数值优先；字符串描述如 bottom_closure 原样保留）
    key_aliases = {
        "total_height_m": "height_m",
        "total_width_m": "width_m",
        "arc_radius_m": "radius_m",
        "radius": "radius_m",
        "straight_side_height_m": "leg_height_m",
        "leg_height_m": "leg_height_m",
        "leg_m": "leg_height_m",
    }
    for alias, standard in key_aliases.items():
        if standard in dimensions:
            continue
        value = dimensions.get(alias)
        if not isinstance(value, (int, float)) or value <= 0:
            value = requirements.get(alias)
        if isinstance(value, (int, float)) and value > 0:
            dimensions[standard] = float(value)
    for key in ("width_m", "height_m", "radius_m", "diameter_m"):
        if key not in dimensions:
            value = requirements.get(key)
            if isinstance(value, (int, float)):
                dimensions[key] = float(value)
    return dimensions


def normalize_design_requirements(
    requirements: dict[str, Any] | None,
    prompt: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """Single normalization gate for creative-project write paths.

    Model-written requirements (``update_creative_project``) may carry a
    descriptive ``shape`` string and top-level ``width_m``/``height_m`` while
    the generator reads the ``shape`` enum plus the ``dimensions`` sub-dict.
    Normalizing here keeps the "missing" classification identical between the
    reply layer and the generator, so a project is never reported ready while
    the generator would still reject it.
    """
    req = deepcopy(requirements) if isinstance(requirements, dict) else {}
    text = str(prompt or "").strip()
    template = recognize_drawing_template(text) if text else None
    dimensions = _normalize_dimensions(req)
    req["dimensions"] = dimensions
    # units 归一化：LLM 直投常写中文"米/毫米"，标准值是 m/mm，
    # normalize_model_geometry_units 的 explicit_units 只认 m/mm。
    units_raw = str(req.get("units") or "").strip().lower()
    if units_raw in {"米", "m"}:
        req["units"] = "m"
    elif units_raw in {"毫米", "mm"}:
        req["units"] = "mm"
    missing: list[str] = []
    if template is None:
        # 拱门是复合结构（半圆弧 + 两侧直立边）：LLM 可能把 shape 简写为
        # "circle"（"半圆拱门"含"圆"字），但 dimensions 里带拱门结构键
        # （leg_height_m / arc_radius_m 归一化后）就强制识别为拱门，
        # 防止确认闸把拱门当整圆生成器处理。
        shape_raw = str(req.get("shape") or "").strip().lower()
        arch_markers = ("拱门", "arch", "semicircular")
        arch_keys = (
            "leg_height_m",
            "arc_radius_m",
            "straight_side_height_m",
            "total_height_m",
        )
        has_arch_keys = any(
            str(key) in req or key in dimensions for key in arch_keys
        )
        if (
            has_arch_keys
            and not any(marker in shape_raw for marker in arch_markers)
        ):
            req["shape"] = "closed_semicircular_arch"
        normalized_shape = _normalize_shape_value(req.get("shape"), text)
        req["shape"] = normalized_shape
        # shape 存在（含描述性值）即视为满足——用户已提供图形描述；
        # 确定性生成器是否支持该 shape 由 design_geometries_for_project
        # 自行判定（非枚举图形走构造/直投路径），与确认闸同口径，
        # 避免“用户已确认但 normalize 判缺 → 项目回 clarifying”的矛盾。
        if not str(req.get("shape") or "").strip():
            missing.append("shape")
        if not dimensions:
            missing.append("dimensions")
    req["missing"] = missing
    return req, missing


def _geometry_extent(geometries: list[dict[str, Any]]) -> tuple[float, float] | None:
    """Return (width, height) of a geometry set, coordinates treated as mm."""
    xs: list[float] = []
    ys: list[float] = []
    for geometry in geometries:
        if not isinstance(geometry, dict):
            continue
        geometry_type = str(geometry.get("type") or "").lower()
        points: list[Any] = []
        if geometry_type == "line":
            points = [geometry.get("start"), geometry.get("end")]
        elif geometry_type == "polyline":
            points = geometry.get("vertices") or []
        elif geometry_type in {"circle", "arc"}:
            # 只取中心会丢失半径包围盒（半圆弧顶部、整圆外沿），
            # 导致 extent 与真实尺寸量级不符、单位判定误判为毫米。
            points = [geometry.get("center")]
            radius = geometry.get("radius")
            if isinstance(radius, (int, float)) and float(radius) > 0:
                center = geometry.get("center")
                if isinstance(center, dict):
                    try:
                        cx = float(center["x"])
                        cy = float(center["y"])
                    except (KeyError, TypeError, ValueError):
                        cx = cy = None
                    if cx is not None and cy is not None:
                        points.extend([
                            {"x": cx - radius, "y": cy - radius},
                            {"x": cx - radius, "y": cy + radius},
                            {"x": cx + radius, "y": cy - radius},
                            {"x": cx + radius, "y": cy + radius},
                        ])
        elif geometry_type == "ellipse":
            points = [geometry.get("center")]
            major = geometry.get("major_axis", geometry.get("majorAxis"))
            if isinstance(major, dict):
                try:
                    rx = abs(float(major.get("x", 0.0)))
                    ry = abs(float(major.get("y", 0.0)))
                except (TypeError, ValueError):
                    rx = ry = 0.0
                center = geometry.get("center")
                if isinstance(center, dict) and (rx > 0 or ry > 0):
                    try:
                        cx = float(center["x"])
                        cy = float(center["y"])
                    except (KeyError, TypeError, ValueError):
                        cx = cy = None
                    if cx is not None and cy is not None:
                        points.extend([
                            {"x": cx - rx, "y": cy - ry},
                            {"x": cx - rx, "y": cy + ry},
                            {"x": cx + rx, "y": cy - ry},
                            {"x": cx + rx, "y": cy + ry},
                        ])
        elif geometry_type == "spline":
            points = geometry.get("control_points") or geometry.get("vertices") or []
        for point in points:
            if not isinstance(point, dict):
                continue
            try:
                xs.append(float(point["x"]))
                ys.append(float(point["y"]))
            except (KeyError, TypeError, ValueError):
                continue
    if not xs or not ys:
        return None
    return (max(xs) - min(xs)), (max(ys) - min(ys))


def _scale_geometry(geometry: dict[str, Any], factor: float) -> dict[str, Any]:
    """Deep-copy one geometry with every metric field scaled (unit conversion)."""
    scaled = deepcopy(geometry)
    geometry_type = str(scaled.get("type") or "").lower()

    def scale_point(point: Any) -> None:
        if not isinstance(point, dict):
            return
        x = point.get("x")
        y = point.get("y")
        if isinstance(x, (int, float)):
            point["x"] = float(x) * factor
        if isinstance(y, (int, float)):
            point["y"] = float(y) * factor

    if geometry_type == "line":
        scale_point(scaled.get("start"))
        scale_point(scaled.get("end"))
    elif geometry_type == "polyline":
        for point in scaled.get("vertices") or []:
            scale_point(point)
    elif geometry_type in {"circle", "arc"}:
        scale_point(scaled.get("center"))
        if isinstance(scaled.get("radius"), (int, float)):
            scaled["radius"] = float(scaled["radius"]) * factor
    elif geometry_type == "ellipse":
        scale_point(scaled.get("center"))
        scale_point(scaled.get("major_axis", scaled.get("majorAxis")))
    elif geometry_type == "spline":
        for point in scaled.get("control_points") or []:
            scale_point(point)
    elif geometry_type == "text":
        scale_point(scaled.get("position"))
        if isinstance(scaled.get("height"), (int, float)):
            scaled["height"] = float(scaled["height"]) * factor
    return scaled


def _scale_geometries(
    geometries: list[dict[str, Any]], factor: float
) -> list[dict[str, Any]]:
    return [_scale_geometry(item, factor) for item in geometries]


def normalize_model_geometry_units(
    geometries: list[dict[str, Any]],
    project: dict[str, Any] | None,
    *,
    explicit_units: str | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Convert model-supplied variant geometry onto the mm convention.

    Deterministic paths emit millimetres while a model that writes geometry
    directly usually thinks in metres (as seen in model-authored spline
    candidates whose extent is ~4 m but are consumed as ~4 mm).  An explicit
    ``units`` declaration is honoured; otherwise the project's confirmed
    dimensions (in metres) are used as the reference: when the geometry
    extent is much closer to the metre value than to its 1000x millimetre
    value, the geometry is scaled to millimetres.

    Returns ``(geometries, note)`` where note describes what was applied.
    """
    if not geometries:
        return geometries, "no_geometries"
    if explicit_units == "mm":
        return geometries, "declared_mm"
    extent = _geometry_extent(geometries)
    if extent is None:
        return geometries, "no_extent"
    width, height = extent
    if width <= 0 or height <= 0:
        return geometries, "degenerate_extent"
    if explicit_units == "m":
        return _scale_geometries(geometries, 1000.0), "declared_m"
    if not isinstance(project, dict):
        return geometries, "no_project_reference"
    requirements = project.get("requirements") or {}
    dimensions = requirements.get("dimensions") if isinstance(requirements, dict) else {}
    if not isinstance(dimensions, dict):
        return geometries, "no_dimensions"
    refs: list[float] = []
    for key in ("width_m", "height_m"):
        value = dimensions.get(key)
        if isinstance(value, (int, float)) and value > 0:
            refs.append(float(value))
    # 圆的 extent 是直径量级（2r），radius 参照须按直径加入，否则
    # 圆/弧类直投几何会因尺寸量级差 2 倍被判为"毫米对齐"而不转换。
    for key in ("radius_m", "diameter_m"):
        value = dimensions.get(key)
        if isinstance(value, (int, float)) and value > 0:
            refs.append(float(value) * (2.0 if key == "radius_m" else 1.0))
    # 兜底：LLM 直投可能用非标准键名（total_height_m / arc_radius_m /
    # straight_side_height_m / leg_height_m），存量项目已按此落库时
    # 同样纳入参照，避免 height 与 width 参照缺失导致单位误判。
    for key, radius_like in (
        ("total_height_m", False),
        ("total_width_m", False),
        ("arc_radius_m", True),
        ("straight_side_height_m", False),
        ("leg_height_m", False),
    ):
        value = dimensions.get(key)
        if isinstance(value, (int, float)) and value > 0:
            refs.append(float(value) * (2.0 if radius_like else 1.0))
    if not refs:
        return geometries, "no_dimensions"
    ref_m = max(refs)
    size = max(width, height)
    error_m = abs(size - ref_m) / ref_m
    error_mm = abs(size - ref_m * 1000.0) / (ref_m * 1000.0)
    if error_m < 0.12 and error_m < error_mm:
        return _scale_geometries(geometries, 1000.0), "inferred_m"
    return geometries, "millimetre_aligned"


def candidate_response_payload(
    project: dict[str, Any],
    variant: dict[str, Any],
    preview: list[Any],
    drawing_json: dict[str, Any],
    *,
    restored: bool,
    layout_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the shared response contract for restored or generated candidates."""
    action_message = "已恢复现有候选方案" if restored else "候选方案已生成"
    response_text = (
        "候选方案已经生成，已恢复右侧路径预览。请选择方案后再进入路径规划。"
        if restored
        else "候选方案已生成，右侧已显示喷墨路径预览。"
        "请选择方案后再进行路径规划；本次没有启动小车。"
    )
    tool_result = {
        "name": "persist_candidate_variant",
        "ok": True,
        "message": action_message,
        "variant_id": variant.get("id"),
        "preview_paths": preview,
    }
    if not restored:
        tool_result["layout_validation"] = layout_validation
    payload = {
        "response_text": response_text,
        "tool_result": tool_result,
        "project_id": project["id"],
        "project": project,
        "variants": project.get("variants", [variant]),
        "variant": variant,
        "preview_paths": preview,
        "drawing_json": drawing_json,
        "next_action": "select_design_variant",
    }
    variant_summary = variant.get("acceptance_summary") if isinstance(variant, dict) else None
    if not isinstance(variant_summary, dict) and isinstance(variant, dict):
        record = variant.get("construction_record")
        variant_summary = record.get("acceptance_summary") if isinstance(record, dict) else None
    if isinstance(variant_summary, dict):
        payload["acceptance_summary"] = deepcopy(variant_summary)
    if layout_validation is not None:
        payload["layout_validation"] = layout_validation
    return payload


def candidate_generation_context(
    project: dict[str, Any], route: dict[str, Any]
) -> dict[str, Any]:
    """Resolve the deterministic expectations used to generate a candidate."""
    original_prompt = str(project.get("original_prompt") or "").strip()
    fallback_prompt = " ".join(
        value.strip()
        for value in (str(project.get("name") or ""), original_prompt)
        if value.strip()
    )
    prompt = original_prompt or fallback_prompt
    expected_template = recognize_drawing_template(prompt)
    template_set = recognize_drawing_template_set(prompt)
    if expected_template is None and fallback_prompt != prompt:
        expected_template = recognize_drawing_template(fallback_prompt)
    if not template_set and fallback_prompt != prompt:
        template_set = recognize_drawing_template_set(fallback_prompt)
    inferred = parameterize_design(prompt)
    if not inferred.get("ok") and fallback_prompt != prompt:
        inferred = parameterize_design(fallback_prompt)
    merged_requirements = merge_design_requirements(project, route)
    requirements = normalize_template_layout_for_matches(template_set, merged_requirements)
    for key in ("added_shapes", "additions", "annotations", "composition_contract", "composition_validation"):
        if key in merged_requirements:
            requirements[key] = deepcopy(merged_requirements[key])
    # Standard templates already have their own deterministic recognizer and
    # should not gain duplicate inferred fields.  This reconciliation is for
    # custom shapes (such as legacy heart-outline projects) only.
    if (
        inferred.get("ok")
        and inferred.get("shape")
        and expected_template is None
        and not template_set
    ):
        # Keep legacy projects compatible with newly supported natural-language
        # shapes.  Only fill fields absent from the persisted requirements.
        for key in (
            "shape",
            "dimensions",
            "dimension_bounds",
            "origin",
            "closed",
            "smooth",
            "symmetric",
            "self_intersection",
        ):
            if key not in requirements and key in inferred:
                requirements[key] = deepcopy(inferred[key])
    requested_quantity = requirements.get("quantity")
    composite_quantity = compose_template_instance_count(template_set)
    expected_quantity = (
        composite_quantity
        if composite_quantity is not None
        else max(1, min(50, int(requested_quantity)))
        if isinstance(requested_quantity, (int, float))
        else int(expected_template.get("quantity", 1))
        if isinstance(expected_template, dict)
        else 1
    )
    expected_template_name = (
        str(expected_template.get("template") or "")
        if isinstance(expected_template, dict)
        else str(requirements.get("shape") or requirements.get("drawing_type") or "")
    )
    return {
        "prompt": prompt,
        "expected_template": expected_template,
        "template_set": template_set,
        "requirements": requirements,
        "layout_conflicts": list(requirements.get("layout_conflicts") or []),
        "expected_quantity": expected_quantity,
        "expected_template_name": expected_template_name,
    }


def validate_candidate_geometries(
    geometries: list[dict[str, Any]], context: dict[str, Any]
) -> dict[str, Any]:
    """Validate generated geometry before a candidate is persisted."""
    requirements = context.get("requirements")
    requirements = requirements if isinstance(requirements, dict) else {}
    template_set = context.get("template_set")
    layout_instance_count = len(
        {
            item.get("template_instance")
            for item in geometries
            if isinstance(item, dict)
            and isinstance(item.get("template_instance"), int)
        }
    )
    layout_validation = None
    if (
        isinstance(template_set, list)
        and len(template_set) > 1
        and layout_instance_count == 2
    ):
        layout_validation = validate_template_layout(
            geometries,
            arrangement=requirements.get("arrangement"),
            spacing_m=(
                float(requirements["spacing_m"])
                if isinstance(requirements.get("spacing_m"), (int, float))
                else None
            ),
            peer_placement=requirements.get("peer_placement"),
        )
        if layout_validation.get("ok") is not True:
            errors = "、".join(
                str(item) for item in layout_validation.get("errors") or []
            )
            return {
                "ok": False,
                "message": "候选布局未通过几何校验，本次错误方案未保存。"
                + (errors or "请重新生成。"),
                "layout_instance_count": layout_instance_count,
                "layout_validation": layout_validation,
            }

    if isinstance(template_set, list) and len(template_set) > 1:
        expected_by_template = {
            str(item["template"]): max(1, min(50, int(item.get("quantity", 1))))
            * max(1, len(item.get("placement") or []))
            for item in template_set
        }
        expected_by_template[str(template_set[0]["template"])] = max(
            1, min(50, int(template_set[0].get("quantity", 1)))
        )
        actual_instances: dict[str, set[int]] = {}
        for item in geometries:
            template_type = str(item.get("template_type") or "")
            instance = item.get("template_instance")
            if template_type and isinstance(instance, int):
                actual_instances.setdefault(template_type, set()).add(instance)
        actual_by_template = {
            key: len(values) for key, values in actual_instances.items()
        }
        if any(
            actual_by_template.get(key, 0) != count
            for key, count in expected_by_template.items()
        ):
            expected_text = "、".join(
                f"{count} 个{DRAWING_TEMPLATE_SKILLS.get(key, {}).get('label', key)}"
                for key, count in expected_by_template.items()
            )
            actual_text = "、".join(
                f"{count} 个{DRAWING_TEMPLATE_SKILLS.get(key, {}).get('label', key)}"
                for key, count in actual_by_template.items()
            ) or "无有效场地图形"
            return {
                "ok": False,
                "message": (
                    f"候选方案与已确认需求不一致：需要 {expected_text}，"
                    f"实际生成 {actual_text}。本次错误方案未保存，请重新生成。"
                ),
                "layout_instance_count": layout_instance_count,
                "layout_validation": layout_validation,
            }

    if str(requirements.get("printer") or "center") != "center":
        return {
            "ok": False,
            "message": "当前版本仅支持中心喷码机，无法生成可执行候选方案。",
            "layout_instance_count": layout_instance_count,
            "layout_validation": layout_validation,
        }
    assessment = score_design_variant(geometries)
    feasibility = assessment.get("feasibility") or {}
    if feasibility.get("ok") is not True:
        errors = "、".join(str(item) for item in feasibility.get("errors") or [])
        return {
            "ok": False,
            "message": "候选几何未通过可制造性检查，暂不生成路径。" + errors,
            "layout_instance_count": layout_instance_count,
            "layout_validation": layout_validation,
            "assessment": assessment,
        }
    return {
        "ok": True,
        "layout_instance_count": layout_instance_count,
        "layout_validation": layout_validation,
        "assessment": assessment,
    }


def design_geometries_for_project(
    project: dict[str, Any], route: dict[str, Any]
) -> tuple[list[dict[str, Any]] | None, list[str]]:
    """Build deterministic supported geometry for a project candidate."""
    source = project.get("source_drawing")
    source_geometries = source.get("geometries") if isinstance(source, dict) else None
    if (
        isinstance(source_geometries, list)
        and source_geometries
        and not list(project.get("variants") or [])
    ):
        return deepcopy(source_geometries), []

    requirements = merge_design_requirements(project, route)
    original_prompt = str(project.get("original_prompt") or "").strip()
    fallback_prompt = " ".join(
        value.strip()
        for value in (str(project.get("name") or ""), original_prompt)
        if value.strip()
    )
    prompt = original_prompt or fallback_prompt
    inferred = parameterize_design(prompt)
    if inferred.get("ok") and inferred.get("shape"):
        # Older projects may have been persisted before a newly supported
        # natural-language shape was added.  Refresh only missing fields so
        # confirmed user edits remain authoritative.
        for key in (
            "shape",
            "dimensions",
            "dimension_bounds",
            "origin",
            "closed",
            "smooth",
            "symmetric",
            "self_intersection",
        ):
            if key not in requirements and key in inferred:
                requirements[key] = deepcopy(inferred[key])
    # Templates are compiled and executed through the same strict IR as LLM plans.
    from .cad_template_plan import interpret_template_project
    interpretation = interpret_template_project(project, route)
    if interpretation is not None:
        return interpretation["trial_result"]["geometries"], []

    shape = str(requirements.get("shape") or "").lower()
    dimensions = requirements.get("dimensions")
    dimensions = dimensions if isinstance(dimensions, dict) else {}
    if shape in {
        "closed_semicircular_arch", "semicircular_arch", "arch", "半圆拱门", "拱门",
    }:
        width = dimensions.get("width_m")
        height = dimensions.get("height_m")
        if (
            isinstance(width, (int, float))
            and isinstance(height, (int, float))
            and float(width) > 0
            and float(height) > 0
        ):
            width_mm = float(width) * 1000.0
            height_mm = float(height) * 1000.0
            radius_mm = width_mm / 2.0
            leg_height_mm = height_mm - radius_mm
            if leg_height_mm < 0:
                return None, ["拱门总高度不能小于半圆半径（宽度的一半）"]
            left_x = -radius_mm
            right_x = radius_mm
            return [
                {
                    "id": 1,
                    "type": "line",
                    "layer_id": 1,
                    "start": {"x": left_x, "y": 0.0, "z": 0.0},
                    "end": {"x": left_x, "y": leg_height_mm, "z": 0.0},
                    "label": "左侧竖边",
                },
                {
                    "id": 2,
                    "type": "arc",
                    "layer_id": 1,
                    "center": {"x": 0.0, "y": leg_height_mm, "z": 0.0},
                    "radius": radius_mm,
                    "start_angle": 0.0,
                    "end_angle": 180.0,
                    "label": "顶部半圆弧",
                },
                {
                    "id": 3,
                    "type": "line",
                    "layer_id": 1,
                    "start": {"x": right_x, "y": leg_height_mm, "z": 0.0},
                    "end": {"x": right_x, "y": 0.0, "z": 0.0},
                    "label": "右侧竖边",
                },
                {
                    "id": 4,
                    "type": "line",
                    "layer_id": 1,
                    "start": {"x": right_x, "y": 0.0, "z": 0.0},
                    "end": {"x": left_x, "y": 0.0, "z": 0.0},
                    "label": "底边",
                },
            ], []
        return None, ["拱门总宽度和总高度"]
    if shape in {"rectangle", "rect", "长方形", "矩形"}:
        width = dimensions.get("width_m")
        height = dimensions.get("height_m")
        if isinstance(width, (int, float)) and isinstance(height, (int, float)):
            return [
                {
                    "id": 1,
                    "type": "polyline",
                    "layer_id": 1,
                    "vertices": [
                        {"x": 0.0, "y": 0.0, "z": 0.0},
                        {"x": float(width) * 1000.0, "y": 0.0, "z": 0.0},
                        {
                            "x": float(width) * 1000.0,
                            "y": float(height) * 1000.0,
                            "z": 0.0,
                        },
                        {"x": 0.0, "y": float(height) * 1000.0, "z": 0.0},
                    ],
                    "closed": True,
                }
            ], []
        return None, ["矩形宽度和高度"]
    if shape in {"heart_outline", "heart", "爱心", "心形", "心型"}:
        width = dimensions.get("width_m")
        height = dimensions.get("height_m")
        if (
            isinstance(width, (int, float))
            and isinstance(height, (int, float))
            and float(width) > 0
            and float(height) > 0
        ):
            return [heart_outline_geometry(float(width), float(height))], []
        return None, ["爱心轮廓宽度和高度"]
    if shape in {"circle", "圆", "圆形"}:
        radius = dimensions.get("radius_m")
        if isinstance(radius, (int, float)) and float(radius) > 0:
            radius_mm = float(radius) * 1000.0
            return [
                {
                    "id": 1,
                    "type": "polyline",
                    "layer_id": 1,
                    "vertices": [
                        {
                            "x": radius_mm * math.cos(2 * math.pi * index / 64),
                            "y": radius_mm * math.sin(2 * math.pi * index / 64),
                            "z": 0.0,
                        }
                        for index in range(64)
                    ],
                    "closed": True,
                }
            ], []
        return None, ["圆形半径"]
    return None, ["图形类型和关键尺寸"]


def project_logical_graph(
    project: dict[str, Any],
    match: dict[str, Any],
    geometries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Preserve valid imported semantics or create a stable selectable root."""
    source = project.get("source_drawing")
    if isinstance(source, dict):
        source_objects = source.get("logical_objects")
        source_topology = source.get("topology")
        if isinstance(source_objects, list) and source_objects:
            validation = validate_logical_object_graph(
                geometries,
                source_objects,
                source_topology if isinstance(source_topology, dict) else {},
            )
            if validation.get("verified") is True:
                return {
                    "logical_objects": deepcopy(source_objects),
                    "topology": deepcopy(source_topology or {}),
                }
        match = dict(match)
        match.setdefault("template", "imported_cad")
        match.setdefault("quantity", 1)
    return build_template_logical_object_graph(match, geometries)


def template_instance_assessment(
    geometries: list[dict[str, Any]],
    template: str,
    *,
    source_drawing: dict[str, Any] | None = None,
    allow_legacy_migration: bool = False,
    expected_geometries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tagged = {
        int(item["template_instance"])
        for item in geometries
        if isinstance(item, dict)
        and isinstance(item.get("template_instance"), (int, float))
    }
    fully_tagged = bool(geometries) and all(
        isinstance(item, dict)
        and isinstance(item.get("template_instance"), (int, float))
        and int(item["template_instance"]) >= 1
        for item in geometries
    )
    if fully_tagged:
        return {
            "count": len(tagged),
            "status": "authoritative",
            "source": "stable_instance_ids",
            "authoritative": True,
            "geometry_count": len(geometries),
        }

    source = source_drawing if isinstance(source_drawing, dict) else {}
    if str(source.get("source_format") or "").lower() in {"dxf", "dwg", "image"}:
        analysis = source.get("cad_analysis")
        analysis = analysis if isinstance(analysis, dict) else {}
        groups = analysis.get("instance_groups")
        if (
            analysis.get("instance_groups_confirmed") is True
            and isinstance(groups, list)
            and groups
        ):
            return {
                "count": len(groups),
                "status": "authoritative",
                "source": "confirmed_cad_groups",
                "authoritative": True,
                "geometry_count": len(geometries),
                "groups": deepcopy(groups),
            }
        return {
            "count": None,
            "status": "confirmation_required",
            "source": "cad_grouping_unconfirmed",
            "authoritative": False,
            "geometry_count": len(geometries),
            "message": "导入图纸尚未确认实例分组，不能判定数量是否满足要求。",
        }

    expected_geometry_count = template_geometry_count(template)
    migrated = deepcopy(geometries)
    legacy_count: int | None = None
    if (
        allow_legacy_migration
        and not tagged
        and isinstance(expected_geometries, list)
        and len(expected_geometries) == len(migrated)
        and preview_paths({"lines": expected_geometries})
        == preview_paths({"lines": migrated})
    ):
        expected_ids = {
            str(item.get("id")): item
            for item in expected_geometries
            if isinstance(item, dict) and item.get("id") is not None
        }
        for index, item in enumerate(migrated):
            expected = expected_ids.get(str(item.get("id")))
            if expected is None and index < len(expected_geometries):
                expected = expected_geometries[index]
            item["template_instance"] = int(expected.get("template_instance", 1))
            item["template_type"] = str(
                expected.get("template_type") or template
            )
        legacy_count = len(
            {int(item["template_instance"]) for item in migrated}
        )
    if legacy_count is not None:
        return {
            "count": legacy_count,
            "status": "migrated",
            "source": "legacy_template_migration",
            "authoritative": True,
            "geometry_count": len(geometries),
            "migrated_geometries": migrated,
        }

    estimated = (
        len(geometries) // expected_geometry_count
        if expected_geometry_count > 0 and geometries
        else 0
    )
    return {
        "count": estimated or None,
        "status": "estimated",
        "source": "geometry_count_hint",
        "authoritative": False,
        "geometry_count": len(geometries),
        "message": "仅根据几何条数估算实例数量，不能用于候选方案通过判定。",
    }


def template_instance_count(
    geometries: list[dict[str, Any]], template: str
) -> int:
    assessment = template_instance_assessment(geometries, template)
    return int(assessment.get("count") or 0)


def scale_factor_from_message(message: str) -> float | None:
    """Parse common whole-design scale requests without model ambiguity."""
    normalized = re.sub(r"[\s，。！？、,!?；;：:]+", "", message.lower())
    chinese_numbers = {"一": 1.0, "二": 2.0, "两": 2.0, "三": 3.0}
    if "缩小一半" in normalized or "缩小到一半" in normalized:
        return 0.5
    percent = re.search(r"(扩大|放大|缩小)(到|为)?(\d+(?:\.\d+)?)%", normalized)
    if percent:
        value = float(percent.group(3)) / 100.0
        if percent.group(2):
            return value
        return 1.0 - value if percent.group(1) == "缩小" else 1.0 + value
    multiple = re.search(
        r"(扩大|放大|缩小)(到|为)?(\d+(?:\.\d+)?|一|二|两|三)倍",
        normalized,
    )
    if not multiple:
        return None
    raw_value = multiple.group(3)
    value = (
        float(raw_value)
        if raw_value[0].isdigit()
        else chinese_numbers.get(raw_value, 0.0)
    )
    if value <= 0:
        return None
    if multiple.group(1) == "缩小":
        return 1.0 / (2.0 if value == 1.0 else value)
    return 2.0 if value == 1.0 else value


def effective_parent_variant(
    project: dict[str, Any],
    parent_variant_id: str | None = None,
    preferred_variant_id: str | None = None,
) -> dict[str, Any] | None:
    variants = project.get("variants")
    if not isinstance(variants, list):
        return None
    variants = [item for item in variants if candidate_is_accepted(item)]
    effective_id = (
        parent_variant_id
        or preferred_variant_id
        or project.get("design_base_variant_id")
        or project.get("selected_variant_id")
    )
    if effective_id:
        return next(
            (
                item
                for item in variants
                if isinstance(item, dict) and item.get("id") == effective_id
            ),
            None,
        )
    return variants[0] if len(variants) == 1 and isinstance(variants[0], dict) else None


def scale_geometries(
    geometries: list[dict[str, Any]], factor: float
) -> list[dict[str, Any]]:
    paths = preview_paths({"lines": geometries})
    points = [point for path in paths for point in path if len(point) >= 2]
    if not points:
        return []
    center_x = (
        min(point[0] for point in points) + max(point[0] for point in points)
    ) * 500.0
    center_y = (
        min(point[1] for point in points) + max(point[1] for point in points)
    ) * 500.0
    scaled = deepcopy(geometries)

    def scale_point(point: Any, *, vector: bool = False) -> None:
        if not isinstance(point, dict):
            return
        try:
            x, y = float(point["x"]), float(point["y"])
        except (KeyError, TypeError, ValueError):
            return
        point["x"] = x * factor if vector else center_x + (x - center_x) * factor
        point["y"] = y * factor if vector else center_y + (y - center_y) * factor

    for geometry in scaled:
        geometry_type = str(geometry.get("type") or "").lower()
        for key in ("start", "end", "center", "position"):
            scale_point(geometry.get(key))
        for key in ("vertices", "control_points"):
            values = geometry.get(key)
            if isinstance(values, list):
                for point in values:
                    scale_point(point)
        if geometry_type == "ellipse":
            scale_point(geometry.get("major_axis"), vector=True)
        if geometry_type in {"circle", "arc"} and isinstance(
            geometry.get("radius"), (int, float)
        ):
            geometry["radius"] = float(geometry["radius"]) * factor
        if geometry_type == "text" and isinstance(
            geometry.get("height"), (int, float)
        ):
            geometry["height"] = float(geometry["height"]) * factor
    return scaled
