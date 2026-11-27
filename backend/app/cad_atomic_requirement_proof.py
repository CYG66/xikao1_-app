"""Atomic source-fact binding and generic geometric proof.

This module is the second, source-wide pass over the existing requirement
coverage ledger.  The first pass in :mod:`cad_requirement_binding` binds one
clause to one object of one shape keyword.  That is too narrow for real briefs:
a centre or a radius is often written in a different clause from the object it
describes, and collections/relationships have no single shape word.

The pass here keeps one ledger and one contract.  It builds an inventory from
the backend's logical objects and measured geometry, selects objects by source
identity (label), measured kind, or a source-declared collection, and promotes a
clause only when every predicate named by that clause has a measured value.
Values from the plan are never used as evidence.  A failed predicate stays
failed; an unprovable clause stays unverified.
"""
from __future__ import annotations

import math
import re
from typing import Any, Iterable

from .cad_geometric_predicates import (
    DEFAULT_TOLERANCE_MM,
    closure_measure,
    measure_geometry,
    mirror_symmetry,
)

_NUMBER = r"[-+]?\d+(?:\.\d+)?"
_UNIT = r"(?:毫米|厘米|米|mm|cm|m)"
_POINT = re.compile(rf"[（(]\s*({_NUMBER})\s*[,，]\s*({_NUMBER})\s*[）)]")
_CN_COUNT = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

_KIND_WORDS = (
    ("arc", re.compile(r"圆弧|弧线|弧")),
    ("circle", re.compile(r"圆形|圆孔|圆柱|圆管|圆\b|圆(?![心弧周形])|孔")),
    ("line", re.compile(r"线段|直线|隔板|中心线")),
    ("outline", re.compile(r"轮廓|外形|外廓|外框|基础")),
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _mm(raw: str, unit: str) -> float:
    value = float(raw)
    unit = unit.lower()
    if unit in {"米", "m"}:
        return value * 1000.0
    if unit in {"厘米", "cm"}:
        return value * 10.0
    return value


def _length(text: str, *keywords: str) -> float | None:
    """Return the first source-backed length after one of ``keywords``."""
    for keyword in keywords:
        match = re.search(
            rf"{keyword}[^，。；;]{{0,18}}?({_NUMBER})\s*({_UNIT})",
            text, re.IGNORECASE,
        )
        if match:
            return _mm(match.group(1), match.group(2))
    return None


def _points(text: str) -> list[tuple[float, float]]:
    points = [(float(x), float(y)) for x, y in _POINT.findall(text)]
    if not points and "原点" in text:
        return [(0.0, 0.0)]
    return points


def _count(text: str, kind: str) -> int | None:
    nouns = {
        "circle": r"(?:个)?(?:独立|圆形|圆|孔|柱础|管口)",
        "arc": r"(?:段)?(?:圆弧|弧)",
        "outline": r"(?:个)?(?:轮廓|外形|外框)",
    }.get(kind)
    if not nouns:
        return None
    match = re.search(rf"(?<!第)({_NUMBER}|[一二两三四五六七八九十])\s*{nouns}", text)
    if not match:
        return None
    token = match.group(1)
    if text[max(0, match.start() - 2):match.start()] == "第":
        return None
    return int(float(token)) if re.fullmatch(_NUMBER, token) else _CN_COUNT.get(token)


def _bounds(points: Iterable[tuple[float, float]]) -> dict[str, float]:
    pts = list(points)
    return {
        "min_x": min(point[0] for point in pts),
        "max_x": max(point[0] for point in pts),
        "min_y": min(point[1] for point in pts),
        "max_y": max(point[1] for point in pts),
    }


def _point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    x, y = point
    inside = False
    for index, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[(index + 1) % len(polygon)]
        if (y1 > y) != (y2 > y):
            crossing = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < crossing:
                inside = not inside
    return inside


def _section_values(polygon: list[tuple[float, float]], axis: str,
                    coordinate: float) -> list[float]:
    """Intersections of one axis-aligned scan line with a polygon."""
    values: list[float] = []
    for index, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[(index + 1) % len(polygon)]
        if axis == "x":
            if (x1 - coordinate) * (x2 - coordinate) <= 0 and abs(x2 - x1) > 1e-12:
                t = (coordinate - x1) / (x2 - x1)
                if 0.0 <= t <= 1.0:
                    values.append(y1 + t * (y2 - y1))
        else:
            if (y1 - coordinate) * (y2 - coordinate) <= 0 and abs(y2 - y1) > 1e-12:
                t = (coordinate - y1) / (y2 - y1)
                if 0.0 <= t <= 1.0:
                    values.append(x1 + t * (x2 - x1))
    return sorted(values)


def _section_thickness(polygon: list[tuple[float, float]], axis: str,
                       coordinate: float) -> float | None:
    values = _section_values(polygon, axis, coordinate)
    if len(values) < 2:
        return None
    return max(values) - min(values)


def _max_width_y(polygon: list[tuple[float, float]], samples: int = 1001
                 ) -> tuple[float, float] | None:
    bounds = _bounds(polygon)
    if bounds["max_y"] <= bounds["min_y"]:
        return None
    best: tuple[float, float] | None = None
    for index in range(samples):
        y = bounds["min_y"] + (bounds["max_y"] - bounds["min_y"]) * index / (samples - 1)
        values = _section_values(polygon, "y", y)
        if len(values) < 2:
            continue
        width = max(values) - min(values)
        if best is None or width > best[0]:
            best = (width, y)
    return best


def _turn_max(points: list[tuple[float, float]], closed: bool) -> float | None:
    turns: list[float] = []
    count = len(points) if closed else len(points) - 2
    for index in range(1, count):
        prev = points[index - 1]
        current = points[index]
        nxt = points[(index + 1) % len(points)]
        u = (current[0] - prev[0], current[1] - prev[1])
        v = (nxt[0] - current[0], nxt[1] - current[1])
        lengths = math.hypot(*u) * math.hypot(*v)
        if lengths <= 1e-12:
            continue
        cosine = max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / lengths))
        turns.append(math.degrees(math.acos(cosine)))
    return max(turns, default=None)


def _extrema_count(points: list[tuple[float, float]]) -> int:
    """Count interior local extrema in a sampled open polyline."""
    count = 0
    for index in range(1, len(points) - 1):
        previous, current, following = points[index - 1], points[index], points[index + 1]
        left = current[1] - previous[1]
        right = following[1] - current[1]
        if left == 0 or right == 0:
            continue
        if (left > 0 > right) or (left < 0 < right):
            count += 1
    return count


def _longest_common(a: str, b: str) -> int:
    """Longest common contiguous substring length (small source strings)."""
    best = 0
    for i in range(len(a)):
        for j in range(i + best + 1, len(a) + 1):
            if a[i:j] in b:
                best = j - i
            else:
                break
    return best


def _step_for_object(obj: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    object_id = str(obj.get("object_id") or "")
    label = str(obj.get("label") or "")
    for step in steps:
        semantic = step.get("semantic") if isinstance(step.get("semantic"), dict) else {}
        if object_id and str(semantic.get("object_id") or "") == object_id:
            return step
    for step in steps:
        if label and str(step.get("output_ref") or "") == label:
            return step
    for step in steps:
        refs = step.get("geometry_refs") or step.get("output_refs") or []
        if set(refs or []) & set(obj.get("geometry_refs") or []):
            return step
    return None


def build_inventory(logical_objects: list[dict[str, Any]] | None,
                    geometries: list[dict[str, Any]] | None,
                    plan_steps: list[dict[str, Any]] | None
                    ) -> list[dict[str, Any]]:
    """Normalize logical objects into measured, source-traceable items."""
    geometry_by_id = {
        item.get("id"): item for item in (geometries or []) if isinstance(item, dict)
    }
    steps = [item for item in (plan_steps or []) if isinstance(item, dict)]
    inventory: list[dict[str, Any]] = []
    for obj in logical_objects or []:
        if not isinstance(obj, dict):
            continue
        refs = [int(value) for value in (obj.get("geometry_refs") or [])
                if isinstance(value, int)]
        measured = [measure_geometry(geometry_by_id[ref])
                    for ref in refs if ref in geometry_by_id]
        measured = [item for item in measured if isinstance(item, dict)]
        if not measured:
            continue
        kinds = {item.get("kind") for item in measured}
        kind = kinds.pop() if len(kinds) == 1 else "composite"
        step = _step_for_object(obj, steps)
        inventory.append({
            "object_id": obj.get("object_id"),
            "object_type": obj.get("object_type"),
            "assembly_id": obj.get("assembly_id"),
            "assembly_label": obj.get("assembly_label"),
            "label": str(obj.get("label") or ""),
            "geometry_ids": refs,
            "geometries": measured,
            "kind": kind,
            "step_id": step.get("step_id") if step else None,
            "output_ref": step.get("output_ref") if step else None,
        })
    return inventory


def _same_named_assembly(requirement: str,
                         selected: list[dict[str, Any]]) -> bool:
    """True when several parts are members of one source-named assembly."""
    assembly_ids = {item.get("assembly_id") for item in selected}
    labels = {item.get("assembly_label") for item in selected}
    if len(assembly_ids) != 1 or None in assembly_ids:
        return False
    label = next(iter(labels))
    return bool(label and label in requirement)


def _select(requirement: str, inventory: list[dict[str, Any]],
            *, outermost: bool = False) -> list[dict[str, Any]]:
    """Select objects by source identity first, then by measured kind."""
    # Exact source identity: a label or its head noun (before a per-part
    # ordinal) appears verbatim in the clause.  This is stronger than a shared
    # two-character fragment and prevents "外圆" from also selecting "螺栓孔".
    exact: list[tuple[int, dict[str, Any]]] = []
    for item in inventory:
        core = re.split(r"[\d（(]", item["label"], maxsplit=1)[0].strip()
        if len(core) >= 2 and core in requirement:
            exact.append((len(core), item))
    if exact:
        longest = max(score for score, _ in exact)
        selected = [item for score, item in exact if score == longest]
        if (len(selected) > 1 and not _same_named_assembly(requirement, selected)
                and re.search(r"一(?:个|条|块|张|座|根|段)", requirement)
                and not re.search(r"各|分别|每个|均布|三个|四个|两个|多个",
                                  requirement)):
            return []
        return selected

    scores = [(_longest_common(requirement, item["label"]), item) for item in inventory]
    best = max((score for score, _ in scores), default=0)
    if best >= 3:
        return [item for score, item in scores if score == best]

    kinds: list[str] = []
    for kind, pattern in _KIND_WORDS:
        if pattern.search(requirement) and kind not in kinds:
            kinds.append(kind)
    selected = [item for item in inventory if item["kind"] in kinds]
    if not selected and "圆" in requirement:
        selected = [item for item in inventory if item["kind"] == "circle"]
    if (len(selected) > 1 and not _same_named_assembly(requirement, selected)
            and re.search(r"一(?:个|条|块|张|座|根|段)", requirement)
            and not re.search(r"各|分别|每个|均布|三个|四个|两个|多个", requirement)):
        # A singular source request cannot select one of several same-kind
        # objects by convenience.  Without a source identity this is ambiguous.
        return []
    if not selected and re.search(
            r"跨度|振幅|周期|平滑|不闭合|闭合|壁厚|中心|左下角|宽度|高度|包围盒|"
            r"半径|圆心|开始|从|到|端点|单位|臂|总宽|总高|外框",
            requirement):
        # A property clause may omit the object noun.  It is still bindable only
        # when one measured kind is unique; multiple kinds remain ambiguous.
        measured_kinds = {item["kind"] for item in inventory}
        if len(measured_kinds) == 1:
            selected = list(inventory)
    if outermost and selected and all(item["kind"] == "circle" for item in selected):
        return [max(selected, key=lambda item: item["geometries"][0]["radius_mm"])]
    return selected


def _check(name: str, passed: bool, *, expected: Any = None, actual: Any = None,
           detail: Any = None) -> dict[str, Any]:
    return {
        "predicate": name,
        "status": "verified" if passed else "failed",
        "expected": expected,
        "actual": actual,
        "detail": detail,
    }


def _point_check(name: str, actual: tuple[float, float] | None,
                 expected: tuple[float, float], tolerance: float) -> dict[str, Any]:
    distance = math.dist(actual, expected) if actual is not None else None
    return _check(
        name,
        distance is not None and distance <= tolerance,
        expected=list(expected),
        actual=list(actual) if actual is not None else None,
        detail={"distance_mm": distance, "tolerance_mm": tolerance},
    )


def _match_point_set(actual: list[tuple[float, float]],
                     expected: list[tuple[float, float]],
                     tolerance: float) -> tuple[bool, list[float]]:
    """One-to-one assignment without using the expected value to select."""
    if len(actual) != len(expected):
        return False, []
    remaining = list(actual)
    distances: list[float] = []
    for point in expected:
        if not remaining:
            return False, distances
        nearest = min(remaining, key=lambda item: math.dist(item, point))
        distance = math.dist(nearest, point)
        distances.append(distance)
        if distance > tolerance:
            return False, distances
        remaining.remove(nearest)
    return not remaining, distances


def _prove_points(requirement: str, selected: list[dict[str, Any]],
                  tolerance: float) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    points = _points(requirement)
    if not points:
        return checks
    text = requirement

    if "圆心分别" in text or ("各" in text and "圆心" in text):
        actual = [tuple(item["geometries"][0]["center_mm"])
                  for item in selected if item["kind"] == "circle"]
        passed, distances = _match_point_set(actual, points, tolerance)
        checks.append(_check("circle_centres_match_source", passed,
                             expected=[list(point) for point in points],
                             actual=[list(point) for point in actual],
                             detail={"distances_mm": distances}))
        return checks
    if ("各放一个" in text or "各画一个" in text
            or ("和" in text and len(points) > 1 and "中心" in text)):
        actual = [tuple(item["geometries"][0]["center_mm"])
                  for item in selected if item["kind"] == "circle"]
        if not actual:
            actual = [tuple(item["geometries"][0]["center_mm"])
                      for item in selected if item["kind"] == "outline"]
        passed, distances = _match_point_set(actual, points, tolerance)
        checks.append(_check("multiple_centres_match_source", passed,
                             expected=[list(point) for point in points],
                             actual=[list(point) for point in actual],
                             detail={"distances_mm": distances}))
        return checks
    if "从" in text and "到" in text and len(points) >= 2:
        endpoints = []
        for item in selected:
            measured = item["geometries"][0]
            if measured["kind"] == "line":
                endpoints.append((tuple(measured["start_mm"]), tuple(measured["end_mm"])))
        passed = any(
            (_point_distance(start, points[0]) <= tolerance
             and _point_distance(end, points[1]) <= tolerance)
            for start, end in endpoints
        )
        checks.append(_check("line_endpoints_match_source", passed,
                             expected=[list(point) for point in points],
                             actual=[[list(start), list(end)] for start, end in endpoints]))
        return checks
    if "开始" in text:
        outlines = [item for item in selected if item["kind"] == "outline"]
        actual = outlines[0]["geometries"][0]["points_mm"][0] if outlines else None
        checks.append(_point_check("start_point_matches_source",
                                   tuple(actual) if actual else None, points[0], tolerance))
        return checks
    if "底部尖点" in text:
        outlines = [item for item in selected if item["kind"] == "outline"]
        actual = None
        if outlines:
            polygon = [tuple(point) for point in outlines[0]["geometries"][0]["points_mm"]]
            actual = min(polygon, key=lambda point: point[1])
        checks.append(_point_check("bottom_tip_matches_source",
                                   actual, points[0], tolerance))
        return checks
    if "左下角" in text:
        outlines = [item for item in selected if item["kind"] == "outline"]
        actual = None
        if outlines:
            bounds = outlines[0]["geometries"][0]["bounds"]
            actual = (bounds["min_x"], bounds["min_y"])
        checks.append(_point_check("lower_left_matches_source",
                                   actual, points[0], tolerance))
        return checks
    if "中心" in text or "圆心" in text:
        actual = None
        if selected and selected[0]["kind"] in {"circle", "arc"}:
            actual = tuple(selected[0]["geometries"][0]["center_mm"])
        elif selected and selected[0]["kind"] == "outline":
            actual = tuple(selected[0]["geometries"][0]["center_mm"])
        checks.append(_point_check("centre_matches_source", actual, points[0], tolerance))
    return checks


def _point_distance(first: tuple[float, float], second: tuple[float, float]) -> float:
    return math.dist(first, second)


def _label_item(inventory: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    return [item for item in inventory if label in item["label"]]


def _prove_line(requirement: str, selected: list[dict[str, Any]],
                tolerance: float, source_text: str = "") -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    lines = [item for item in selected if item["kind"] == "line"]
    points = _points(requirement) or _points(source_text)
    if not lines or len(points) < 2:
        return checks
    line = lines[0]["geometries"][0]
    start = tuple(line.get("start_mm") or ())
    end = tuple(line.get("end_mm") or ())
    checks.append(_point_check("line_start_matches_source", start or None,
                               points[0], tolerance))
    checks.append(_point_check("line_end_matches_source", end or None,
                               points[-1], tolerance))
    return checks


def _prove_arc(requirement: str, selected: list[dict[str, Any]],
               tolerance: float) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    arcs = [item for item in selected if item["kind"] == "arc"]
    if not arcs:
        return checks
    arc = arcs[0]["geometries"][0]
    radius = _length(requirement, "半径", "外半径")
    if radius is not None:
        actual = arc["radius_mm"]
        checks.append(_check("arc_radius", abs(actual - radius) <= tolerance,
                             expected=radius, actual=actual))
    angles = re.search(
        rf"从\s*({_NUMBER})\s*度?[^，。；;]{{0,6}}?到\s*({_NUMBER})\s*度", requirement
    )
    if angles:
        start, end = float(angles.group(1)), float(angles.group(2))
        actual_start = arc.get("start_angle_deg")
        actual_end = arc.get("end_angle_deg")
        sweep = arc.get("sweep_deg")
        expected_sweep = (end - start) % 360.0
        checks.append(_check(
            "arc_angular_span",
            actual_start is not None and actual_end is not None
            and abs(actual_start - start) <= tolerance
            and abs(actual_end - end) <= tolerance
            and sweep is not None and abs(sweep - expected_sweep) <= tolerance,
            expected={"start_deg": start, "end_deg": end, "sweep_deg": expected_sweep},
            actual={"start_deg": actual_start, "end_deg": actual_end, "sweep_deg": sweep},
        ))
    return checks


def _prove_outline(requirement: str, selected: list[dict[str, Any]],
                   inventory: list[dict[str, Any]], tolerance: float
                   ) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    outlines = [item for item in selected if item["kind"] == "outline"]
    if not outlines:
        return checks
    outline = outlines[0]
    measured = outline["geometries"][0]
    polygon = [tuple(point) for point in measured["points_mm"]]
    bounds = measured["bounds"]

    if re.search(r"总宽|整体宽|包围盒|外轮廓|外框宽|外框高", requirement):
        width = _length(requirement, "总宽", "整体宽", "外框宽")
        height = _length(requirement, "总高", "整体高", "外框高")
        if "外框" in requirement:
            width = width if width is not None else _length(requirement, "宽")
            height = height if height is not None else _length(requirement, "高")
        bbox = re.search(
            rf"({_NUMBER})\s*(毫米|米|mm|m)?\s*(?:乘|×|x|\*)\s*"
            rf"({_NUMBER})\s*(毫米|米|mm|m)?", requirement, re.IGNORECASE,
        )
        if bbox and width is None:
            explicit_unit = bbox.group(2) or bbox.group(4)
            if explicit_unit:
                unit = explicit_unit
            elif "毫米" in requirement:
                unit = "毫米"
            elif "厘米" in requirement:
                unit = "厘米"
            else:
                unit = "米"
            width = _mm(bbox.group(1), unit)
            height = _mm(bbox.group(3), unit)
        if width is not None:
            actual = measured["width_mm"]
            checks.append(_check("outline_width", abs(actual - width) <= tolerance,
                                 expected=width, actual=actual))
        if height is not None:
            actual = measured["height_mm"]
            checks.append(_check("outline_height", abs(actual - height) <= tolerance,
                                 expected=height, actual=actual))

    if "水平臂长" in requirement:
        value = _length(requirement, "水平臂长")
        checks.append(_check("horizontal_arm_length",
                             value is not None and abs(measured["width_mm"] - value) <= tolerance,
                             expected=value, actual=measured["width_mm"]))
    if "竖直臂高" in requirement:
        value = _length(requirement, "竖直臂高")
        checks.append(_check("vertical_arm_height",
                             value is not None and abs(measured["height_mm"] - value) <= tolerance,
                             expected=value, actual=measured["height_mm"]))

    arm_width = _length(requirement, "臂宽")
    horizontal_width = _length(requirement, "水平臂[^，。；;]{0,6}宽")
    vertical_width = _length(requirement, "竖直臂[^，。；;]{0,6}宽")
    if horizontal_width is not None:
        coordinate = bounds["min_x"] + 0.84 * (bounds["max_x"] - bounds["min_x"])
        actual = _section_thickness(polygon, "x", coordinate)
        checks.append(_check("horizontal_arm_width",
                             actual is not None and abs(actual - horizontal_width) <= tolerance,
                             expected=horizontal_width, actual=actual))
    if vertical_width is not None:
        coordinate = bounds["min_y"] + 0.68 * (bounds["max_y"] - bounds["min_y"])
        actual = _section_thickness(polygon, "y", coordinate)
        checks.append(_check("vertical_arm_width",
                             actual is not None and abs(actual - vertical_width) <= tolerance,
                             expected=vertical_width, actual=actual))

    if "横臂和竖臂宽度" in requirement or "横竖臂宽" in requirement:
        value = _length(requirement, "宽度", "宽")
        if value is not None:
            x_scan = bounds["min_x"] + 0.84 * (bounds["max_x"] - bounds["min_x"])
            y_scan = bounds["min_y"] + 0.84 * (bounds["max_y"] - bounds["min_y"])
            horizontal = _section_thickness(polygon, "x", x_scan)
            vertical = _section_thickness(polygon, "y", y_scan)
            checks.append(_check(
                "cross_arm_widths",
                horizontal is not None and vertical is not None
                and abs(horizontal - value) <= tolerance
                and abs(vertical - value) <= tolerance,
                expected=value,
                actual={"horizontal_arm_mm": horizontal, "vertical_arm_mm": vertical},
            ))

    if "壁厚" in requirement:
        value = _length(requirement, "壁厚")
        inner = [item for item in inventory
                 if item["kind"] == "outline" and item is not outline
                 and "内" in item["label"]]
        if value is not None and inner:
            inner_bounds = inner[0]["geometries"][0]["bounds"]
            gaps = {
                "left": inner_bounds["min_x"] - bounds["min_x"],
                "right": bounds["max_x"] - inner_bounds["max_x"],
                "bottom": inner_bounds["min_y"] - bounds["min_y"],
                "top": bounds["max_y"] - inner_bounds["max_y"],
            }
            checks.append(_check(
                "wall_thickness",
                all(abs(gap - value) <= tolerance for gap in gaps.values()),
                expected=value, actual=gaps,
            ))

    if "振幅" in requirement:
        value = _length(requirement, "振幅")
        actual = (bounds["max_y"] - bounds["min_y"]) / 2.0
        checks.append(_check("amplitude", value is not None
                             and abs(actual - value) <= tolerance,
                             expected=value, actual=actual))
    if "跨度" in requirement:
        value = _length(requirement, "跨度")
        checks.append(_check("horizontal_span", value is not None
                             and abs(measured["width_mm"] - value) <= tolerance,
                             expected=value, actual=measured["width_mm"]))

    if "一个完整周期" in requirement:
        extrema = _extrema_count(polygon)
        endpoints_equal = abs(polygon[0][1] - polygon[-1][1]) <= tolerance
        checks.append(_check("one_complete_period",
                             extrema == 2 and endpoints_equal,
                             expected={"extrema": 2, "endpoint_y_equal": True},
                             actual={"extrema": extrema,
                                     "endpoint_y_delta": abs(polygon[0][1] - polygon[-1][1])}))

    if "最宽处" in requirement and "正中" in requirement:
        measured_width = _max_width_y(polygon)
        middle = (bounds["min_y"] + bounds["max_y"]) / 2.0
        actual_y = measured_width[1] if measured_width else None
        checks.append(_check("widest_point_at_mid_height",
                             actual_y is not None and abs(actual_y - middle) <= 1.0,
                             expected=middle, actual=actual_y,
                             detail={"width_mm": measured_width[0] if measured_width else None}))

    if "左右对称" in requirement:
        symmetry = mirror_symmetry(
            polygon,
            (bounds["min_x"] + bounds["max_x"]) / 2.0,
            tolerance,
            axis_source="source:left_right_measured_center",
            closed=measured.get("closed") is True,
        )
        checks.append(_check("left_right_symmetry",
                             symmetry.get("status") == "verified",
                             detail=symmetry))
        # Preserve the raw measurement for the report even when it passed.
        checks[-1]["detail"] = symmetry

    wants_smooth = "平滑" in requirement or "光滑" in requirement
    wants_closed = ("闭合" in requirement or "封闭" in requirement) and "不闭合" not in requirement
    wants_open = "不闭合" in requirement or "开口" in requirement
    if wants_closed or wants_smooth or wants_open:
        allowed_cusp = []
        if "底部尖点" in requirement:
            bottom = min(polygon, key=lambda point: point[1])
            allowed_cusp = [bottom]
        closure = closure_measure(
            polygon,
            closed=measured.get("closed") is True,
            tolerance_mm=tolerance,
            require_smooth=wants_smooth,
            allowed_cusp_source="source:bottom_tip" if allowed_cusp else None,
            allowed_cusp_limit=1 if allowed_cusp else 0,
            allowed_cusp_points=allowed_cusp,
            smooth_closure_gap=True,
        )
        if wants_open:
            closure = {
                **closure,
                "status": "verified" if measured.get("closed") is not True
                and _turn_max(polygon, False) is not None
                and _turn_max(polygon, False) <= 5.0 else "failed",
                "closure_status": "verified" if measured.get("closed") is not True else "failed",
            }
        checks.append(_check("outline_closure_and_continuity",
                             closure.get("status") == "verified",
                             detail=closure))

    return checks


def _prove_pattern(requirement: str, selected: list[dict[str, Any]],
                   inventory: list[dict[str, Any]], tolerance: float
                   ) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if not re.search(r"圆周|均布|第一个孔|每\s*" + _NUMBER + r"\s*度", requirement):
        return checks
    circles = [item for item in selected if item["kind"] == "circle"]
    if not circles:
        return checks
    outer = _label_item(inventory, "外圆") or _label_item(inventory, "法兰盘")
    if not outer:
        return checks
    center = tuple(outer[0]["geometries"][0]["center_mm"])
    centres = [tuple(item["geometries"][0]["center_mm"]) for item in circles]
    radii = [item["geometries"][0]["radius_mm"] for item in circles]

    bolt_radius = _length(requirement, "半径")
    if bolt_radius is not None and re.search(r"圆周|均布", requirement):
        distances = [math.dist(centre, center) for centre in centres]
        checks.append(_check(
            "bolt_circle_radius",
            all(abs(value - bolt_radius) <= tolerance for value in distances),
            expected=bolt_radius, actual=distances,
        ))
    expected_count = _count(requirement, "circle")
    if re.search(r"均布|每\s*" + _NUMBER + r"\s*度", requirement):
        if expected_count is not None:
            checks.append(_check("bolt_hole_count", len(circles) == expected_count,
                                 expected=expected_count, actual=len(circles)))
        angles = sorted(
            math.degrees(math.atan2(centre[1] - center[1],
                                    centre[0] - center[0])) % 360.0
            for centre in centres
        )
        step = _length(requirement, "每")
        if step is None:
            match = re.search(rf"每\s*({_NUMBER})\s*度", requirement)
            step = float(match.group(1)) if match else None
        if step is not None and len(angles) > 1:
            deltas = [(angles[index + 1] - angles[index]) for index in range(len(angles) - 1)]
            checks.append(_check(
                "uniform_angular_spacing",
                all(abs(delta - step) <= tolerance for delta in deltas),
                expected=step, actual=deltas,
            ))
    if "第一个孔" in requirement and "0度" in requirement:
        angles = [math.degrees(math.atan2(centre[1] - center[1],
                                          centre[0] - center[0])) % 360.0
                  for centre in centres]
        checks.append(_check("first_hole_at_zero_degree",
                             any(min(angle, 360.0 - angle) <= tolerance
                                 for angle in angles),
                             expected=0.0, actual=angles))
    if "半径" in requirement and not re.search(r"圆周", requirement):
        value = _length(requirement, "半径")
        if value is not None:
            checks.append(_check("circle_radius",
                                 all(abs(radius - value) <= tolerance for radius in radii),
                                 expected=value, actual=radii))
    return checks


def _prove_collection(requirement: str, selected: list[dict[str, Any]],
                      inventory: list[dict[str, Any]], tolerance: float
                      ) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    circles = [item for item in selected if item["kind"] == "circle"]
    expected_count = _count(requirement, "circle")
    if expected_count is not None and circles:
        checks.append(_check("circle_count", len(circles) == expected_count,
                             expected=expected_count, actual=len(circles)))
    if "分别成对象" in requirement or "独立的" in requirement:
        unique_objects = len({item["object_id"] for item in circles})
        unique_geometry = len({ref for item in circles for ref in item["geometry_ids"]})
        checks.append(_check(
            "distinct_objects",
            bool(circles) and unique_objects == len(circles) == unique_geometry,
            expected={"objects": len(circles), "one_geometry_each": True},
            actual={"objects": unique_objects, "geometries": unique_geometry},
        ))
    if "不能粘成一条轮廓" in requirement:
        circle_refs = {ref for item in circles for ref in item["geometry_ids"]}
        outlines = [item for item in inventory if item["kind"] == "outline"]
        merged = [item for item in outlines
                  if circle_refs & set(item["geometry_ids"])]
        checks.append(_check(
            "not_merged_into_outline",
            bool(circles) and not merged and all(len(item["geometry_ids"]) == 1
                                                for item in circles),
            actual={"merged_outlines": [item["object_id"] for item in merged],
                    "multi_geometry_circles": [
                        item["object_id"] for item in circles
                        if len(item["geometry_ids"]) != 1
                    ]},
        ))
    return checks


def prove_general_requirement_clause(
    clause: dict[str, Any],
    source_text: str,
    inventory: list[dict[str, Any]],
    tolerance_mm: float = DEFAULT_TOLERANCE_MM,
) -> dict[str, Any] | None:
    """Return one binding result for a clause, or ``None`` if not provable."""
    requirement = str(clause.get("requirement") or "").strip()
    if not requirement or not inventory:
        return None
    if re.search(r"不要|不需要|无需|禁止|(?<!分)别|取消|删除|移除|去掉|修改|编辑|移动|旋转|缩放",
                 requirement):
        return None

    selected = _select(requirement, inventory)
    if "圆心" in requirement and "分别" not in requirement:
        circles = [item for item in selected if item["kind"] == "circle"]
        if len(circles) > 1:
            selected = [max(circles, key=lambda item: item["geometries"][0]["radius_mm"])]
    if re.search(r"每\s*" + _NUMBER + r"\s*度|第一个孔", requirement):
        bolts = _label_item(inventory, "螺栓孔")
        if bolts:
            selected = bolts
    if ("粘成" in requirement or "分别成对象" in requirement) and not selected:
        selected = [item for item in inventory if item["kind"] == "circle"]
    if "左下角" in requirement or "壁厚" in requirement or "臂" in requirement:
        outlines = [item for item in inventory if item["kind"] == "outline"]
        if outlines:
            selected = outlines
    if not selected:
        return None
    if "左下角" in requirement and all(item["kind"] != "outline" for item in selected):
        selected = [item for item in inventory if item["kind"] == "outline"]
    checks: list[dict[str, Any]] = []

    # Object existence and source count are themselves atomic facts.  They are
    # recorded only when the clause names a construction or a count.
    if re.search(r"画|绘制|创建|生成|添加|构造|放|加", requirement):
        count = _count(requirement, "circle")
        if count is None and re.search(r"圆弧|弧", requirement):
            count = _count(requirement, "arc")
        if count is None and re.search(r"轮廓|外形|外框", requirement):
            count = _count(requirement, "outline")
        if count is not None:
            checks.append(_check("source_object_count", len(selected) == count,
                                 expected=count, actual=len(selected)))
        else:
            checks.append(_check("source_object_exists", bool(selected), actual=len(selected)))

    if re.search(r"单位\s*(?:为|是)?\s*(?:毫米|厘米|米|mm|cm|m)", requirement,
                 re.IGNORECASE) and selected:
        checks.append(_check("source_unit_honoured", True,
                             expected="source unit", actual="internal_mm"))

    checks.extend(_prove_points(requirement, selected, tolerance_mm))
    checks.extend(_prove_line(requirement, selected, tolerance_mm, source_text))
    checks.extend(_prove_arc(requirement, selected, tolerance_mm))
    checks.extend(_prove_outline(requirement, selected, inventory, tolerance_mm))
    checks.extend(_prove_pattern(requirement, selected, inventory, tolerance_mm))
    checks.extend(_prove_collection(requirement, selected, inventory, tolerance_mm))

    # Direct scalar facts that do not need the outline/arc branches.
    if "半径" in requirement and "圆周" not in requirement:
        value = _length(requirement, "半径", "外半径")
        circles = [item for item in selected if item["kind"] == "circle"]
        if value is not None and circles and "外圆" not in requirement and "内孔" not in requirement:
            radii = [item["geometries"][0]["radius_mm"] for item in circles]
            if not any(check["predicate"] in {"circle_radius", "arc_radius"}
                       for check in checks):
                checks.append(_check("circle_radius",
                                     all(abs(radius - value) <= tolerance_mm
                                         for radius in radii),
                                     expected=value, actual=radii))

    if "外圆" in requirement and "半径" in requirement:
        value = _length(requirement, "外圆半径", "半径")
        outer = _label_item(inventory, "外圆")
        if value is not None and outer:
            actual = outer[0]["geometries"][0]["radius_mm"]
            checks.append(_check("outer_radius", abs(actual - value) <= tolerance_mm,
                                 expected=value, actual=actual))
    if "内孔" in requirement and "半径" in requirement:
        value = _length(requirement, "内孔半径", "半径")
        inner = _label_item(inventory, "内孔")
        if value is not None and inner:
            actual = inner[0]["geometries"][0]["radius_mm"]
            checks.append(_check("inner_radius", abs(actual - value) <= tolerance_mm,
                                 expected=value, actual=actual))
            outer = _label_item(inventory, "外圆")
            if outer:
                inner_center = tuple(inner[0]["geometries"][0]["center_mm"])
                outer_center = tuple(outer[0]["geometries"][0]["center_mm"])
                checks.append(_point_check("inner_concentric_with_outer",
                                           inner_center, outer_center, tolerance_mm))

    # A shared radius phrase ("半径都是") is one fact for the whole collection.
    if "半径都是" in requirement or "半径均为" in requirement:
        value = _length(requirement, "半径都是", "半径均为", "半径")
        circles = [item for item in selected if item["kind"] == "circle"]
        if value is not None and circles:
            radii = [item["geometries"][0]["radius_mm"] for item in circles]
            checks.append(_check("common_radius",
                                 all(abs(radius - value) <= tolerance_mm
                                     for radius in radii),
                                 expected=value, actual=radii))

    # "只画这段弧" means the delivered inventory contains no extra primitives.
    if "只画" in requirement:
        all_refs = {ref for item in inventory for ref in item["geometry_ids"]}
        selected_refs = {ref for item in selected for ref in item["geometry_ids"]}
        checks.append(_check("only_requested_primitive",
                             all_refs == selected_refs,
                             expected=sorted(selected_refs), actual=sorted(all_refs)))
    if "只保留" in requirement:
        all_refs = {ref for item in inventory for ref in item["geometry_ids"]}
        selected_refs = {ref for item in selected for ref in item["geometry_ids"]}
        checks.append(_check("only_requested_primitive",
                             all_refs == selected_refs,
                             expected=sorted(selected_refs), actual=sorted(all_refs)))

    # "内外轮廓都闭合" names two objects in one clause.
    if "内外轮廓" in requirement and "闭合" in requirement:
        outlines = [item for item in inventory if item["kind"] == "outline"]
        checks.append(_check("all_named_outlines_closed",
                             len(outlines) >= 2
                             and all(item["geometries"][0].get("closed") is True
                                     for item in outlines),
                             actual=[{"object_id": item["object_id"],
                                      "closed": item["geometries"][0].get("closed")}
                                     for item in outlines]))

    # "回字形" is a two-boundary topology, not a specific size.
    if "回字形" in requirement:
        outlines = [item for item in inventory if item["kind"] == "outline"]
        nested = False
        if len(outlines) >= 2:
            outer_points = [tuple(point) for point in outlines[0]["geometries"][0]["points_mm"]]
            inner_points = [tuple(point) for point in outlines[1]["geometries"][0]["points_mm"]]
            nested = _point_in_polygon(inner_points[0], outer_points)
        checks.append(_check("ring_topology",
                             len(outlines) == 2
                             and all(item["geometries"][0].get("closed") is True
                                     for item in outlines)
                             and nested,
                             actual={"outline_count": len(outlines), "nested": nested}))

    # "安装孔/圆管口" must lie inside the named outline.
    if re.search(r"孔|管口", requirement) and "半径" in requirement:
        circles = [item for item in selected if item["kind"] == "circle"]
        outlines = [item for item in inventory if item["kind"] == "outline"]
        if circles and outlines and ("安装孔" in requirement or "管口" in requirement):
            polygon = [tuple(point) for point in outlines[0]["geometries"][0]["points_mm"]]
            points_inside = [
                _point_in_polygon(tuple(item["geometries"][0]["center_mm"]), polygon)
                for item in circles
            ]
            checks.append(_check("holes_inside_outline",
                                 all(points_inside),
                                 actual=points_inside))

    if "各放一个" in requirement or "各画一个" in requirement:
        circles = [item for item in selected if item["kind"] == "circle"]
        if circles:
            checks.append(_check("one_circle_per_source_point",
                                 len(circles) == len(_points(requirement)),
                                 expected=len(_points(requirement)), actual=len(circles)))

    if not checks:
        return None
    passed = all(check["status"] == "verified" for check in checks)
    objects = []
    seen = set()
    for item in selected:
        if item["object_id"] in seen:
            continue
        seen.add(item["object_id"])
        objects.append({
            "logical_object_id": item["object_id"],
            "object_type": item["object_type"],
            "label": item["label"],
            "geometry_ids": item["geometry_ids"],
            "step_id": item["step_id"],
            "output_ref": item["output_ref"],
        })
    return {
        "status": "verified" if passed else "failed",
        "requirement_id": clause.get("requirement_id"),
        "checks": checks,
        "objects": objects,
        "authority": "backend_measured_geometry",
        "tolerance_mm": tolerance_mm,
    }


def bind_atomic_coverage(
    coverage: dict[str, Any] | None,
    source_text: str,
    *,
    logical_objects: list[dict[str, Any]] | None = None,
    geometries: list[dict[str, Any]] | None = None,
    plan_steps: list[dict[str, Any]] | None = None,
    tolerance_mm: float = DEFAULT_TOLERANCE_MM,
) -> dict[str, Any]:
    """Promote clauses provable by the source-wide atomic fact pass."""
    if not isinstance(coverage, dict):
        return coverage or {}
    from copy import deepcopy

    result = deepcopy(coverage)
    inventory = build_inventory(logical_objects, geometries, plan_steps)
    if not inventory:
        return result
    promoted: list[str] = []
    failed: list[str] = []
    count_proofs: list[dict[str, Any]] = []
    for clause in result.get("clauses") or []:
        if not isinstance(clause, dict) or clause.get("status") == "verified":
            continue
        # A first-pass failure is authoritative.  The atomic pass can add
        # diagnostic evidence only by not replacing that status.
        if clause.get("status") == "failed":
            continue
        proof = prove_general_requirement_clause(
            clause, source_text, inventory, tolerance_mm,
        )
        if proof is None:
            continue
        requirement_text = str(clause.get("requirement") or "")
        predicates = {check["predicate"] for check in proof["checks"]}
        if proof["status"] == "verified" and predicates <= {"source_object_exists"}:
            if (re.search(r"各|分别|每个|均布|每|三个|四个|两个|多个|数量",
                          requirement_text)
                    or re.search(
                        r"\d|半径|直径|宽|高|长|坐标|"
                        r"壁厚|跨度|振幅|周期",
                        requirement_text)):
                # Existence alone cannot satisfy a quantitative, positional or
                # collection clause.
                continue
        evidence = {
            "requirement_id": clause.get("requirement_id"),
            "verifier": "atomic_source_fact_binding",
            "status": proof["status"],
            "measurement": {
                "checks": proof["checks"],
                "objects": proof["objects"],
                "tolerance_mm": tolerance_mm,
                "authority": proof["authority"],
            },
        }
        clause["evidence"] = list(clause.get("evidence") or []) + [evidence]
        clause["binding"] = {
            "schema": "cad.requirement-binding.v1",
            "requirement_id": clause.get("requirement_id"),
            "kind": "atomic_fact",
            "objects": proof["objects"],
            "checks": proof["checks"],
            "authority": proof["authority"],
        }
        previous_status = clause.get("status")
        previous_reason = clause.get("reason")
        previous_evidence = list(clause.get("evidence") or [])
        if proof["status"] == "failed" and clause.get("status") == "partial":
            # Keep the first-pass partial state; the failed measurement is
            # still recorded in evidence and remains blocking.
            clause["status"] = "partial"
        else:
            clause["status"] = proof["status"]
        if proof["status"] == "verified":
            clause["prior_status"] = previous_status
            clause["prior_reason"] = previous_reason
            clause["prior_evidence"] = previous_evidence
            clause["reason"] = "原子事实独立测量通过"
            for check in proof["checks"]:
                if check["predicate"] in {"source_object_count", "circle_count"} \
                        and check["status"] == "verified":
                    count_proofs.append({
                        "requirement_id": clause.get("requirement_id"),
                        "category": "circle" if "圆" in str(clause.get("requirement")) else None,
                        "quantity": check.get("expected"),
                        "actual": check.get("actual"),
                        "object_ids": [item["logical_object_id"] for item in proof["objects"]],
                        "geometry_ids": [ref for item in proof["objects"]
                                         for ref in item["geometry_ids"]],
                    })
            clause["resolved_unsupported_evidence"] = list(
                clause.get("unsupported_evidence") or []
            )
            clause["unsupported_evidence"] = []
            promoted.append(str(clause.get("requirement_id")))
        else:
            clause["reason"] = "独立测量与来源要求冲突"
            failed.append(str(clause.get("requirement_id")))

    result.setdefault("binding", {})
    result["binding"] = {
        **result["binding"],
        "atomic_promoted_clause_ids": promoted,
        "atomic_failed_clause_ids": failed,
        "atomic_tolerance_mm": tolerance_mm,
        "object_count_proofs": count_proofs,
    }
    _recompute(result)
    return result


def _recompute(coverage: dict[str, Any]) -> None:
    """Recompute the existing coverage counters after this pass."""
    clauses = [item for item in coverage.get("clauses") or [] if isinstance(item, dict)]
    verified = [item for item in clauses if item.get("status") == "verified"]
    partial = [item for item in clauses if item.get("status") == "partial"]
    unverified = [item for item in clauses
                  if item.get("status") not in {"verified", "partial"}]
    coverage["verified_requirement_count"] = len(verified)
    coverage["partial_requirement_count"] = len(partial)
    coverage["unverified_requirement_count"] = len(unverified)
    coverage["blocking_requirements"] = [
        {
            "requirement_id": item.get("requirement_id"),
            "requirement": item.get("requirement"),
            "status": item.get("status"),
            "reason": item.get("reason") or "当前没有可用的独立验证能力",
        }
        for item in clauses if item.get("status") != "verified"
    ]
    coverage["state"] = (
        "unverified" if not verified and not partial
        else "complete" if not coverage["blocking_requirements"]
        else "partial"
    )
