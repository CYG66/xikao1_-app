from __future__ import annotations

import math
import os
import re
import hashlib
import json
from copy import deepcopy
from typing import Any

from .config import MAX_TASK_LINEAR_VELOCITY, WHEEL_BASE_M
from .cad_import import PATH_SEMANTIC_TO_ROLE, ROLE_TO_PATH_SEMANTIC
from .drawing_commands import (
    build_command_rollback_evidence,
    build_drawing_command_batch,
)
from .drawing_store import preview_paths
from .geometry_catalog import build_geometry_catalog
from .geometry_diff import build_geometry_diff, build_path_impact
from .mission_analysis import segment_length_m
from .state import robot_state


def validate_preview_paths(paths: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate and normalize the path contract consumed by the App preview.

    The planner owns travel generation.  The Agent may only label a path as
    printing when it is explicitly marked as such; unknown route types are
    rejected instead of being silently rendered as travel.
    """
    errors: list[str] = []
    warnings: list[str] = []
    normalized: list[dict[str, Any]] = []
    allowed_types = {"printing", "transition", "drawing", "planned"}

    for index, raw in enumerate(paths, start=1):
        if not isinstance(raw, dict):
            errors.append(f"第 {index} 段路径不是对象")
            continue
        route_type = str(raw.get("route_type") or "").strip().lower()
        if route_type not in allowed_types:
            errors.append(f"第 {index} 段路径缺少有效 route_type")
            continue
        points = raw.get("points")
        if not isinstance(points, list) or len(points) < 2:
            errors.append(f"第 {index} 段路径至少需要两个点")
            continue
        frame_id = str(raw.get("frame_id") or "map").strip()
        if not frame_id:
            errors.append(f"第 {index} 段路径缺少 frame_id")
            continue
        clean_points: list[list[float]] = []
        invalid_point = False
        for point_index, point in enumerate(points, start=1):
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                errors.append(f"第 {index} 段路径第 {point_index} 个点无效")
                invalid_point = True
                break
            try:
                x, y = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                invalid_point = True
                errors.append(f"第 {index} 段路径第 {point_index} 个点坐标无效")
                break
            if not math.isfinite(x) or not math.isfinite(y):
                invalid_point = True
                errors.append(f"第 {index} 段路径第 {point_index} 个点包含非有限数值")
                break
            clean_points.append([x, y])
        if invalid_point:
            continue
        canonical_type = {
            "drawing": "printing",
            "planned": "transition",
        }.get(route_type, route_type)
        normalized_item = {
            "namespace": str(raw.get("namespace") or "agent_preview"),
            "frame_id": frame_id,
            "route_type": canonical_type,
            "points": clean_points,
        }
        if isinstance(raw.get("color"), dict):
            normalized_item["color"] = dict(raw["color"])
        geometry_id = raw.get("geometry_id")
        if isinstance(geometry_id, int) and geometry_id > 0:
            normalized_item["geometry_id"] = geometry_id
        normalized.append(normalized_item)

    printing_count = sum(item["route_type"] == "printing" for item in normalized)
    transition_count = sum(item["route_type"] == "transition" for item in normalized)
    return {
        "ok": not errors and bool(normalized),
        "errors": errors or ([] if normalized else ["没有有效路径"]),
        "warnings": warnings,
        "paths": normalized,
        "summary": {
            "path_count": len(normalized),
            "printing_path_count": printing_count,
            "transition_path_count": transition_count,
            "frame_ids": sorted({item["frame_id"] for item in normalized}),
        },
    }


def inspect_drawing(geometries: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a read-only, machine-readable CAD inspection report."""
    items = [item for item in geometries if isinstance(item, dict)]
    type_counts: dict[str, int] = {}
    layer_counts: dict[str, int] = {}
    for item in items:
        geometry_type = str(item.get("type") or "unknown").lower()
        type_counts[geometry_type] = type_counts.get(geometry_type, 0) + 1
        layer = str(item.get("layer_id", item.get("layer", "unassigned")))
        layer_counts[layer] = layer_counts.get(layer, 0) + 1
    paths = preview_paths({"lines": items})
    bounds = calculate_geometry_bounds(items)
    topology = analyze_geometry_topology(items)
    topology_errors = list(topology.get("errors") or [])
    return {
        "ok": bool(items) and bounds.get("ok", False) and not topology_errors,
        "contract_version": "cad-inspect-1.0",
        "entity_count": len(items),
        "type_counts": dict(sorted(type_counts.items())),
        "layer_counts": dict(sorted(layer_counts.items())),
        "preview_path_count": len(paths),
        "bounds": bounds.get("bounds"),
        "boundary_check": bounds,
        "topology": topology,
        "errors": list(dict.fromkeys(
            list(bounds.get("errors") or []) + topology_errors
        )),
        "warnings": list(dict.fromkeys(
            list(bounds.get("warnings") or []) + list(topology.get("warnings") or [])
        )),
    }


def list_elements(
    geometries: list[dict[str, Any]],
    *,
    instance_ids: list[int] | None = None,
    semantic: str | None = None,
) -> dict[str, Any]:
    """List stable CAD instances and elements for locate-then-edit workflows."""
    catalog = build_geometry_catalog(geometries)
    requested_instances: set[int] = set()
    for value in instance_ids or []:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            requested_instances.add(parsed)
    semantic_query = str(semantic or "").strip().casefold()

    instances = [
        dict(item) for item in catalog.get("instances", [])
        if isinstance(item, dict)
        and (not requested_instances or item.get("instance_id") in requested_instances)
    ]
    allowed_instances = {
        item.get("instance_id") for item in instances if item.get("instance_id") is not None
    }
    elements = [
        dict(item) for item in catalog.get("elements", [])
        if isinstance(item, dict)
        and (
            not requested_instances
            or item.get("instance_id") in allowed_instances
        )
        and (
            not semantic_query
            or semantic_query in str(item.get("semantic") or "").casefold()
        )
    ]
    if semantic_query:
        matched_instance_ids = {
            item.get("instance_id") for item in elements
            if item.get("instance_id") is not None
        }
        instances = [
            item for item in instances
            if item.get("instance_id") in matched_instance_ids
            or semantic_query in str(item.get("semantic") or "").casefold()
        ]

    return {
        "ok": True,
        "schema": "cad.element-list.v1",
        "unit": catalog.get("unit", "m"),
        "filters": {
            "instance_ids": sorted(requested_instances),
            "semantic": str(semantic or "").strip() or None,
        },
        "instances": instances,
        "elements": elements,
        "instance_count": len(instances),
        "element_count": len(elements),
        "source_element_count": catalog.get("element_count", 0),
        "truncated": bool(catalog.get("truncated")),
        "execution_allowed": False,
    }


def validate_drawing(geometries: list[dict[str, Any]]) -> dict[str, Any]:
    """Run the deterministic drawing gate before preview or execution."""
    result = check_drawing_feasibility(geometries)
    return {
        "ok": bool(result.get("ok")),
        "contract_version": "cad-validate-1.0",
        "status": "valid" if result.get("ok") else "invalid",
        "feasibility": result,
        "errors": list(result.get("errors") or []),
        "warnings": list(result.get("warnings") or []),
        "execution_allowed": False,
        "next_action": "preview_paths" if result.get("ok") else "fix_geometry",
    }


def diff_drawings(
    source: list[dict[str, Any]], target: list[dict[str, Any]]
) -> dict[str, Any]:
    """Compare two geometry revisions and describe path impact."""
    geometry_diff = build_geometry_diff(source, target)
    path_impact = build_path_impact(source, target)
    return {
        "ok": True,
        "contract_version": "cad-diff-1.0",
        "geometry_diff": geometry_diff,
        "path_impact": path_impact,
        "requires_replan": bool(path_impact.get("requires_replan")),
        "execution_allowed": False,
    }


def snapshot_drawing(
    geometries: list[dict[str, Any]], label: str = ""
) -> dict[str, Any]:
    """Create a deterministic JSON snapshot reference, without writing files."""
    canonical = json.dumps(
        geometries, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    paths = preview_paths({"lines": geometries})
    lengths = [
        round(sum(
            math.hypot(float(end[0]) - float(start[0]), float(end[1]) - float(start[1]))
            for start, end in zip(path, path[1:])
        ), 4)
        for path in paths
    ]
    return {
        "ok": bool(geometries),
        "contract_version": "cad-snapshot-1.0",
        "snapshot_id": f"cad_{digest[:16]}",
        "sha256": digest,
        "label": label.strip(),
        "entity_count": len(geometries),
        "path_count": len(paths),
        "path_lengths_m": lengths,
        "geometry_ids": [item.get("id") for item in geometries if isinstance(item, dict)],
        "persisted": False,
        "execution_allowed": False,
    }


def apply_drawing_modifications(source: list[dict[str, Any]], operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply an explicit edit batch atomically and return command records.

    Edits are evaluated on a working copy.  A failed operation never leaks a
    partially modified drawing to the caller, which keeps Preview/Apply and
    later persistence decisions deterministic.
    """
    original = [dict(item) for item in source if isinstance(item, dict)]
    geometries = [dict(item) for item in original]
    applied, command_records, errors = [], [], []

    def validate_geometry(value: Any, label: str) -> list[str]:
        if not isinstance(value, dict):
            return [f"{label}必须是对象"]
        geometry_type = str(value.get("type", "")).lower()
        if geometry_type not in {"line", "polyline", "circle", "arc", "ellipse", "spline", "text"}:
            return [f"{label} type 无效：{geometry_type or '空'}"]
        geometry_id = as_id(value.get("id"))
        if geometry_id is None:
            return [f"{label}缺少有效 id"]

        def point(point_value: Any, point_label: str) -> list[str]:
            if not isinstance(point_value, dict):
                return [f"{label}.{point_label}必须是点对象"]
            missing = [key for key in ("x", "y") if key not in point_value]
            if missing:
                return [f"{label}.{point_label}缺少坐标：{','.join(missing)}"]
            try:
                coordinates = [float(point_value[key]) for key in ("x", "y")]
                if "z" in point_value:
                    coordinates.append(float(point_value["z"]))
            except (TypeError, ValueError):
                return [f"{label}.{point_label}坐标不是数字"]
            return [] if all(math.isfinite(item) for item in coordinates) else [f"{label}.{point_label}坐标不是有限值"]

        if geometry_type == "line":
            return point(value.get("start"), "start") + point(value.get("end"), "end")
        if geometry_type in {"polyline", "spline"}:
            key = "vertices" if geometry_type == "polyline" else "control_points"
            values = value.get(key)
            if not isinstance(values, list) or len(values) < 2:
                return [f"{label}.{key}至少需要 2 个点"]
            result: list[str] = []
            for index, item in enumerate(values):
                result.extend(point(item, f"{key}[{index}]"))
            return result
        if geometry_type == "text":
            result = point(value.get("position"), "position")
            content = value.get("content")
            if not isinstance(content, str) or not content.strip():
                result.append(f"{label}.content 不能为空")
            return result
        result = point(value.get("center"), "center")
        if geometry_type == "ellipse":
            result.extend(point(value.get("major_axis"), "major_axis"))
        try:
            radius = float(value.get("radius")) if geometry_type in {"circle", "arc"} else 1.0
            if geometry_type in {"circle", "arc"} and (not math.isfinite(radius) or radius <= 0):
                result.append(f"{label}.radius 必须大于 0")
        except (TypeError, ValueError):
            result.append(f"{label}.radius 不是数字")
        return result

    def as_id(value: Any) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    for index, operation in enumerate(operations, 1):
        if not isinstance(operation, dict):
            errors.append(f"第 {index} 个操作必须是对象")
            continue
        kind = str(operation.get("op", operation.get("operation", ""))).lower()
        geometry_id = as_id(operation.get("id"))
        position = (
            next(
                (i for i, item in enumerate(geometries) if as_id(item.get("id")) == geometry_id),
                None,
            )
            if geometry_id is not None
            else None
        )
        if kind == "add":
            geometry = operation.get("geometry")
            new_id = as_id(geometry.get("id")) if isinstance(geometry, dict) else None
            if not isinstance(geometry, dict) or new_id is None:
                errors.append(f"第 {index} 个新增操作缺少有效 geometry")
                continue
            geometry_errors = validate_geometry(geometry, f"第 {index} 个新增几何")
            if geometry_errors:
                errors.extend(geometry_errors)
                continue
            item = dict(geometry)
            item["id"] = new_id
            if any(as_id(existing.get("id")) == new_id for existing in geometries):
                errors.append(f"第 {index} 个新增几何 ID {new_id} 已存在")
                continue
            geometries.append(item)
            applied.append({"op": "add", "id": new_id})
            command_records.append({"op": "add", "id": new_id, "before": None, "after": deepcopy(item)})
        elif kind == "update":
            geometry = operation.get("geometry")
            if geometry_id is None or position is None or not isinstance(geometry, dict):
                errors.append(f"第 {index} 个更新目标 ID {geometry_id or '?'} 无效")
                continue
            # The operation ID is authoritative, so legacy callers may omit it
            # from the replacement payload.
            candidate = dict(geometry)
            candidate["id"] = geometry_id
            geometry_errors = validate_geometry(candidate, f"第 {index} 个更新几何")
            if geometry_errors:
                errors.extend(geometry_errors)
                continue
            before = deepcopy(geometries[position])
            item = candidate
            item["id"] = geometry_id
            geometries[position] = item
            applied.append({"op": "update", "id": geometry_id})
            command_records.append({"op": "update", "id": geometry_id, "before": before, "after": deepcopy(item)})
        elif kind == "remove":
            if position is None:
                errors.append(f"第 {index} 个删除目标 ID {geometry_id} 不存在")
                continue
            before = deepcopy(geometries[position])
            geometries.pop(position)
            applied.append({"op": "remove", "id": geometry_id})
            command_records.append({"op": "remove", "id": geometry_id, "before": before, "after": None})
        else:
            errors.append(f"第 {index} 个操作类型无效：{kind or '空'}")
    if errors or not geometries:
        return {
            "ok": False,
            "geometries": original,
            "applied_operations": [],
            "commands": [],
            "rolled_back": bool(applied),
            "rollback_evidence": build_command_rollback_evidence(
                original,
                applied_command_count=len(applied),
                triggered=bool(applied),
            ),
            "errors": errors or ["修改后没有剩余几何"],
        }
    command_batch = build_drawing_command_batch(original, command_records)
    if not command_batch["verified"]:
        return {
            "ok": False,
            "geometries": original,
            "applied_operations": [],
            "commands": [],
            "command_batch": command_batch,
            "rolled_back": True,
            "rollback_evidence": command_batch["execution"].get("rollback_evidence"),
            "errors": list(command_batch["execution"]["errors"]),
        }
    return {
        "ok": True,
        "geometries": command_batch["execution"]["geometries"],
        "applied_operations": applied,
        "commands": command_batch["commands"],
        "command_batch": command_batch,
        "rolled_back": False,
        "errors": [],
    }


# Drawing editor templates are also local Agent skills.  Keeping the aliases
# and dimensions here makes template recognition independent of an LLM call.
DRAWING_TEMPLATE_SKILLS: dict[str, dict[str, Any]] = {
    "room": {
        "label": "矩形房间",
        "aliases": ("矩形房间", "房间", "矩形室内", "room"),
        "category": "建筑",
        "width_m": 6.0,
        "height_m": 4.0,
    },
    "two_rooms": {
        "label": "两室布局",
        "aliases": ("两室布局", "两室", "双房间", "two rooms"),
        "category": "建筑",
        "width_m": 8.0,
        "height_m": 6.0,
    },
    "corridor": {
        "label": "长走廊",
        "aliases": ("长走廊", "走廊", "通道", "corridor"),
        "category": "建筑",
        "width_m": 12.0,
        "height_m": 2.0,
    },
    "parking": {
        "label": "标准车位",
        "aliases": ("标准车位", "单个车位", "停车位", "车位", "parking spot"),
        "category": "场地",
        "width_m": 2.5,
        "height_m": 5.0,
    },
    "parking_lot": {
        "label": "停车场",
        "aliases": ("停车场", "停车区", "停车位阵列", "parking lot"),
        "category": "场地",
        "width_m": 12.0,
        "height_m": 6.0,
    },
    "basketball": {
        "label": "篮球场",
        "aliases": ("篮球场", "篮球场地", "basketball court"),
        "category": "场地",
        "width_m": 28.0,
        "height_m": 15.0,
    },
    "badminton": {
        "label": "羽毛球场",
        "aliases": ("羽毛球场", "羽毛球场地", "badminton court"),
        "category": "场地",
        "width_m": 13.4,
        "height_m": 6.1,
    },
    "warehouse": {
        "label": "仓库网格",
        "aliases": ("仓库网格", "仓库", "仓储网格", "warehouse"),
        "category": "施工",
        "width_m": 20.0,
        "height_m": 12.0,
    },
    "grid": {
        "label": "施工轴网",
        "aliases": ("施工轴网", "轴网", "网格", "grid"),
        "category": "施工",
        "width_m": 4.0,
        "height_m": 4.0,
    },
    "foundation": {
        "label": "圆形基础",
        "aliases": ("圆形基础", "圆基础", "基础圆", "circular foundation"),
        "category": "施工",
        "radius_m": 3.0,
    },
}


def _positive_quantity_before_template(
    prompt: str, aliases: tuple[str, ...]
) -> int:
    normalized = prompt.lower()
    alias_pattern = "|".join(
        re.escape(alias.lower()) for alias in sorted(aliases, key=len, reverse=True)
    )
    match = re.search(
        r"(?P<count>\d+|[一二两三四五六七八九十]+)\s*"
        rf"(?:个|组)?\s*(?:(?:标准|并排|并列|相邻|相连|连续|的)\s*){{0,6}}(?:{alias_pattern})",
        normalized,
    )
    if match is None:
        return 1
    raw = match.group("count")
    if raw.isdigit():
        return max(1, min(50, int(raw)))
    digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
    if raw == "十":
        value = 10
    elif "十" in raw:
        left, right = raw.split("十", 1)
        value = digits.get(left, 1) * 10 + digits.get(right, 0)
    else:
        value = digits.get(raw, 1)
    return max(1, min(50, value))


def _template_layout_requirements(prompt: str) -> dict[str, Any]:
    normalized = prompt.lower()
    number_pattern = r"\d+(?:\.\d+)?|[一二两三四五六七八九十]+"
    unit_pattern = r"米|m|厘米|cm|毫米|mm"
    spacing_name = r"间距|间隔|净距|相隔|距离"
    spacing = re.search(
        rf"(?:{spacing_name})\s*(?:改成|改为|调整为|调成|设为|设置为|变成|为|是)?\s*"
        rf"(?P<value>{number_pattern})\s*(?P<unit>{unit_pattern})?",
        normalized,
    )
    if spacing is None:
        spacing = re.search(
            rf"(?P<value>{number_pattern})\s*(?P<unit>{unit_pattern})\s*"
            rf"(?:的)?\s*(?:{spacing_name})",
            normalized,
        )
    result: dict[str, Any] = {}
    layout_conflicts: list[str] = []

    # "间距不变/保持原间距" is an explicit instruction to inherit the
    # displayed candidate's spacing. It must not be treated as a missing
    # numeric parameter or silently fall back to a template default.
    if re.search(
        rf"(?:{spacing_name}).{{0,8}}(?:为|改成|改为|调整为|设为|保持|维持|沿用)?"
        r"(?:不变|保持原样|保持原间距|维持原间距|沿用原间距)",
        normalized,
    ) or re.search(
        r"(?:不变|保持原样|保持原间距|维持原间距|沿用原间距).{0,8}"
        rf"(?:{spacing_name})",
        normalized,
    ):
        result["preserve_spacing"] = True

    # A single message may accidentally contain two competing numeric gaps.
    # Keep the first value for display compatibility, but mark the request as
    # ambiguous so the orchestration layer can ask instead of saving a guess.
    all_spacing_patterns = (
        rf"(?:{spacing_name})\s*(?:改成|改为|调整为|调成|设为|设置为|变成|为|是)?\s*"
        rf"(?P<value>{number_pattern})\s*(?P<unit>{unit_pattern})?",
        rf"(?P<value>{number_pattern})\s*(?P<unit>{unit_pattern})?\s*"
        rf"(?:的)?\s*(?:{spacing_name})",
    )
    spacing_values: set[float] = set()
    for pattern in all_spacing_patterns:
        for match in re.finditer(pattern, normalized):
            raw_value = match.group("value")
            chinese_digits = {
                "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
                "六": 6, "七": 7, "八": 8, "九": 9,
            }
            if raw_value.replace(".", "", 1).isdigit():
                numeric_value = float(raw_value)
            elif raw_value == "十":
                numeric_value = 10.0
            elif "十" in raw_value:
                left, right = raw_value.split("十", 1)
                numeric_value = float(
                    chinese_digits.get(left, 1) * 10 + chinese_digits.get(right, 0)
                )
            else:
                numeric_value = float(chinese_digits.get(raw_value, 0))
            factor = {
                "厘米": 0.01, "cm": 0.01,
                "毫米": 0.001, "mm": 0.001,
            }.get(match.group("unit") or "米", 1.0)
            if numeric_value > 0:
                spacing_values.add(round(numeric_value * factor, 4))
    if len(spacing_values) > 1:
        layout_conflicts.append("同一条要求包含多个不同间距值")
    if spacing:
        raw_value = spacing.group("value")
        chinese_digits = {
            "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9,
        }
        if raw_value.replace(".", "", 1).isdigit():
            numeric_value = float(raw_value)
        elif raw_value == "十":
            numeric_value = 10.0
        elif "十" in raw_value:
            left, right = raw_value.split("十", 1)
            numeric_value = float(
                chinese_digits.get(left, 1) * 10 + chinese_digits.get(right, 0)
            )
        else:
            numeric_value = float(chinese_digits.get(raw_value, 0))
        factor = {
            "厘米": 0.01,
            "cm": 0.01,
            "毫米": 0.001,
            "mm": 0.001,
        }.get(spacing.group("unit") or "米", 1.0)
        if numeric_value > 0:
            result["spacing_m"] = round(numeric_value * factor, 4)
    # A parking-space-sized gap is a domain expression, not a missing
    # numeric value. For long-side court layouts the lateral gap uses the
    # standard parking-space width, which is 2.5 m in this app's template.
    if "spacing_m" not in result and re.search(
        r"(?:间距|间隔).{0,12}(?:一个|一块|一格)?(?:标准)?(?:停车位|车位)(?:大小|宽度|尺寸)?",
        normalized,
    ):
        result["spacing_m"] = 2.5
        result["spacing_reference"] = "standard_parking_space_width"
    if any(marker in normalized for marker in (
        "短边相邻", "短边并排", "短边并列", "短边排列", "沿短边排列",
    )):
        result["arrangement"] = "short_side_adjacent"
    elif "长边相邻" in normalized or any(
        marker in normalized
        for marker in (
            "长边并排", "长边并列", "长边排列", "沿长边排列",
            "并排", "相邻", "连续", "相连",
        )
    ):
        result["arrangement"] = "long_side_adjacent"
    horizontal_layout = any(marker in normalized for marker in (
        "左右并排", "左右并列", "左右排列", "横向并排", "横向并列", "横向排列",
    ))
    vertical_layout = any(marker in normalized for marker in (
        "上下并排", "上下并列", "上下排列", "上下排",
        "纵向并排", "纵向并列", "纵向排列", "纵向排",
    ))
    if horizontal_layout and vertical_layout:
        layout_conflicts.append("同一条要求同时包含横向和纵向排列方向")
    if horizontal_layout:
        result["peer_placement"] = "right"
        # For the standard landscape templates, horizontal placement means
        # short-edge adjacency. Store it explicitly so a previous vertical
        # layout cannot leak into the regenerated candidate.
        result.setdefault("arrangement", "short_side_adjacent")
    elif vertical_layout:
        result["peer_placement"] = "above"
        # Standard basketball/badminton templates are wider than tall, so a
        # top/bottom arrangement is their long-side adjacency.
        result.setdefault("arrangement", "long_side_adjacent")
    placement_matches = list(re.finditer(
        r"(?P<label>篮球场|羽毛球场|停车场|停车位|车位|房间|走廊)\s*"
        r"(?:在|位于)\s*(?:另一个|另一侧)?\s*(?P<direction>上方|下方|左侧|右侧)",
        normalized,
    ))
    placement_match = placement_matches[0] if placement_matches else None
    placement_directions = {item.group("direction") for item in placement_matches}
    horizontal_directions = placement_directions & {"左侧", "右侧"}
    vertical_directions = placement_directions & {"上方", "下方"}
    if (len(horizontal_directions) > 1 or len(vertical_directions) > 1
            or (horizontal_directions and vertical_directions)):
        layout_conflicts.append("多个图形的相对位置要求互相冲突")
    placement_key = {
        "篮球场": "basketball",
        "羽毛球场": "badminton",
        "停车场": "parking_lot",
        "停车位": "parking",
        "车位": "parking",
        "房间": "room",
        "走廊": "corridor",
    }
    if placement_match:
        result["placement_template"] = placement_key[placement_match.group("label")]
    if placement_match and placement_match.group("direction") == "上方":
        result["peer_placement"] = "above"
        result.setdefault("arrangement", "long_side_adjacent")
    elif placement_match and placement_match.group("direction") == "下方":
        result["peer_placement"] = "below"
        result.setdefault("arrangement", "long_side_adjacent")
    elif placement_match and placement_match.group("direction") == "左侧":
        result["peer_placement"] = "left"
        result.setdefault("arrangement", "short_side_adjacent")
    elif placement_match and placement_match.group("direction") == "右侧":
        result["peer_placement"] = "right"
        result.setdefault("arrangement", "short_side_adjacent")
    if layout_conflicts:
        result["layout_conflicts"] = list(dict.fromkeys(layout_conflicts))
    return result


def normalize_template_layout_for_matches(
    matches: list[dict[str, Any]] | None,
    layout: dict[str, Any] | None,
) -> dict[str, Any]:
    """Normalize a named placement to the secondary template's direction.

    The renderer places the first template at the origin and translates the
    second one. Therefore "篮球场在上方" means the secondary template must be
    below, while "羽毛球场在上方" means it must be above.
    """
    normalized = dict(layout or {})
    if not isinstance(matches, list) or len(matches) < 2:
        return normalized
    parsed_layout = matches[0]
    if parsed_layout.get("layout_override") is True:
        # The original request is still the authoritative source for an
        # explicit layout. This also repairs projects saved by older versions
        # that persisted spacing but lost arrangement, or retained an inferred
        # horizontal peer placement.
        for key in ("arrangement", "spacing_m", "spacing_reference"):
            if parsed_layout.get(key) is not None:
                normalized[key] = parsed_layout[key]
        if parsed_layout.get("peer_placement") is not None:
            normalized["peer_placement"] = parsed_layout["peer_placement"]
        else:
            normalized.pop("peer_placement", None)
        normalized["layout_override"] = True
    else:
        for key in (
            "arrangement",
            "spacing_m",
            "spacing_reference",
            "peer_placement",
        ):
            if normalized.get(key) is None and parsed_layout.get(key) is not None:
                normalized[key] = parsed_layout[key]
    target = str(normalized.get("placement_template") or "")
    if not target:
        return normalized
    first = str(matches[0].get("template") or "")
    second = str(matches[1].get("template") or "")
    if target == second:
        return normalized
    if target != first:
        return normalized
    opposite = {
        "above": "below", "below": "above",
        "left": "right", "right": "left",
    }
    placement = str(normalized.get("peer_placement") or "")
    if placement in opposite:
        normalized["peer_placement"] = opposite[placement]
    return normalized


def recognize_drawing_template(prompt: str) -> dict[str, Any] | None:
    """Recognize one editor template without spending a model request."""
    normalized = prompt.lower().replace("×", "x")
    # Longer aliases first avoids matching “停车位” inside “停车位阵列”.
    candidates = sorted(
        DRAWING_TEMPLATE_SKILLS.items(),
        key=lambda item: max(map(len, item[1]["aliases"])),
        reverse=True,
    )
    for key, skill in candidates:
        if any(alias.lower() in normalized for alias in skill["aliases"]):
            result = {"template": key, **skill}
            size_match = re.search(
                r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)", normalized
            )
            if size_match and "width_m" in result:
                result["width_m"] = float(size_match.group(1))
                result["height_m"] = float(size_match.group(2))
            radius_match = re.search(r"半径\s*(\d+(?:\.\d+)?)", normalized)
            if radius_match and "radius_m" in result:
                result["radius_m"] = float(radius_match.group(1))
            result["quantity"] = _positive_quantity_before_template(
                normalized, tuple(skill["aliases"])
            )
            if result["quantity"] > 1:
                result.update(_template_layout_requirements(normalized))
            return result
    return None


_PLACEMENT_PATTERNS = (
    ("中间夹着", ("between",)),
    ("中间夹", ("between",)),
    ("夹在中间", ("between",)),
    ("放在中间", ("between",)),
    ("位于中间", ("between",)),
    ("中间放", ("between",)),
    ("上下方", ("above", "below")),
    ("上下", ("above", "below")),
    ("上方", ("above",)),
    ("上边", ("above",)),
    ("上面", ("above",)),
    ("下方", ("below",)),
    ("下边", ("below",)),
    ("下面", ("below",)),
    ("左边", ("left",)),
    ("左侧", ("left",)),
    ("左方", ("left",)),
    ("右边", ("right",)),
    ("右侧", ("right",)),
    ("右方", ("right",)),
)


def _placement_hints(normalized: str, alias_index: int) -> tuple[str, ...]:
    """Return relative placement hints found just before a template alias."""
    window = normalized[max(0, alias_index - 16):alias_index]
    for pattern, result in _PLACEMENT_PATTERNS:
        if pattern in window:
            return result
    return ()


def recognize_drawing_template_set(prompt: str) -> list[dict[str, Any]] | None:
    """Recognize every template mentioned in one prompt, in order of appearance.

    Unlike ``recognize_drawing_template`` this supports composite requests such
    as "在篮球场的上下方各添加一个羽毛球场": the first mentioned template is the
    primary one and every later template carries its relative placement hints.
    """
    normalized = prompt.lower().replace("×", "x")
    entries = [
        (alias.lower(), key)
        for key, skill in DRAWING_TEMPLATE_SKILLS.items()
        for alias in skill["aliases"]
    ]
    entries.sort(key=lambda item: len(item[0]), reverse=True)
    occupied: list[tuple[int, int]] = []
    found: list[dict[str, Any]] = []
    for alias, key in entries:
        start = 0
        while True:
            index = normalized.find(alias, start)
            if index < 0:
                break
            end = index + len(alias)
            if any(s <= index and end <= e for s, e in occupied):
                start = index + 1
                continue
            occupied.append((index, end))
            existing = next(
                (item for item in found if item["template"] == key), None
            )
            if existing is None:
                found.append({"index": index, "end": end, "template": key})
            elif index < existing["index"]:
                # Keep one concrete mention for connector/placement parsing.
                # Extending ``end`` to a later repeated size description (for
                # example "篮球场与羽毛球场……篮球场28m……羽毛球场13.4m")
                # makes the first template overlap the next one and loses the
                # original "与" connector, incorrectly collapsing the request
                # back to a single template.
                existing["index"] = index
                existing["end"] = end
            start = end
    if not found:
        return None
    found.sort(key=lambda item: item["index"])
    results: list[dict[str, Any]] = []
    for position, item in enumerate(found):
        skill = DRAWING_TEMPLATE_SKILLS[item["template"]]
        match: dict[str, Any] = {
            "template": item["template"],
            "quantity": _positive_quantity_before_template(
                normalized, tuple(skill["aliases"])
            ),
        }
        match.update({
            key: float(skill[key])
            for key in ("width_m", "height_m", "radius_m")
            if isinstance(skill.get(key), (int, float))
        })
        if position == 0:
            layout = _template_layout_requirements(normalized)
            for key in (
                "arrangement",
                "spacing_reference",
                "peer_placement",
            ):
                if layout.get(key) is not None:
                    match[key] = layout[key]
            spacing = layout.get("spacing_m")
            if isinstance(spacing, (int, float)):
                match["spacing_m"] = float(spacing)
            # An explicit edge/direction request must override the generic
            # horizontal placement inferred from connectors such as "与".
            if layout.get("arrangement") is not None or layout.get("peer_placement") is not None:
                match["layout_override"] = True
            results.append(match)
            continue
        placements = _placement_hints(normalized, item["index"])
        if not placements:
            previous = found[position - 1]
            connector = normalized[previous["end"]:item["index"]]
            # Two different templates joined as peers are still a composite
            # request even when the user does not spell out left/right.  Use
            # input order for a deterministic horizontal layout.  Repeated
            # aliases of one scene (停车场…8个车位) were merged above and never
            # enter this branch.
            if not any(marker in connector for marker in (
                "与", "和", "及", "以及", "加", "搭配", "组合", "+", "&",
            )):
                continue
            placements = ("right",)
            match["placement_inferred"] = True
        match["placement"] = list(placements)
        if "between" in placements:
            match["sequence_axis"] = (
                "long"
                if any(marker in normalized for marker in (
                    "长边平行", "沿长边方向", "长边方向", "一字排开",
                ))
                else "short"
                if any(marker in normalized for marker in (
                    "短边平行", "沿短边方向", "短边方向",
                ))
                else "long"
            )
        results.append(match)
    if len(results) < 2:
        return None
    return results


def compose_template_geometries(
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    """Build combined geometry: primary template centred, extras placed outside.

    Each extra template is offset against the primary bounds (default flush
    placement, with no additional gap) according to its placement hint. Every generated item keeps a stable
    id and a distinct template_instance so downstream scope checks, logical
    objects and planning stay deterministic.
    """
    if not matches:
        return None

    def template_match(match: dict[str, Any]) -> dict[str, Any]:
        skill = DRAWING_TEMPLATE_SKILLS[match["template"]]
        return {
            **skill,
            **{
                key: match[key]
                for key in (
                    "width_m", "height_m", "radius_m", "spacing_m",
                    "arrangement", "spacing_reference", "peer_placement",
                    "layout_override",
                )
                if match.get(key) is not None
            },
            "template": match["template"],
            "quantity": max(1, min(50, int(match.get("quantity", 1)))),
        }

    def translated_copy(
        source: list[dict[str, Any]],
        *,
        dx: float,
        dy: float,
        instance: int,
        next_identifier: int,
    ) -> tuple[list[dict[str, Any]], int]:
        copied: list[dict[str, Any]] = []
        for geometry in source:
            item = deepcopy(geometry)
            item["id"] = next_identifier
            next_identifier += 1
            item["template_instance"] = instance
            for key in ("start", "end", "center", "position"):
                point = item.get(key)
                if isinstance(point, dict):
                    point["x"] = float(point["x"]) + dx
                    point["y"] = float(point["y"]) + dy
            for key in ("vertices", "control_points"):
                for point in item.get(key) or []:
                    if isinstance(point, dict):
                        point["x"] = float(point["x"]) + dx
                        point["y"] = float(point["y"]) + dy
            copied.append(item)
        return copied, next_identifier

    between = next(
        (
            extra for extra in matches[1:]
            if "between" in (extra.get("placement") or [])
        ),
        None,
    )
    if between is not None and int(matches[0].get("quantity", 1)) == 2:
        primary = drawing_template_geometries({
            **template_match(matches[0]), "quantity": 1,
        })
        middle = drawing_template_geometries({
            **template_match(between), "quantity": 1,
        })
        primary_bounds = _template_bounds(primary)
        middle_bounds = _template_bounds(middle)
        if primary_bounds is None or middle_bounds is None:
            return None
        primary_width = primary_bounds[2] - primary_bounds[0]
        primary_height = primary_bounds[3] - primary_bounds[1]
        middle_width = middle_bounds[2] - middle_bounds[0]
        middle_height = middle_bounds[3] - middle_bounds[1]
        # ``sequence_axis`` describes which edges are parallel, not the axis
        # along which instances are translated.  When the long edges are
        # parallel, the venues are laid out side by side along the short axis.
        # The old inversion placed the middle venue on the long axis and made
        # the rendered candidate disagree with the user's wording.
        long_axis = between.get("sequence_axis") == "short"
        spacing_mm = float(matches[0].get("spacing_m", 0.0)) * 1000.0
        primary_extent = primary_width if long_axis else primary_height
        middle_extent = middle_width if long_axis else middle_height
        center_offset = middle_extent / 2.0 + spacing_mm + primary_extent / 2.0
        result: list[dict[str, Any]] = []
        next_identifier = 1
        for instance, offset, source in (
            (1, -center_offset, primary),
            (2, 0.0, middle),
            (3, center_offset, primary),
        ):
            copied, next_identifier = translated_copy(
                source,
                dx=offset if long_axis else 0.0,
                dy=0.0 if long_axis else offset,
                instance=instance,
                next_identifier=next_identifier,
            )
            result.extend(copied)
        return result

    geometries = drawing_template_geometries(template_match(matches[0]))
    primary_bounds = _template_bounds(geometries)
    if primary_bounds is None or not geometries:
        return None
    next_id = max(int(item.get("id", 0)) for item in geometries) + 1
    next_instance = max(
        int(item.get("template_instance", 0)) for item in geometries
    ) + 1
    # Default flush placement matches the incremental addition path.
    spacing_mm = float(matches[0].get("spacing_m", 0.0)) * 1000.0
    arrangement = str(matches[0].get("arrangement") or "")
    peer_placement = str(matches[0].get("peer_placement") or "")
    layout_override = matches[0].get("layout_override") is True
    primary_width = primary_bounds[2] - primary_bounds[0]
    primary_height = primary_bounds[3] - primary_bounds[1]

    def inferred_peer_placement() -> str:
        """Map an edge-adjacency request to the translation direction.

        A horizontal court has horizontal long edges.  Making those long edges
        adjacent therefore places the next venue above it (translation on Y),
        while short-edge adjacency places it to the right (translation on X).
        """
        long_side_is_horizontal = primary_width >= primary_height
        if arrangement == "long_side_adjacent":
            return "above" if long_side_is_horizontal else "right"
        if arrangement == "short_side_adjacent":
            return "right" if long_side_is_horizontal else "above"
        return "right"

    for extra in matches[1:]:
        placements = list(extra.get("placement") or [])
        if (extra.get("placement_inferred") is True or layout_override) and (
            peer_placement in {"right", "above"}
            or arrangement in {"long_side_adjacent", "short_side_adjacent"}
        ):
            placements = [
                peer_placement
                if peer_placement in {"right", "above"}
                else inferred_peer_placement()
            ]
        if not placements:
            continue
        raw_geometries = drawing_template_geometries(template_match(extra))
        raw_bounds = _template_bounds(raw_geometries)
        if raw_bounds is None or not raw_geometries:
            continue
        for placement in placements:
            if placement == "above":
                dx, dy = 0.0, primary_bounds[3] + spacing_mm - raw_bounds[1]
            elif placement == "below":
                dx, dy = 0.0, primary_bounds[1] - spacing_mm - raw_bounds[3]
            elif placement == "left":
                dx, dy = primary_bounds[0] - spacing_mm - raw_bounds[2], 0.0
            elif placement == "right":
                dx, dy = primary_bounds[2] + spacing_mm - raw_bounds[0], 0.0
            else:
                continue
            instance_map: dict[int, int] = {}
            for geometry in raw_geometries:
                old_instance = int(geometry.get("template_instance", 1))
                if old_instance not in instance_map:
                    instance_map[old_instance] = next_instance
                    next_instance += 1
                copy_geometry = deepcopy(geometry)
                copy_geometry["id"] = next_id
                next_id += 1
                copy_geometry["template_instance"] = instance_map[old_instance]
                for key in ("start", "end", "center", "position"):
                    point = copy_geometry.get(key)
                    if isinstance(point, dict):
                        point["x"] = float(point["x"]) + dx
                        point["y"] = float(point["y"]) + dy
                for key in ("vertices", "control_points"):
                    for point in copy_geometry.get(key) or []:
                        if isinstance(point, dict):
                            point["x"] = float(point["x"]) + dx
                            point["y"] = float(point["y"]) + dy
                geometries.append(copy_geometry)
    return geometries


def compose_template_instance_count(
    matches: list[dict[str, Any]] | None,
) -> int | None:
    """Total template instances of a composite match (primary + extras)."""
    if not isinstance(matches, list) or len(matches) < 2:
        return None
    total = max(1, min(50, int(matches[0].get("quantity", 1))))
    for extra in matches[1:]:
        placements = extra.get("placement") or []
        total += (
            max(1, min(50, int(extra.get("quantity", 1))))
            * max(1, len(placements))
        )
    return total


def _rectangle_points(width: float, height: float) -> list[list[float]]:
    width_mm, height_mm = width * 1000, height * 1000
    return [
        [-width_mm / 2, -height_mm / 2],
        [width_mm / 2, -height_mm / 2],
        [width_mm / 2, height_mm / 2],
        [-width_mm / 2, height_mm / 2],
        [-width_mm / 2, -height_mm / 2],
    ]


def drawing_template_geometries(match: dict[str, Any]) -> list[dict[str, Any]]:
    """Build CAD JSON geometry for an identified template."""
    template = str(match["template"])
    width = float(match.get("width_m", 1.0))
    height = float(match.get("height_m", 1.0))
    if not math.isfinite(width) or not math.isfinite(height) or min(width, height) <= 0:
        raise ValueError("模板宽高必须为有限正数")
    quantity = max(1, min(50, int(match.get("quantity", 1))))
    if quantity > 1 and template != "parking":
        base = drawing_template_geometries({**match, "quantity": 1})
        spacing = max(0.0, min(100.0, float(match.get("spacing_m", 0.0))))
        arrangement = str(match.get("arrangement") or "long_side_adjacent")
        layout_width = (
            float(match.get("radius_m", 1.0)) * 2.0
            if template == "foundation" else width
        )
        layout_height = (
            float(match.get("radius_m", 1.0)) * 2.0
            if template == "foundation" else height
        )
        long_side_is_width = layout_width >= layout_height
        use_x_axis = (
            not long_side_is_width
            if arrangement == "long_side_adjacent"
            else long_side_is_width
        )
        step = (layout_width if use_x_axis else layout_height) + spacing
        geometries: list[dict[str, Any]] = []

        def translate_point(point: dict[str, Any], dx_mm: float, dy_mm: float) -> None:
            point["x"] = float(point.get("x", 0.0)) + dx_mm
            point["y"] = float(point.get("y", 0.0)) + dy_mm

        for instance in range(quantity):
            offset = (instance - (quantity - 1) / 2) * step * 1000.0
            dx_mm, dy_mm = (offset, 0.0) if use_x_axis else (0.0, offset)
            for base_geometry in base:
                geometry = deepcopy(base_geometry)
                geometry["id"] = len(geometries) + 1
                geometry["template_instance"] = instance + 1
                geometry["template_type"] = template
                for key in ("start", "end", "center", "position"):
                    if isinstance(geometry.get(key), dict):
                        translate_point(geometry[key], dx_mm, dy_mm)
                for key in ("vertices", "control_points"):
                    points = geometry.get(key)
                    if isinstance(points, list):
                        for point in points:
                            if isinstance(point, dict):
                                translate_point(point, dx_mm, dy_mm)
                geometries.append(geometry)
        return geometries
    drawing_width = width * quantity if template == "parking" else width
    def line(identifier: int, start: tuple[float, float], end: tuple[float, float]) -> dict[str, Any]:
        return {
            "id": identifier,
            "type": "line",
            "layer_id": 1,
            "start": {"x": start[0] * 1000, "y": start[1] * 1000, "z": 0.0},
            "end": {"x": end[0] * 1000, "y": end[1] * 1000, "z": 0.0},
        }

    if template == "parking" and quantity > 1:
        geometries: list[dict[str, Any]] = []
        left = -drawing_width / 2
        identifier = 1
        for boundary in range(quantity + 1):
            x = left + width * boundary
            geometry = line(identifier, (x, -height / 2), (x, height / 2))
            geometry["template_instance"] = min(quantity, max(1, boundary or 1))
            geometries.append(geometry)
            identifier += 1
        for instance in range(quantity):
            min_x = left + width * instance
            max_x = min_x + width
            for y in (-height / 2, height / 2):
                geometry = line(identifier, (min_x, y), (max_x, y))
                geometry["template_instance"] = instance + 1
                geometries.append(geometry)
                identifier += 1
        for geometry in geometries:
            geometry["template_type"] = template
        return geometries

    geometries = [
        {
            "id": 1,
            "type": "polyline",
            "layer_id": 1,
            "vertices": [
                {"x": point[0], "y": point[1], "z": 0.0}
                for point in _rectangle_points(drawing_width, height)
            ],
            "closed": True,
        }
    ]
    if template == "two_rooms":
        geometries.append(line(2, (0, -height / 2), (0, height / 2)))
    elif template == "basketball":
        from .cad_standard_templates import court_geometries
        geometries = court_geometries(template, width, height)
    elif template == "badminton":
        from .cad_standard_templates import court_geometries
        geometries = court_geometries(template, width, height)
    elif template == "parking_lot":
        for identifier, x in enumerate(range(-5, 6, 2), start=2):
            geometries.append(line(identifier, (float(x), -height / 2), (float(x), height / 2)))
    elif template == "warehouse":
        for identifier, x in enumerate(range(-8, 9, 4), start=2):
            geometries.append(line(identifier, (float(x), -height / 2), (float(x), height / 2)))
    elif template == "grid":
        # Cells determine axes (N cells need N+1 axes); no perimeter overlay.
        geometries = []
        columns = int(match.get('grid_columns',4))
        rows = int(match.get('grid_rows',4))
        if not 1 <= min(columns,rows) <= max(columns,rows) <= 50:
            raise ValueError('轴网行列分格数必须在1至50之间')
        for index in range(columns+1):
            x = -width/2 + index*width/columns
            geometries.append(line(len(geometries)+1,(x,-height/2),(x,height/2)))
        for index in range(rows+1):
            y = -height/2 + index*height/rows
            geometries.append(line(len(geometries)+1,(-width/2,y),(width/2,y)))
    elif template == "foundation":
        geometries = [{
            "id": 1,
            "type": "circle",
            "layer_id": 1,
            "center": {"x": 0.0, "y": 0.0, "z": 0.0},
            "radius": float(match.get("radius_m", 3.0)) * 1000,
        }]
    for geometry in geometries:
        geometry.setdefault("template_instance", 1)
        geometry.setdefault("template_type", template)
    return geometries


def _template_bounds(geometries: list[dict[str, Any]]) -> tuple[float, float, float, float] | None:
    points: list[tuple[float, float]] = []
    for geometry in geometries:
        for key in ("start", "end", "center", "position"):
            point = geometry.get(key)
            if isinstance(point, dict):
                try:
                    points.append((float(point["x"]), float(point["y"])))
                except (KeyError, TypeError, ValueError):
                    pass
        for point in geometry.get("vertices", []):
            if isinstance(point, dict):
                try:
                    points.append((float(point["x"]), float(point["y"])))
                except (KeyError, TypeError, ValueError):
                    pass
    if not points:
        return None
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def build_template_logical_object_graph(
    match: dict[str, Any], geometries: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build stable logical objects without changing physical print geometry."""
    template = str(match.get("template") or "").lower()
    quantity = max(1, min(50, int(match.get("quantity", 1))))

    def add_spatial_identity(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Attach stable spatial metadata once, alongside the logical ID.

        The resolver must not infer an object's identity from the current
        geometry order after a move.  These fields are persisted with the
        logical object and are refreshed only when a new logical graph is
        created.
        """
        valid = [item for item in objects if isinstance(item.get("bounds"), dict)]
        for item in objects:
            object_id = str(item.get("object_id") or "").strip()
            if object_id:
                item.setdefault("identity_key", object_id)
        if len(valid) <= 1:
            for item in valid:
                item["spatial_anchor"] = {
                    "axis": None, "rank": 1, "count": 1, "position": "only"
                }
            return objects
        centers = {
            str(item["object_id"]): (
                (float(item["bounds"]["min_x"]) + float(item["bounds"]["max_x"])) / 2,
                (float(item["bounds"]["min_y"]) + float(item["bounds"]["max_y"])) / 2,
            )
            for item in valid
        }
        use_y = (
            max(value[1] for value in centers.values())
            - min(value[1] for value in centers.values())
            >= max(value[0] for value in centers.values())
            - min(value[0] for value in centers.values())
        )
        axis = "y" if use_y else "x"
        ordered = sorted(
            valid,
            key=lambda item: (centers[str(item["object_id"])][1 if use_y else 0], str(item["object_id"])),
        )
        total = len(ordered)
        for rank, item in enumerate(ordered, 1):
            if total == 2:
                position = "bottom" if use_y and rank == 1 else "top" if use_y else "left" if rank == 1 else "right"
            elif rank == 1:
                position = "bottom" if use_y else "left"
            elif rank == total:
                position = "top" if use_y else "right"
            else:
                position = "middle"
            item["spatial_anchor"] = {
                "axis": axis, "rank": rank, "count": total, "position": position,
            }
        return objects
    if template == "parking" and quantity > 1:
        bounds = _template_bounds(geometries)
        vertical = sorted(
            (
                item for item in geometries
                if item.get("type") == "line"
                and abs(float(item.get("start", {}).get("x", 0.0))
                        - float(item.get("end", {}).get("x", 0.0))) < 1e-6
            ),
            key=lambda item: float(item.get("start", {}).get("x", 0.0)),
        )
        horizontal = sorted(
            (
                item for item in geometries
                if item.get("type") == "line"
                and abs(float(item.get("start", {}).get("y", 0.0))
                        - float(item.get("end", {}).get("y", 0.0))) < 1e-6
            ),
            key=lambda item: (
                float(item.get("start", {}).get("x", 0.0)),
                float(item.get("start", {}).get("y", 0.0)),
            ),
        )
        if bounds and len(vertical) == quantity + 1 and len(horizontal) == quantity * 2:
            min_x, min_y, max_x, max_y = bounds
            width = (max_x - min_x) / quantity
            objects: list[dict[str, Any]] = []
            shared: list[dict[str, Any]] = []
            for index in range(quantity):
                object_id = f"parking-space-{index + 1}"
                min_object_x = min_x + index * width
                max_object_x = min_object_x + width
                horizontal_refs = [
                    int(item["id"]) for item in horizontal
                    if abs(min(
                        float(item["start"]["x"]), float(item["end"]["x"])
                    ) - min_object_x) < 1e-6
                    and abs(max(
                        float(item["start"]["x"]), float(item["end"]["x"])
                    ) - max_object_x) < 1e-6
                ]
                refs = [
                    int(vertical[index]["id"]), int(vertical[index + 1]["id"]),
                    *horizontal_refs,
                ]
                objects.append({
                    "object_id": object_id,
                    "object_type": "parking_space",
                    "label": f"{'从左到右' if quantity > 2 else '左侧' if index == 0 else '右侧'}车位"
                    if quantity <= 2 else f"从左到右第{index + 1}个车位",
                    "geometry_refs": refs,
                    "bounds": {
                        "min_x": min_x + index * width,
                        "min_y": min_y,
                        "max_x": min_x + (index + 1) * width,
                        "max_y": max_y,
                    },
                    "confirmed": True,
                    "confidence": 1.0,
                })
            for index, divider in enumerate(vertical[1:-1]):
                shared.append({
                    "geometry_id": int(divider["id"]),
                    "object_ids": [
                        f"parking-space-{index + 1}",
                        f"parking-space-{index + 2}",
                    ],
                    "relation": "shared_boundary",
                })
            relations = [
                {
                    "source_object_id": f"parking-space-{index}",
                    "target_object_id": f"parking-space-{index + 1}",
                    "relation": relation,
                }
                for index in range(1, quantity)
                for relation in ("left_of", "adjacent")
            ]
            return {
                "logical_objects": add_spatial_identity(objects),
                "topology": {
                    "schema_version": "cad.topology.v1",
                    "shared_geometries": shared,
                    "relations": relations,
                },
            }

    if template == "two_rooms" and quantity == 1:
        outer = next(
            (item for item in geometries
             if item.get("type") == "polyline" and item.get("closed") is True),
            None,
        )
        divider = next(
            (item for item in geometries if item.get("type") == "line"), None
        )
        bounds = _template_bounds([outer] if outer else geometries)
        if bounds and divider is not None:
            min_x, min_y, max_x, max_y = bounds
            center_x = (min_x + max_x) / 2
            objects = [
                {
                    "object_id": "room-1", "object_type": "room",
                    "label": "左侧房间", "geometry_refs": [int(divider["id"])],
                    "bounds": {"min_x": min_x, "min_y": min_y,
                               "max_x": center_x, "max_y": max_y},
                    "confirmed": True, "confidence": 1.0,
                },
                {
                    "object_id": "room-2", "object_type": "room",
                    "label": "右侧房间", "geometry_refs": [int(divider["id"])],
                    "bounds": {"min_x": center_x, "min_y": min_y,
                               "max_x": max_x, "max_y": max_y},
                    "confirmed": True, "confidence": 1.0,
                },
            ]
            return {
                "logical_objects": add_spatial_identity(objects),
                "topology": {
                    "schema_version": "cad.topology.v1",
                    "shared_geometries": [{
                        "geometry_id": int(divider["id"]),
                        "object_ids": ["room-1", "room-2"],
                        "relation": "shared_boundary",
                    }],
                    "relations": [
                        {"source_object_id": "room-1", "target_object_id": "room-2",
                         "relation": "left_of"},
                        {"source_object_id": "room-1", "target_object_id": "room-2",
                         "relation": "adjacent"},
                    ],
                },
            }

    # Generic template instances remain addressable even when no special
    # shared-boundary decomposition is available yet.
    groups: dict[int, list[dict[str, Any]]] = {}
    for geometry in geometries:
        instance = geometry.get("template_instance")
        if isinstance(instance, (int, float)) and int(instance) > 0:
            groups.setdefault(int(instance), []).append(geometry)
    # Imported CAD commonly has stable geometry IDs but no template instance
    # metadata. It is still one selectable drawing, so provide a durable root
    # object instead of forcing complete-shape selection to fall back to the
    # single segment under the pointer.
    if not groups and geometries:
        groups[1] = geometries
    objects = []
    for instance, items in sorted(groups.items()):
        bounds = _template_bounds(items)
        instance_template = str(
            next(
                (
                    item.get("template_type") for item in items
                    if str(item.get("template_type") or "").strip()
                ),
                template or "drawing",
            )
        )
        label = str(
            DRAWING_TEMPLATE_SKILLS.get(instance_template, {}).get("label")
            or ({"imported_cad": "导入 CAD 图纸", "drawing": "完整图形"}.get(instance_template))
            or instance_template
            or "图形"
        )
        objects.append({
            "object_id": f"{instance_template}-{instance}",
            "object_type": instance_template,
            "label": f"{label} {instance}",
            "geometry_refs": [int(item["id"]) for item in items if str(item.get("id", "")).isdigit()],
            **({"bounds": {
                "min_x": bounds[0], "min_y": bounds[1],
                "max_x": bounds[2], "max_y": bounds[3],
            }} if bounds else {}),
            "confirmed": True,
            "confidence": 1.0,
        })
    return {
        "logical_objects": add_spatial_identity(objects),
        "topology": {
            "schema_version": "cad.topology.v1",
            "shared_geometries": [],
            "relations": [],
        },
    }


def drawing_template_motion_steps(match: dict[str, Any]) -> list[dict[str, float]]:
    """Create an open-loop base-mode preview from a template perimeter."""
    geometries = drawing_template_geometries(match)
    points: list[tuple[float, float]] = []
    for geometry in geometries:
        if geometry["type"] == "polyline":
            points.extend(
                (float(point["x"]) / 1000, float(point["y"]) / 1000)
                for point in geometry["vertices"]
            )
        elif geometry["type"] == "line":
            points.extend(
                (
                    (float(geometry["start"]["x"]) / 1000, float(geometry["start"]["y"]) / 1000),
                    (float(geometry["end"]["x"]) / 1000, float(geometry["end"]["y"]) / 1000),
                )
            )
        elif geometry["type"] == "circle":
            radius = float(geometry["radius"]) / 1000
            points.extend(
                (
                    radius * math.cos(2 * math.pi * index / 24),
                    radius * math.sin(2 * math.pi * index / 24),
                )
                for index in range(25)
            )
    if len(points) < 2:
        return []
    origin_x, origin_y = points[0]
    translated = [(x - origin_x, y - origin_y) for x, y in points]
    steps: list[dict[str, float]] = []
    heading = 0.0
    for start, end in zip(translated, translated[1:]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        distance = math.hypot(dx, dy)
        if distance < 0.01:
            continue
        target = math.atan2(dy, dx)
        turn = (target - heading + math.pi) % (2 * math.pi) - math.pi
        if abs(turn) > 0.03:
            turn_duration = abs(turn) / 0.4
            steps.append({
                "linear": 0.0,
                "angular": 0.4 if turn > 0 else -0.4,
                "duration_seconds": round(turn_duration, 3),
            })
        drive_duration = distance / 0.1
        remaining = drive_duration
        while remaining > 0:
            duration = min(30.0, remaining)
            steps.append({"linear": 0.1, "angular": 0.0, "duration_seconds": round(duration, 3)})
            remaining -= duration
        heading = target
    return steps


def _default_printer() -> str | None:
    """Return the only printer supported by the current vehicle design.

    Connectivity is an execution preflight concern. Requiring live printer
    telemetry while creating an offline design leaves otherwise complete CAD
    projects stuck in clarification when the vehicle is disconnected.
    """
    return "center"


def heart_outline_geometry(
    width_m: float,
    height_m: float,
    *,
    samples: int = 128,
) -> dict[str, Any]:
    """Build a deterministic, centered, closed heart outline in millimetres.

    The parametric curve is sampled as a polyline so the existing preview,
    path planner, and geometry validators can consume it without a special
    renderer.  Normalising the raw curve by its own bounds makes the requested
    width and height exact and keeps the logical object centred at (0, 0).
    """
    width_mm = float(width_m) * 1000.0
    height_mm = float(height_m) * 1000.0
    if width_mm <= 0 or height_mm <= 0:
        raise ValueError("爱心轮廓宽度和高度必须大于零")
    sample_count = max(32, min(512, int(samples)))
    raw_points = [
        (
            16.0 * math.sin(t) ** 3,
            13.0 * math.cos(t)
            - 5.0 * math.cos(2.0 * t)
            - 2.0 * math.cos(3.0 * t)
            - math.cos(4.0 * t),
        )
        for t in (2.0 * math.pi * index / sample_count for index in range(sample_count))
    ]
    min_x = min(point[0] for point in raw_points)
    max_x = max(point[0] for point in raw_points)
    min_y = min(point[1] for point in raw_points)
    max_y = max(point[1] for point in raw_points)
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0
    scale_x = width_mm / (max_x - min_x)
    scale_y = height_mm / (max_y - min_y)
    vertices = [
        {
            "x": round((x - center_x) * scale_x, 6),
            "y": round((y - center_y) * scale_y, 6),
            "z": 0.0,
        }
        for x, y in raw_points
    ]
    return {
        "id": 1,
        "type": "polyline",
        "layer_id": 1,
        "vertices": vertices,
        "closed": True,
        "label": "对称闭合爱心轮廓",
        "role": "printing",
        "path_semantic": "printing",
        "semantic": "heart_outline",
    }


def parameterize_design(prompt: str) -> dict[str, Any]:
    normalized = prompt.lower().replace("×", "x").replace("*", "x")
    # Editor templates are complete design intents even when the prompt does
    # not contain a generic word such as "rectangle" or an explicit size.
    # Keep this in the same parameter contract used by creative projects so a
    # saved template cannot appear as a finished operation with missing shape
    # and dimensions.
    template_set = recognize_drawing_template_set(normalized)
    template = recognize_drawing_template(normalized)
    if template is not None:
        dimensions = {
            key: float(template[key])
            for key in ("width_m", "height_m", "radius_m")
            if key in template
        }
        printer = _default_printer()
        missing = ["printer"] if printer is None else []
        assumptions = [
            "模板尺寸按标准尺寸解释",
            "未指定起点时按小车当前位姿作为图纸原点",
            "未指定执行方式时只生成设计和规划预览，不启动小车",
        ]
        if printer == "center":
            assumptions.append("未指定喷头时使用当前唯一可用的中心喷码机")
        result = {
            "ok": not missing,
            "shape": template["template"],
            "dimensions": dimensions,
            "quantity": int(template.get("quantity", 1)),
            "arrangement": template.get("arrangement"),
            "spacing_m": float(template.get("spacing_m", 0.0)),
            "printer": printer,
            "origin": "current_robot_pose",
            "units": "m",
            "missing": missing,
            "assumptions": assumptions,
        }
        if isinstance(template_set, list) and len(template_set) > 1:
            composite_layout = template_set[0]
            for key in (
                "arrangement",
                "spacing_reference",
                "peer_placement",
                "layout_override",
            ):
                if composite_layout.get(key) is not None:
                    result[key] = composite_layout[key]
            if isinstance(composite_layout.get("spacing_m"), (int, float)):
                result["spacing_m"] = float(composite_layout["spacing_m"])
            result["template_components"] = [
                {
                    "template": str(item["template"]),
                    "label": str(
                        DRAWING_TEMPLATE_SKILLS.get(
                            str(item["template"]), {}
                        ).get("label") or item["template"]
                    ),
                    "quantity": max(1, min(50, int(item.get("quantity", 1)))),
                    "dimensions": {
                        key: float(item[key])
                        for key in ("width_m", "height_m", "radius_m")
                        if isinstance(item.get(key), (int, float))
                    },
                    "placement": list(item.get("placement") or []),
                    "placement_inferred": item.get("placement_inferred") is True,
                }
                for item in template_set
            ]
            result["quantity"] = int(compose_template_instance_count(template_set) or 1)
            if (
                result.get("arrangement") is None
                and result.get("peer_placement") is None
                and any(item.get("placement_inferred") is True for item in template_set)
            ):
                assumptions.append("未指定组合位置时按提及顺序水平并排")
        return result
    heart_shape = any(keyword in normalized for keyword in ("爱心", "心形", "心型", "heart"))
    # 复合结构优先：半圆拱门/拱门 = 半圆弧 + 两侧直立边（+ 可选底边）。
    # 必须排在"圆/circle"之前——"半圆拱门"里含"圆"字，否则会被误判成整圆
    # （整圆生成器会直接画一个圆，用户要的拱门结构完全丢失，链路3 也无从执行）。
    arch_shape = any(
        keyword in normalized
        for keyword in ("半圆拱门", "拱门", "semicircular arch", "semicircular_arch", "arch")
    )
    shape = (
        "closed_semicircular_arch"
        if arch_shape
        else "heart_outline"
        if heart_shape
        else next(
            (
                value
                for keywords, value in (
                    (("矩形", "长方形", "rectangle"), "rectangle"),
                    (("圆弧", "arc"), "arc"),
                    (("圆形", "圆", "circle"), "circle"),
                    (("折线", "polyline"), "polyline"),
                    (("椭圆", "ellipse"), "ellipse"),
                )
                if any(keyword in normalized for keyword in keywords)
            ),
            None,
        )
    )
    numbers = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", normalized)]
    size_match = re.search(r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)", normalized)
    named_size_match = re.search(
        r"(?:总\s*)?(?:宽度?|width)\s*(\d+(?:\.\d+)?)\s*"
        r"(?:米|m|厘米|cm|毫米|mm)?\s*[，,、;；\s]*"
        r"(?:总\s*)?(?:高度?|height)\s*(\d+(?:\.\d+)?)\s*"
        r"(?:米|m|厘米|cm|毫米|mm)?",
        normalized,
    )
    diameter_match = re.search(r"直径\s*(\d+(?:\.\d+)?)", normalized)
    radius_match = re.search(r"半径\s*(\d+(?:\.\d+)?)", normalized)
    unsupported_printer = any(
        marker in normalized for marker in ("左喷", "右喷", "left printer", "right printer")
    )
    requested_printer = "center" if any(
        marker in normalized for marker in ("中喷", "中心喷", "center printer")
    ) else None
    printer = requested_printer or _default_printer()
    dimensions: dict[str, float] = {}
    dimension_bounds: dict[str, float] = {}
    if named_size_match:
        dimensions = {
            "width_m": float(named_size_match.group(1)),
            "height_m": float(named_size_match.group(2)),
        }
    elif size_match:
        dimensions = {"width_m": float(size_match.group(1)), "height_m": float(size_match.group(2))}
    elif diameter_match:
        dimensions = {"diameter_m": float(diameter_match.group(1))}
    elif radius_match:
        dimensions = {"radius_m": float(radius_match.group(1))}
    elif shape == "circle" and numbers:
        dimensions = {"radius_m": numbers[0]}

    same_size_match = re.search(
        r"(?:宽高|宽度和高度|宽度高度)\s*(?:均|都)?\s*"
        r"(?:为|是|改为|改成|调整为|调整成|[:：])?\s*"
        r"(\d+(?:\.\d+)?)\s*(米|m|厘米|cm|毫米|mm)",
        normalized,
    )
    if same_size_match:
        factor = {"厘米": 0.01, "cm": 0.01, "毫米": 0.001, "mm": 0.001}.get(
            same_size_match.group(2), 1.0
        )
        value = float(same_size_match.group(1)) * factor
        dimensions = {"width_m": value, "height_m": value}
    for key, label in (("width_m", "宽度"), ("height_m", "高度")):
        single_size_match = re.search(
            rf"(?:总\s*)?{label}\s*(?:为|是|改为|改成|调整为|调整成|[:：])?\s*"
            r"(\d+(?:\.\d+)?)\s*(米|m|厘米|cm|毫米|mm)",
            normalized,
        )
        if single_size_match:
            factor = {"厘米": 0.01, "cm": 0.01, "毫米": 0.001, "mm": 0.001}.get(
                single_size_match.group(2), 1.0
            )
            dimensions[key] = float(single_size_match.group(1)) * factor

    # 拱门是复合结构（半圆弧 + 两侧直立边）：除总宽/总高外，补提
    # 弧半径与直腿高，供 normalize 单位判定与后续直投几何做完整参照；
    # 避免只抓"半径1米"导致尺寸量级参照只剩半径。
    if arch_shape:
        if radius_match and "radius_m" not in dimensions:
            dimensions["radius_m"] = float(radius_match.group(1))
        leg_match = re.search(
            r"(?:直腿|腿)\s*(?:高|height)\s*(\d+(?:\.\d+)?)",
            normalized,
        )
        if leg_match:
            dimensions["leg_height_m"] = float(leg_match.group(1))

    # "宽高不超过 5 米" is a complete bounded design request, not a
    # missing-dimensions request.  Use the stated bound as the deterministic
    # maximum size and retain the bound for the UI/explanation layer.
    bound_match = re.search(
        r"(?:整体)?(?:宽度和高度|宽高|宽度高度)\s*"
        r"(?:均|都)?\s*(?:不超过|不得超过|小于等于|不大于|<=|≤)\s*"
        r"(\d+(?:\.\d+)?)\s*(米|m|厘米|cm|毫米|mm)?",
        normalized,
    )
    if bound_match and shape == "heart_outline":
        unit_factor = {
            "厘米": 0.01,
            "cm": 0.01,
            "毫米": 0.001,
            "mm": 0.001,
        }.get(bound_match.group(2) or "米", 1.0)
        limit_m = float(bound_match.group(1)) * unit_factor
        if limit_m > 0:
            dimensions = {"width_m": limit_m, "height_m": limit_m}
            dimension_bounds = {
                "max_width_m": limit_m,
                "max_height_m": limit_m,
            }

    # A named free-form outline is a valid CAD shape even when it has no
    # standard-template enum. Keep its description for structured construction.
    if shape is None and re.search(r"轮廓|闭合曲线|自由曲线|自由形状", normalized):
        shape = "generic_2d_cad"

    missing = []
    if shape is None:
        missing.append("shape")
    if not dimensions:
        missing.append("dimensions")
    if printer is None:
        missing.append("printer")
    if unsupported_printer:
        missing.append("unsupported_printer:xline_ws3_only_has_center")
    assumptions = [
        "未指定单位时按米解释设计尺寸",
        "未指定起点时按小车当前位姿作为图纸原点",
        "未指定执行方式时只生成设计和规划预览，不启动小车",
    ]
    if printer == "center" and requested_printer is None:
        assumptions.append("未指定喷头时使用当前唯一可用的中心喷码机")
    origin = "current_robot_pose"
    if any(marker in normalized for marker in ("坐标原点", "原点", "中心位于原点")):
        origin = "drawing_origin"
        assumptions.append("图形中心固定在图纸坐标原点 (0, 0)")
    if dimension_bounds:
        assumptions.append("用户只给出尺寸上限，按上限生成可编辑方案")
    result = {
        "ok": not missing,
        "shape": shape,
        "dimensions": dimensions,
        "printer": printer,
        "origin": origin,
        "units": "m",
        "missing": missing,
        "assumptions": assumptions,
    }
    if dimension_bounds:
        result["dimension_bounds"] = dimension_bounds
    if shape == "heart_outline":
        result["closed"] = True
        result["smooth"] = True
        result["symmetric"] = True
        result["self_intersection"] = False
    return result


def clarify_requirements(prompt: str) -> dict[str, Any]:
    requirements = parameterize_design(prompt)
    question_specs = {
        "shape": "需要绘制什么图形或图案？",
        "dimensions": "请提供关键尺寸和单位。",
        "printer": "当前没有唯一可用喷码机，请选择左、中或右喷码机。",
    }
    priority = {
        "shape": 1,
        "dimensions": 2,
        "printer": 3,
        "unsupported_printer:xline_ws3_only_has_center": 1,
    }
    missing = list(requirements["missing"])
    missing.sort(key=lambda item: priority.get(item, 99))
    next_key = missing[0] if missing else None
    next_question = question_specs.get(next_key) if next_key else None
    if next_key == "unsupported_printer:xline_ws3_only_has_center":
        next_question = "当前版本只有中心喷码机可用，是否改用中心喷码机？"
    return {
        **requirements,
        "missing": missing,
        "questions": [next_question] if next_question else [],
        "next_question": next_question,
        "next_question_key": next_key,
        "question_reason": (
            "这是生成候选方案前最关键的缺失参数。"
            if next_question else "设计参数已齐全，可以进入候选方案阶段。"
        ),
        "ready_for_design": not missing,
    }


def calculate_geometry_bounds(geometries: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate executable drawing bounds in millimetres.

    Work-area limits are optional deployment configuration.  When absent we
    report the bounds without inventing a machine limit.
    """
    paths = preview_paths({"lines": geometries})
    points = [point for path in paths for point in path if len(point) >= 2]
    if not points:
        return {"ok": False, "bounds": None, "errors": ["没有可计算边界的有效几何"]}
    min_x = min(float(point[0]) * 1000 for point in points)
    max_x = max(float(point[0]) * 1000 for point in points)
    min_y = min(float(point[1]) * 1000 for point in points)
    max_y = max(float(point[1]) * 1000 for point in points)
    bounds = {
        "min_x_mm": round(min_x, 3),
        "max_x_mm": round(max_x, 3),
        "min_y_mm": round(min_y, 3),
        "max_y_mm": round(max_y, 3),
        "width_mm": round(max_x - min_x, 3),
        "height_mm": round(max_y - min_y, 3),
    }
    errors: list[str] = []
    warnings: list[str] = []
    configured = [os.getenv(name) for name in (
        "XLINE_WORKSPACE_MAX_X_MM", "XLINE_WORKSPACE_MIN_X_MM",
        "XLINE_WORKSPACE_MAX_Y_MM", "XLINE_WORKSPACE_MIN_Y_MM",
    )]
    if any(value is not None for value in configured):
        try:
            max_x_mm = float(os.getenv("XLINE_WORKSPACE_MAX_X_MM", ""))
            min_x_mm = float(os.getenv("XLINE_WORKSPACE_MIN_X_MM", ""))
            max_y_mm = float(os.getenv("XLINE_WORKSPACE_MAX_Y_MM", ""))
            min_y_mm = float(os.getenv("XLINE_WORKSPACE_MIN_Y_MM", ""))
        except ValueError:
            warnings.append("工作范围配置无效，已跳过边界限制比较")
        else:
            if min_x_mm >= max_x_mm or min_y_mm >= max_y_mm:
                warnings.append("工作范围配置无效，已跳过边界限制比较")
            else:
                if bounds["min_x_mm"] < min_x_mm or bounds["max_x_mm"] > max_x_mm:
                    errors.append(f"图纸 X 范围超出工作范围 [{min_x_mm:g}, {max_x_mm:g}] mm")
                if bounds["min_y_mm"] < min_y_mm or bounds["max_y_mm"] > max_y_mm:
                    errors.append(f"图纸 Y 范围超出工作范围 [{min_y_mm:g}, {max_y_mm:g}] mm")
    return {"ok": not errors, "bounds": bounds, "errors": errors, "warnings": warnings}


def validate_template_layout(
    geometries: list[dict[str, Any]],
    *,
    arrangement: str | None = None,
    spacing_m: float | None = None,
    peer_placement: str | None = None,
    tolerance_mm: float = 5.0,
) -> dict[str, Any]:
    """Verify the spatial contract of the first two generated instances.

    Layout text is not evidence that the generated geometry followed it. This
    validator compares stable template-instance bounds after generation and is
    intentionally conservative: an unsupported or incomplete instance graph
    is reported as a failed contract instead of being treated as successful.
    """
    groups: dict[int, list[dict[str, Any]]] = {}
    for item in geometries:
        if not isinstance(item, dict):
            continue
        instance = item.get("template_instance")
        if isinstance(instance, int) and instance > 0:
            groups.setdefault(instance, []).append(item)
    if len(groups) < 2:
        return {
            "schema": "cad.layout-validation.v1",
            "ok": False,
            "status": "insufficient_instances",
            "errors": ["布局校验至少需要两个带稳定实例编号的图形"],
        }

    first_id, second_id = sorted(groups)[:2]
    first_report = calculate_geometry_bounds(groups[first_id])
    second_report = calculate_geometry_bounds(groups[second_id])
    first = first_report.get("bounds")
    second = second_report.get("bounds")
    if not isinstance(first, dict) or not isinstance(second, dict):
        return {
            "schema": "cad.layout-validation.v1",
            "ok": False,
            "status": "invalid_bounds",
            "errors": ["布局校验无法计算两个实例的有效边界"],
        }

    first_width = float(first["width_mm"])
    first_height = float(first["height_mm"])
    effective_arrangement = str(arrangement or "")
    placement = str(peer_placement or "")
    if placement not in {"above", "below", "left", "right"}:
        if effective_arrangement == "long_side_adjacent":
            placement = "above" if first_width >= first_height else "right"
        elif effective_arrangement == "short_side_adjacent":
            placement = "right" if first_width >= first_height else "above"
        else:
            placement = "right" if first_width >= first_height else "above"

    first_center_x = (float(first["min_x_mm"]) + float(first["max_x_mm"])) / 2
    first_center_y = (float(first["min_y_mm"]) + float(first["max_y_mm"])) / 2
    second_center_x = (float(second["min_x_mm"]) + float(second["max_x_mm"])) / 2
    second_center_y = (float(second["min_y_mm"]) + float(second["max_y_mm"])) / 2
    if placement == "above":
        actual_gap_mm = float(second["min_y_mm"]) - float(first["max_y_mm"])
        center_offset_mm = abs(second_center_x - first_center_x)
    elif placement == "below":
        actual_gap_mm = float(first["min_y_mm"]) - float(second["max_y_mm"])
        center_offset_mm = abs(second_center_x - first_center_x)
    elif placement == "left":
        actual_gap_mm = float(first["min_x_mm"]) - float(second["max_x_mm"])
        center_offset_mm = abs(second_center_y - first_center_y)
    else:
        actual_gap_mm = float(second["min_x_mm"]) - float(first["max_x_mm"])
        center_offset_mm = abs(second_center_y - first_center_y)

    expected_gap_mm = None if spacing_m is None else max(0.0, float(spacing_m) * 1000.0)
    errors: list[str] = []
    if center_offset_mm > tolerance_mm:
        errors.append(
            f"两个实例中心线偏移 {center_offset_mm / 1000:g} 米，超过 {tolerance_mm / 1000:g} 米容差"
        )
    if actual_gap_mm < -tolerance_mm:
        errors.append("两个实例发生重叠")
    if expected_gap_mm is not None and abs(actual_gap_mm - expected_gap_mm) > tolerance_mm:
        errors.append(
            f"实际净距 {actual_gap_mm / 1000:g} 米，不等于要求的 {expected_gap_mm / 1000:g} 米"
        )
    return {
        "schema": "cad.layout-validation.v1",
        "ok": not errors,
        "status": "verified" if not errors else "failed",
        "instances": [first_id, second_id],
        "placement": placement,
        "arrangement": effective_arrangement or None,
        "expected_spacing_m": None if expected_gap_mm is None else round(expected_gap_mm / 1000.0, 4),
        "actual_spacing_m": round(actual_gap_mm / 1000.0, 4),
        "center_offset_m": round(center_offset_mm / 1000.0, 4),
        "tolerance_mm": tolerance_mm,
        "errors": errors,
    }


def _orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a: tuple[float, float], b: tuple[float, float], p: tuple[float, float], tolerance: float = 1e-6) -> bool:
    return (
        min(a[0], b[0]) - tolerance <= p[0] <= max(a[0], b[0]) + tolerance
        and min(a[1], b[1]) - tolerance <= p[1] <= max(a[1], b[1]) + tolerance
    )


def _segments_intersect(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float]) -> bool:
    values = (_orientation(a, b, c), _orientation(a, b, d), _orientation(c, d, a), _orientation(c, d, b))
    if values[0] == values[1] == values[2] == values[3] == 0:
        return any(_on_segment(left, right, point) for left, right, point in ((a, b, c), (a, b, d), (c, d, a), (c, d, b)))
    return ((values[0] > 0) != (values[1] > 0)) and ((values[2] > 0) != (values[3] > 0))


def _intersection_key(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float]) -> tuple[float, float]:
    denominator = (a[0] - b[0]) * (c[1] - d[1]) - (a[1] - b[1]) * (c[0] - d[0])
    if abs(denominator) < 1e-9:
        return (round((max(min(a[0], b[0]), min(c[0], d[0]))), 3), round((max(min(a[1], b[1]), min(c[1], d[1]))), 3))
    numerator_x = (a[0] * b[1] - a[1] * b[0]) * (c[0] - d[0]) - (a[0] - b[0]) * (c[0] * d[1] - c[1] * d[0])
    numerator_y = (a[0] * b[1] - a[1] * b[0]) * (c[1] - d[1]) - (a[1] - b[1]) * (c[0] * d[1] - c[1] * d[0])
    return (round(numerator_x / denominator, 3), round(numerator_y / denominator, 3))


def analyze_geometry_topology(geometries: list[dict[str, Any]], tolerance_mm: float = 1.0) -> dict[str, Any]:
    """Analyze endpoint connectivity and sampled-curve intersections."""
    paths = preview_paths({"lines": geometries})
    segments: list[tuple[tuple[float, float], tuple[float, float], int, int]] = []
    endpoints: list[tuple[float, float]] = []
    closed_loop_count = 0
    for path_index, path in enumerate(paths):
        points = [(float(point[0]) * 1000, float(point[1]) * 1000) for point in path]
        if len(points) < 2:
            continue
        is_closed = math.dist(points[0], points[-1]) <= tolerance_mm
        if is_closed:
            closed_loop_count += 1
        else:
            endpoints.extend((points[0], points[-1]))
        for segment_index, (start, end) in enumerate(zip(points, points[1:])):
            segments.append((start, end, path_index, segment_index))

    def node(point: tuple[float, float]) -> tuple[int, int]:
        return (round(point[0] / tolerance_mm), round(point[1] / tolerance_mm))

    component_nodes: dict[tuple[int, int], set[tuple[int, int]]] = {}
    for start, end, _, _ in segments:
        left, right = node(start), node(end)
        component_nodes.setdefault(left, set()).add(right)
        component_nodes.setdefault(right, set()).add(left)
    visited: set[tuple[int, int]] = set()
    components = 0
    for current in component_nodes:
        if current in visited:
            continue
        components += 1
        stack = [current]
        visited.add(current)
        while stack:
            item = stack.pop()
            for neighbour in component_nodes.get(item, set()):
                if neighbour not in visited:
                    visited.add(neighbour)
                    stack.append(neighbour)

    intersection_keys: set[tuple[float, float]] = set()
    cross_path_intersection_keys: set[tuple[float, float]] = set()
    for left_index, left in enumerate(segments):
        for right in segments[left_index + 1:]:
            if left[2] == right[2] and abs(left[3] - right[3]) <= 1:
                continue
            if (left[0] == right[0] and left[1] == right[1]) or (left[0] == right[1] and left[1] == right[0]):
                continue
            if _segments_intersect(left[0], left[1], right[0], right[1]):
                # Shared endpoints are connectivity, not a crossing.
                shared = any(math.dist(point_a, point_b) <= tolerance_mm for point_a in left[:2] for point_b in right[:2])
                if not shared:
                    key = _intersection_key(left[0], left[1], right[0], right[1])
                    if left[2] == right[2]:
                        intersection_keys.add(key)
                    else:
                        # Different CAD entities may intentionally cross (for
                        # example a court centre line through a centre circle).
                        # Report that for review, but do not call it a
                        # self-intersection of either continuous path.
                        cross_path_intersection_keys.add(key)
    path_self_intersections = len(intersection_keys)
    # Keep the historical field name compatible: callers used this count for
    # every geometric crossing, while only same-path crossings are blocking.
    self_intersections = len(intersection_keys | cross_path_intersection_keys)
    duplicate_geometry_count = 0
    signatures: set[tuple[Any, ...]] = set()
    for path in paths:
        signature = tuple(tuple(round(float(value), 3) for value in point) for point in path)
        reverse = tuple(reversed(signature))
        canonical = min(signature, reverse)
        if len(signature) > 3 and signature[0] == signature[-1]:
            ring = signature[:-1]
            # Closed paths have no distinguished starting vertex. Reversal
            # and cyclic shifts must identify the same physical contour.
            smallest = min(ring)
            canonical = min(
                seq[i:] + seq[:i]
                for seq in (ring, tuple(reversed(ring)))
                for i, point in enumerate(seq) if point == smallest
            )
        if canonical in signatures:
            duplicate_geometry_count += 1
        signatures.add(canonical)
    open_chain_count = sum(1 for path in paths if len(path) >= 2 and math.dist(path[0], path[-1]) * 1000 > tolerance_mm)
    warnings: list[str] = []
    if open_chain_count:
        warnings.append(f"存在 {open_chain_count} 条未闭合路径；开放路径不一定错误，请确认设计意图")
    if self_intersections:
        warnings.append(f"检测到 {self_intersections} 处路径交叉或自相交")
    if cross_path_intersection_keys:
        warnings.append(
            f"检测到 {len(cross_path_intersection_keys)} 处不同图元相交；请确认喷墨顺序"
        )
    if duplicate_geometry_count:
        warnings.append(f"检测到 {duplicate_geometry_count} 条重复几何")
    return {
        "ok": path_self_intersections == 0 and duplicate_geometry_count == 0,
        "errors": list(dict.fromkeys(
            ([f"检测到 {path_self_intersections} 处同一路径自相交"] if path_self_intersections else [])
            + ([f"检测到 {duplicate_geometry_count} 条重复几何"] if duplicate_geometry_count else [])
        )),
        "warnings": warnings,
        "open_chain_count": open_chain_count,
        "closed_loop_count": closed_loop_count,
        "self_intersection_count": self_intersections,
        "path_self_intersection_count": path_self_intersections,
        "cross_path_intersection_count": len(cross_path_intersection_keys),
        "duplicate_geometry_count": duplicate_geometry_count,
        "disconnected_component_count": components,
        "endpoint_count": len(endpoints),
    }


def _geometry_points_for_validation(geometry: dict[str, Any]) -> list[tuple[float, float, float]]:
    values: list[Any] = []
    geometry_type = str(geometry.get("type", "")).lower()
    if geometry_type == "line":
        values = [geometry.get("start"), geometry.get("end")]
    elif geometry_type in {"polyline", "spline"}:
        values = geometry.get("vertices") or geometry.get("control_points") or []
    elif geometry_type in {"circle", "arc", "ellipse"}:
        values = [geometry.get("center")]
        if geometry_type == "ellipse":
            values.append(geometry.get("major_axis"))
    elif geometry_type == "text":
        values = [geometry.get("position")]
    result = []
    for value in values:
        if isinstance(value, dict):
            try:
                result.append((float(value["x"]), float(value["y"]), float(value.get("z", 0.0))))
            except (KeyError, TypeError, ValueError):
                continue
    return result


def check_drawing_feasibility(geometries: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    ids = [item.get("id") for item in geometries]
    if len(ids) != len(set(ids)):
        errors.append("几何 ID 重复")
    valid_paths = preview_paths({"lines": geometries})
    if not valid_paths:
        errors.append("没有可规划的有效几何")

    total_length = 0.0
    for geometry in geometries:
        length = segment_length_m(geometry)
        if length is None or not math.isfinite(length) or length <= 0:
            errors.append(f"几何 {geometry.get('id', '?')} 长度无效")
            continue
        total_length += length
        if length < 0.001:
            warnings.append(f"几何 {geometry.get('id', '?')} 短于 1 mm")
        if geometry.get("type") in {"circle", "arc"}:
            radius_m = float(geometry.get("radius", 0.0)) / 1000.0
            if 0 < radius_m < WHEEL_BASE_M / 2:
                warnings.append(
                    f"几何 {geometry.get('id', '?')} 半径小于半轮距，规划后需重点检查转向"
                )
        if geometry.get("type") == "polyline":
            vertices = geometry.get("vertices") or []
            if len(vertices) >= 2 and any(vertices[index] == vertices[index - 1] for index in range(1, len(vertices))):
                warnings.append(f"几何 {geometry.get('id', '?')} 存在重复顶点")
        for point in _geometry_points_for_validation(geometry):
            if abs(point[2]) > 1e-6:
                warnings.append(f"几何 {geometry.get('id', '?')} 含非零 Z 坐标，二维规划将忽略高度")
                break
    topology = analyze_geometry_topology(geometries)
    bounds = calculate_geometry_bounds(geometries)
    errors.extend(topology["errors"])
    warnings.extend(topology["warnings"])
    warnings.extend(bounds.get("warnings", []))
    errors.extend(bounds.get("errors", []))
    return {
        "ok": not errors,
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
        "geometry_count": len(geometries),
        "preview_path_count": len(valid_paths),
        "printing_length_m": round(total_length, 4),
        "topology": topology,
        "bounds": bounds.get("bounds"),
        "boundary_check": bounds,
    }


def score_design_variant(geometries: list[dict[str, Any]]) -> dict[str, Any]:
    feasibility = check_drawing_feasibility(geometries)
    score = 100
    score -= min(60, len(feasibility["errors"]) * 30)
    score -= min(30, len(feasibility["warnings"]) * 5)
    if feasibility["preview_path_count"] == 0:
        score = 0
    score = max(0, score)
    grade = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "E"
    # Design-stage estimate only. Actual time belongs to the ROS2 planner.
    speed = max(0.01, float(MAX_TASK_LINEAR_VELOCITY))
    printing_length = float(feasibility.get("printing_length_m") or 0.0)
    path_count = int(feasibility.get("preview_path_count") or 0)
    bounds = feasibility.get("bounds") or {}
    width_m = max(0.0, float(bounds.get("width_mm") or 0.0) / 1000.0)
    height_m = max(0.0, float(bounds.get("height_mm") or 0.0) / 1000.0)
    work_zone_size_m = 50.0
    columns = max(1, math.ceil(width_m / work_zone_size_m))
    rows = max(1, math.ceil(height_m / work_zone_size_m))
    minimum_zones_for_path_load = max(1, math.ceil(path_count / 500))
    while rows * columns < minimum_zones_for_path_load:
        current_zone_width = width_m / columns if columns else width_m
        current_zone_height = height_m / rows if rows else height_m
        if current_zone_width >= current_zone_height:
            columns += 1
        else:
            rows += 1
    requires_partitioning = (
        width_m > work_zone_size_m
        or height_m > work_zone_size_m
        or path_count > 500
    )
    project_scale = {
        "schema": "cad.project-scale.v1",
        "width_m": round(width_m, 3),
        "height_m": round(height_m, 3),
        "work_zone_size_m": work_zone_size_m,
        "suggested_rows": rows,
        "suggested_columns": columns,
        "suggested_zone_count": rows * columns,
        "maximum_paths_per_zone": 500,
        "requires_partitioning": requires_partitioning,
        "reason": (
            "图纸跨度或路径数量超过单个施工分区的建议范围"
            if requires_partitioning else "图纸可作为单个施工分区继续规划"
        ),
    }
    estimated_time_sec = printing_length / speed + max(0, path_count - 1) * 2.0
    risks = list(feasibility["warnings"])
    limitations = [
        "这是设计阶段估算，不是 ROS2 实际执行时间",
        "未包含现场障碍物、定位误差和转场路径",
        "最终喷墨路径必须经过 xline_ws3 ROS2 规划器确认",
    ]
    if feasibility["errors"]:
        risks.insert(0, "存在几何错误，当前方案不能直接进入执行")
    if path_count > 20:
        risks.append("路径数量较多，执行前需要重点检查转场和喷码顺序")
    if requires_partitioning:
        risks.append(
            f"大型项目需先分区规划，建议拆分为约 {rows}×{columns} 个施工分区"
        )
        limitations.append("大型图纸将按独立施工区逐区规划和执行，不会整图一次下发")
    risk_level = "high" if feasibility["errors"] else "medium" if risks else "low"
    return {
        "score_type": "design_only",
        "score": score,
        "grade": grade,
        "feasibility": feasibility,
        "metrics": {
            "estimated_time_sec": round(estimated_time_sec, 1),
            "estimated_time_min": round(estimated_time_sec / 60.0, 1),
            "estimate_speed_mps": speed,
        },
        "project_scale": project_scale,
        "risks": list(dict.fromkeys(risks)),
        "risk_level": risk_level,
        "limitations": limitations,
        "change_summary": {
            "geometry_delta": len(geometries),
            "path_delta": path_count,
            "printing_length_delta_m": round(printing_length, 4),
        },
        "requires_ros_planning_score": True,
    }


def layer_drawing_paths(
    geometries: list[dict[str, Any]], printer: str = "center"
) -> dict[str, Any]:
    layered = []
    layer_roles: dict[str, int] = {}
    for geometry in geometries:
        item = dict(geometry)
        requested_semantic = str(item.get("path_semantic") or "").upper()
        role = str(item.get("role", "printing")).lower()
        if requested_semantic in PATH_SEMANTIC_TO_ROLE:
            semantic = requested_semantic
            role = PATH_SEMANTIC_TO_ROLE[semantic]
        else:
            semantic = ROLE_TO_PATH_SEMANTIC.get(role, "DRAW")
        if role not in {"printing", "reference", "annotation", "ignored"}:
            role = "printing"
            semantic = "DRAW"
        if semantic not in layer_roles:
            layer_roles[semantic] = len(layer_roles) + 1
        item["layer_id"] = layer_roles[semantic]
        item["role"] = role
        item["path_semantic"] = semantic
        if role != "printing":
            item["selected"] = False
        layered.append(item)
    route_layers = []
    for semantic, layer_id in layer_roles.items():
        role = PATH_SEMANTIC_TO_ROLE[semantic]
        route_layers.append({
            "layer_id": layer_id,
            "name": semantic,
            "path_semantic": semantic,
            "role": role,
            "route_type": "printing" if role == "printing" else "reference",
            "printer": printer if role == "printing" else None,
        })
    return {
        "layers": route_layers,
        "lines": layered,
        "travel_policy": "generated_by_xline_ws3_planner",
    }


def recommend_recovery(status: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    actions: list[str] = []
    moving = status.get("mission_running") is True or status.get("agent_motion_active") is True
    if status.get("localization_valid") is not True:
        reasons.append("定位无效或过期")
        actions.append("停车后恢复定位，重新规划当前图纸")
    if status.get("control_ready") is not True:
        reasons.append("底盘控制未就绪")
        actions.append("检查 CAN 接口、电机驱动节点和控制权")
    if status.get("printer_ready") is not True and status.get("mission_required_printers"):
        reasons.append("任务所需喷码机未就绪")
        actions.append("保持停车，恢复喷码机后从未完成分段继续")
    obstacle_values = [
        value for value in (status.get("obstacle_distances") or {}).values() if isinstance(value, (int, float))
    ]
    if obstacle_values and min(obstacle_values) < 0.35:
        reasons.append("障碍物距离小于 0.35 m")
        actions.append("清理作业区后重新规划，不自动绕行喷墨路径")
    mission_error = str(status.get("mission_error") or "").strip()
    if mission_error:
        reasons.append(mission_error)
        actions.append("保留任务账本和已完成分段，修复原因后重新预览")
    return {
        "ok": not reasons,
        "stop_required": moving and bool(reasons),
        "auto_resume_allowed": False,
        "reasons": list(dict.fromkeys(reasons)),
        "recommended_actions": list(dict.fromkeys(actions)) or ["当前未发现需要恢复的异常"],
    }
