"""Deterministic, compact semantic catalog for CAD entity targeting."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


_POINT_KEYS = ("start", "end", "center", "position")
_POINT_LIST_KEYS = ("vertices", "control_points")
_EXPLICIT_SEMANTIC_KEYS = ("feature_name", "semantic_name", "semantic", "label", "name")
_TYPE_LABELS = {
    "line": "直线",
    "polyline": "闭合轮廓",
    "circle": "圆",
    "arc": "圆弧",
    "ellipse": "椭圆",
    "spline": "样条曲线",
    "text": "文字",
}
_TEMPLATE_LABELS = {
    "basketball": "篮球场",
    "badminton": "羽毛球场",
    "parking": "车位",
    "parking_lot": "停车场",
    "room": "房间",
    "two_rooms": "两室布局",
    "warehouse": "仓库网格",
    "grid": "施工轴网",
    "corridor": "走廊",
    "foundation": "圆形基础",
}


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _geometry_id(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _points(geometry: dict[str, Any]) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for key in _POINT_KEYS:
        point = geometry.get(key)
        if not isinstance(point, dict):
            continue
        x, y = _number(point.get("x")), _number(point.get("y"))
        if x is not None and y is not None:
            result.append((x, y))
    for key in _POINT_LIST_KEYS:
        values = geometry.get(key)
        if not isinstance(values, list):
            continue
        for point in values:
            if not isinstance(point, dict):
                continue
            x, y = _number(point.get("x")), _number(point.get("y"))
            if x is not None and y is not None:
                result.append((x, y))
    return result


def geometry_bounds(geometry: dict[str, Any]) -> tuple[float, float, float, float] | None:
    points = _points(geometry)
    center = geometry.get("center")
    if isinstance(center, dict):
        cx, cy = _number(center.get("x")), _number(center.get("y"))
        radius: float | None = None
        if geometry.get("type") in {"circle", "arc"}:
            radius = _number(geometry.get("radius"))
        elif geometry.get("type") == "ellipse":
            axis = geometry.get("major_axis")
            if isinstance(axis, dict):
                ax, ay = _number(axis.get("x")), _number(axis.get("y"))
                ratio = _number(geometry.get("ratio")) or 1.0
                if ax is not None and ay is not None:
                    radius = math.hypot(ax, ay) * max(1.0, abs(ratio))
        if cx is not None and cy is not None and radius is not None and radius >= 0:
            points.extend(((cx - radius, cy - radius), (cx + radius, cy + radius)))
    if not points:
        return None
    xs, ys = [item[0] for item in points], [item[1] for item in points]
    return min(xs), min(ys), max(xs), max(ys)


def _combined_bounds(geometries: list[dict[str, Any]]) -> tuple[float, float, float, float] | None:
    bounds = [value for item in geometries if (value := geometry_bounds(item)) is not None]
    if not bounds:
        return None
    return (
        min(item[0] for item in bounds),
        min(item[1] for item in bounds),
        max(item[2] for item in bounds),
        max(item[3] for item in bounds),
    )


def _center(bounds: tuple[float, float, float, float] | None) -> tuple[float, float] | None:
    if bounds is None:
        return None
    return (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2


def _meters(values: tuple[float, ...] | None) -> list[float] | None:
    if values is None:
        return None
    return [round(value / 1000.0, 4) for value in values]


def _explicit_semantic(geometry: dict[str, Any]) -> str | None:
    for key in _EXPLICIT_SEMANTIC_KEYS:
        value = str(geometry.get(key) or "").strip()
        if value:
            return value[:80]
    return None


def _semantic_name(
    geometry: dict[str, Any],
    group_bounds: tuple[float, float, float, float] | None,
) -> tuple[str, str]:
    explicit = _explicit_semantic(geometry)
    if explicit:
        return explicit, "explicit"
    geometry_type = str(geometry.get("type") or "").lower()
    template = str(geometry.get("template_type") or "").lower()
    bounds = geometry_bounds(geometry)
    geometry_center, group_center = _center(bounds), _center(group_bounds)
    centered = bool(
        geometry_center is not None
        and group_center is not None
        and abs(geometry_center[0] - group_center[0]) <= 1e-3
        and abs(geometry_center[1] - group_center[1]) <= 1e-3
    )
    if template == "basketball":
        if geometry_type == "circle" and centered:
            return "中心圆", "template_rule"
        if geometry_type == "polyline" and geometry.get("closed") is True:
            return "外框", "template_rule"
        if geometry_type == "line" and centered:
            return "中线", "template_rule"
    if template == "foundation" and geometry_type == "circle":
        return "基础圆", "template_rule"
    if geometry_type == "polyline" and geometry.get("closed") is not True:
        return "折线", "geometry_rule"
    return _TYPE_LABELS.get(geometry_type, geometry_type or "未知图元"), "geometry_rule"


def _instance_position_labels(
    centers: dict[int, tuple[float, float] | None],
) -> dict[int, str]:
    valid = {key: value for key, value in centers.items() if value is not None}
    if len(valid) <= 1:
        return {}
    xs = [value[0] for value in valid.values()]
    ys = [value[1] for value in valid.values()]
    use_y = max(ys) - min(ys) >= max(xs) - min(xs)
    ordered = sorted(valid, key=lambda key: (valid[key][1 if use_y else 0], key))
    if len(ordered) == 2:
        low, high = ordered
        return {low: "下方" if use_y else "左侧", high: "上方" if use_y else "右侧"}
    direction = "从下到上" if use_y else "从左到右"
    return {key: f"{direction}第{index}个" for index, key in enumerate(ordered, 1)}


_QUADRANT_LABELS = {
    ("北", "东"): "东北",
    ("北", "西"): "西北",
    ("南", "东"): "东南",
    ("南", "西"): "西南",
}


def _region_label(
    center: tuple[float, float] | None,
    bounds: tuple[float, float, float, float] | None,
) -> str | None:
    """Deterministic compass-region name from the drawing-level bounds.

    Splits the drawing with its center lines into 北/南/东/西/中部 regions.
    Never invents a functional label ("施工区" etc.) without evidence.
    """
    if center is None or bounds is None:
        return None
    mid_x = (bounds[0] + bounds[2]) / 2
    mid_y = (bounds[1] + bounds[3]) / 2
    x, y = center
    vertical = "北" if y > mid_y else "南" if y < mid_y else "中"
    horizontal = "东" if x > mid_x else "西" if x < mid_x else "中"
    if vertical == "中" and horizontal == "中":
        return "中部"
    if vertical == "中":
        return f"{horizontal}侧"
    if horizontal == "中":
        return f"{vertical}侧"
    return _QUADRANT_LABELS.get((vertical, horizontal), f"{vertical}{horizontal}侧")


def _layer_names_from_source(source: dict[str, Any] | None) -> dict[int, str] | None:
    """Extract layer_id -> name from a drawing payload's layers list."""
    layers = source.get("layers") if isinstance(source, dict) else None
    if not isinstance(layers, list) or not layers:
        return None
    mapping: dict[int, str] = {}
    for record in layers:
        if not isinstance(record, dict):
            continue
        layer_id = record.get("id")
        name = str(record.get("name") or "").strip()
        if isinstance(layer_id, int) and name:
            mapping[layer_id] = name
    return mapping or None


def _topology_summary(topology: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(topology, dict) or not topology:
        return {"has_topology": False}
    shared = topology.get("shared_boundaries")
    return {
        "has_topology": True,
        "shared_boundary_count": len(shared) if isinstance(shared, list) else 0,
    }


def build_geometry_catalog(
    geometries: list[dict[str, Any]],
    *,
    source: dict[str, Any] | None = None,
    max_elements: int = 120,
    layer_names: dict[int, str] | None = None,
    topology: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a prompt-safe semantic index without inventing domain features."""
    valid = [item for item in geometries if isinstance(item, dict) and _geometry_id(item.get("id"))]
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in valid:
        instance = _geometry_id(item.get("template_instance"))
        if instance is not None:
            groups[instance].append(item)
    group_bounds = {key: _combined_bounds(items) for key, items in groups.items()}
    drawing_bounds = _combined_bounds(valid)
    position_labels = _instance_position_labels({key: _center(value) for key, value in group_bounds.items()})
    resolved_layer_names = layer_names or _layer_names_from_source(source)

    instances: list[dict[str, Any]] = []
    for instance_id in sorted(groups):
        items = groups[instance_id]
        template = next((str(item.get("template_type")) for item in items if item.get("template_type")), "")
        base_label = _TEMPLATE_LABELS.get(template, template or "图形")
        position = position_labels.get(instance_id)
        center = _center(group_bounds[instance_id])
        instances.append({
            "instance_id": instance_id,
            "semantic": f"{position}{base_label}" if position else base_label,
            "template_type": template or None,
            "geometry_ids": sorted(_geometry_id(item.get("id")) for item in items),
            "center_m": _meters(center),
            "bounds_m": _meters(group_bounds[instance_id]),
            **({"region": _region_label(center, drawing_bounds)}
               if _region_label(center, drawing_bounds) else {}),
        })

    elements: list[dict[str, Any]] = []
    for geometry in sorted(valid, key=lambda item: _geometry_id(item.get("id")) or 0)[:max_elements]:
        instance_id = _geometry_id(geometry.get("template_instance"))
        semantic, semantic_source = _semantic_name(geometry, group_bounds.get(instance_id))
        bounds = geometry_bounds(geometry)
        center = _center(bounds)
        item: dict[str, Any] = {
            "geometry_id": _geometry_id(geometry.get("id")),
            "instance_id": instance_id,
            "type": str(geometry.get("type") or "unknown").lower(),
            "semantic": semantic,
            "semantic_source": semantic_source,
            "role": str(geometry.get("role") or "printing").lower(),
            "path_semantic": str(geometry.get("path_semantic") or "DRAW").upper(),
            "center_m": _meters(center),
            "bounds_m": _meters(bounds),
        }
        geometry_layer_id = geometry.get("layer_id")
        if resolved_layer_names and isinstance(geometry_layer_id, int):
            layer_name = resolved_layer_names.get(geometry_layer_id)
            if layer_name:
                item["layer"] = layer_name
        region = _region_label(center, drawing_bounds)
        if region is not None:
            item["region"] = region
        radius = _number(geometry.get("radius"))
        if radius is not None:
            item["radius_m"] = round(radius / 1000.0, 4)
        elements.append(item)

    return {
        "catalog_version": "geometry.catalog.v1",
        "unit": "m",
        "source": dict(source or {}),
        "instance_count": len(instances),
        "element_count": len(valid),
        "truncated": len(valid) > max_elements,
        "topology": _topology_summary(topology),
        "instances": instances,
        "elements": elements,
    }
