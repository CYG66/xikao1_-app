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


def _coordinate_factor(*texts: str) -> float:
    """Millimetres per source coordinate unit.

    A coordinate pair has no unit of its own; it inherits the unit declared in
    the same source or the surrounding request.  Millimetre is checked before
    metre so ``mm`` is not read as ``m``.
    """
    joined = " ".join(text for text in texts if text)
    if re.search(r"毫米|\bmm\b", joined, re.IGNORECASE):
        return 1.0
    if re.search(r"厘米|\bcm\b", joined, re.IGNORECASE):
        return 10.0
    if re.search(r"米|\bm\b", joined, re.IGNORECASE):
        return 1000.0
    return 1.0


def _points(text: str, scale: float = 1.0) -> list[tuple[float, float]]:
    points = [(float(x) * scale, float(y) * scale)
              for x, y in _POINT.findall(text)]
    if not points and "原点" in text:
        return [(0.0, 0.0)]
    return points


def _raw_points(text: str) -> list[tuple[float, float]]:
    return [(float(x), float(y)) for x, y in _POINT.findall(text)]


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


def _section_spans(polygon: list[tuple[float, float]], axis: str,
                   coordinate: float) -> list[float]:
    """Interior spans on one scan line, not the distance across a concavity."""
    values = _section_values(polygon, axis, coordinate)
    return [values[index + 1] - values[index]
            for index in range(0, len(values) - 1, 2)
            if values[index + 1] - values[index] > 1e-9]


def _section_thickness(polygon: list[tuple[float, float]], axis: str,
                       coordinate: float) -> float | None:
    spans = _section_spans(polygon, axis, coordinate)
    return max(spans) if spans else None


def _dominant_section_thickness(
    polygon: list[tuple[float, float]], axis: str, tolerance: float,
    samples: int = 257,
) -> dict[str, float] | None:
    """Measure a stable section thickness without a case-specific position.

    Arm widths are the thickness of the arm away from its junction.  Sampling
    the whole bounding interval and taking the largest consistent thickness
    cluster finds that arm generically for L, T and cross outlines, and returns
    ``None`` when the profile has no stable band instead of guessing a point.
    """
    bounds = _bounds(polygon)
    low, high = ((bounds["min_x"], bounds["max_x"]) if axis == "x"
                 else (bounds["min_y"], bounds["max_y"]))
    if high <= low:
        return None
    values: list[float] = []
    for index in range(samples):
        coordinate = low + (high - low) * index / (samples - 1)
        span = _section_thickness(polygon, axis, coordinate)
        if span is not None:
            values.append(span)
    if not values:
        return None
    values.sort()
    cluster_tolerance = max(float(tolerance), 0.5)
    clusters: list[list[float]] = []
    for value in values:
        if not clusters or value - clusters[-1][-1] > cluster_tolerance:
            clusters.append([value])
        else:
            clusters[-1].append(value)
    cluster = max(clusters, key=len)
    coverage = len(cluster) / len(values)
    if len(cluster) < 3 or coverage < 0.2:
        return None
    if cluster[-1] - cluster[0] > max(2.0 * cluster_tolerance, 1.0):
        return None
    ordered = sorted(cluster)
    return {
        "value": ordered[len(ordered) // 2],
        "coverage": coverage,
        "sample_count": float(len(values)),
        "cluster_count": float(len(cluster)),
        "minimum": ordered[0],
        "maximum": ordered[-1],
    }


def _distance_point_segment(point: tuple[float, float],
                            start: tuple[float, float],
                            end: tuple[float, float]) -> float:
    px, py = point
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-18:
        return math.dist(point, start)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_sq))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _distance_to_polygon(point: tuple[float, float],
                         polygon: list[tuple[float, float]]) -> float:
    return min(_distance_point_segment(point, polygon[index],
                                       polygon[(index + 1) % len(polygon)])
               for index in range(len(polygon)))


def _segments_cross(first_start: tuple[float, float],
                    first_end: tuple[float, float],
                    second_start: tuple[float, float],
                    second_end: tuple[float, float],
                    tolerance: float) -> bool:
    """True only for a proper crossing; touching endpoints do not count."""
    def orientation(a, b, c):
        value = ((b[0] - a[0]) * (c[1] - a[1])
                 - (b[1] - a[1]) * (c[0] - a[0]))
        if abs(value) <= tolerance * max(1.0, math.dist(a, b)):
            return 0
        return 1 if value > 0 else -1

    o1 = orientation(first_start, first_end, second_start)
    o2 = orientation(first_start, first_end, second_end)
    o3 = orientation(second_start, second_end, first_start)
    o4 = orientation(second_start, second_end, first_end)
    return o1 * o2 < 0 and o3 * o4 < 0


def _polygon_contains(outer: list[tuple[float, float]],
                      inner: list[tuple[float, float]],
                      tolerance: float, *,
                      allow_boundary: bool = True) -> bool:
    """Prove that the whole inner boundary lies inside the outer boundary.

    A single vertex is not enough: every vertex must be inside or on the
    boundary, no two boundaries may properly cross, and at least one vertex
    must be strictly inside.  Boundary contact is allowed only when the caller
    explicitly permits it.
    """
    if len(outer) < 3 or len(inner) < 3:
        return False
    strictly_inside = False
    for point in inner:
        if _point_in_polygon(point, outer):
            strictly_inside = True
            continue
        if not allow_boundary or _distance_to_polygon(point, outer) > tolerance:
            return False
    for index in range(len(inner)):
        inner_start = inner[index]
        inner_end = inner[(index + 1) % len(inner)]
        for edge in range(len(outer)):
            if _segments_cross(inner_start, inner_end, outer[edge],
                               outer[(edge + 1) % len(outer)], tolerance):
                return False
    return strictly_inside


def _circle_inside_polygon(center: tuple[float, float], radius: float,
                           polygon: list[tuple[float, float]],
                           tolerance: float, samples: int = 32) -> bool:
    """A hole is inside only when its whole boundary is inside."""
    if not _point_in_polygon(center, polygon) \
            and _distance_to_polygon(center, polygon) > tolerance:
        return False
    for index in range(samples):
        angle = 2.0 * math.pi * index / samples
        point = (center[0] + radius * math.cos(angle),
                 center[1] + radius * math.sin(angle))
        if not _point_in_polygon(point, polygon) \
                and _distance_to_polygon(point, polygon) > tolerance:
            return False
    return True


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


def _object_anchor_points(item: dict[str, Any]) -> list[tuple[float, float]]:
    """Measured anchors that can bind a source point to one object."""
    anchors: list[tuple[float, float]] = []
    for measured in item.get("geometries") or []:
        if not isinstance(measured, dict):
            continue
        if measured.get("kind") in {"circle", "arc"}:
            center = tuple(measured.get("center_mm") or ())
            if len(center) == 2:
                anchors.append(center)
        elif measured.get("kind") == "line":
            for key in ("start_mm", "end_mm"):
                point = tuple(measured.get(key) or ())
                if len(point) == 2:
                    anchors.append(point)
        else:
            anchors.extend(tuple(point) for point in measured.get("points_mm") or []
                           if len(point) == 2)
            # An outline's measured centre is also a source-identifying
            # anchor: a "中心在(x,y)" clause names the object by that point.
            center = tuple(measured.get("center_mm") or ())
            if len(center) == 2:
                anchors.append(center)
    return anchors


def _exact_label_core(label: str) -> str:
    return re.split(r"[\d（(]", label, maxsplit=1)[0].strip()


def _source_declares_collection(requirement: str) -> bool:
    return bool(re.search(
        r"各|分别|每个|均布|每|三个|四个|两个|多个|数量|独立的|"
        r"半径都是|半径均为|一组|若干",
        requirement,
    ))


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


def _select(requirement: str, inventory: list[dict[str, Any]], *,
            points: list[tuple[float, float]] | None = None,
            tolerance: float = DEFAULT_TOLERANCE_MM) -> list[dict[str, Any]]:
    """Select only by source identity, measured anchor or unique kind.

    Fuzzy substring scores and largest-radius convenience are deliberately not
    authorities.  They may help a human reviewer, but cannot decide which
    physical object a source fact names.
    """
    universal = bool(re.search(r"都|均|各|分别|全部|所有", requirement))
    exact: list[tuple[int, dict[str, Any]]] = []
    for item in inventory:
        core = _exact_label_core(item["label"])
        if len(core) >= 2 and core in requirement:
            exact.append((len(core), item))
    if exact:
        longest = max(score for score, _ in exact)
        selected = [item for score, item in exact if score == longest]
        if (len(selected) > 1 and not _same_named_assembly(requirement, selected)
                and not _source_declares_collection(requirement)
                and not universal):
            return []
        if (len(selected) == 1
                and sum(1 for item in inventory
                        if item["kind"] == selected[0]["kind"]) > 1
                and not _source_declares_collection(requirement)
                and not universal):
            # A singular clause that names one member while another object of
            # the same kind exists has not identified its target.  A label
            # match alone cannot make that choice.
            return []
        return selected

    # A source coordinate or endpoint can identify one measured object without
    # guessing from a label.  It is authoritative only when exactly one object
    # of the source-named kind owns each anchor; coincident candidates stay
    # ambiguous.
    kinds: list[str] = []
    for kind, pattern in _KIND_WORDS:
        if pattern.search(requirement) and kind not in kinds:
            kinds.append(kind)
    point_pool = [item for item in inventory if item["kind"] in kinds] if kinds else inventory
    if points:
        matched: list[dict[str, Any]] = []
        for point in points:
            hits = [
                item for item in point_pool
                if any(math.dist(anchor, point) <= tolerance
                       for anchor in _object_anchor_points(item))
            ]
            if len(hits) != 1:
                return []
            if hits[0] not in matched:
                matched.append(hits[0])
        if len(matched) == len(points):
            return matched
        if len(matched) == 1 and len(points) > 1:
            # Several source points can describe one object (a line's two
            # endpoints, an arc's centre and endpoints).  That is still one
            # authoritative object unless the source asks for a collection.
            count = (_count(requirement, "circle") or _count(requirement, "arc")
                     or _count(requirement, "outline"))
            if count in (None, 1):
                return matched
        return []

    selected = [item for item in inventory if item["kind"] in kinds]
    if not selected and "圆" in requirement:
        selected = [item for item in inventory if item["kind"] == "circle"]
    if (len(selected) > 1 and not _same_named_assembly(requirement, selected)
            and not _source_declares_collection(requirement)
            and not universal):
        # A singular source request cannot select one of several same-kind
        # objects by convenience.  Without a source identity this is ambiguous.
        return []
    if selected:
        return selected

    if re.search(
            r"跨度|振幅|周期|平滑|不闭合|闭合|壁厚|中心|左下角|宽度|高度|包围盒|"
            r"半径|圆心|开始|从|到|端点|单位|臂|总宽|总高|外框|宽|高",
            requirement):
        # A property clause may omit the object noun.  It is still bindable only
        # when one measured kind is unique; multiple kinds remain ambiguous.
        measured_kinds = {item["kind"] for item in inventory}
        universal = bool(re.search(r"都|均|各|分别|全部|所有", requirement))
        if (len(measured_kinds) == 1
                and (len(inventory) == 1 or universal)):
            return list(inventory)
    return []


def _identity_evidence(requirement: str, inventory: list[dict[str, Any]],
                       selected: list[dict[str, Any]],
                       points: list[tuple[float, float]],
                       tolerance: float) -> dict[str, Any]:
    """Describe why the selected objects are, or are not, authoritative."""
    labels = [item["label"] for item in selected]
    exact = [item for item in selected
             if len(_exact_label_core(item["label"])) >= 2
             and _exact_label_core(item["label"]) in requirement]
    if not selected:
        mode = "ambiguous_or_unbound"
    elif len(exact) == len(selected):
        mode = ("source_declared_collection"
                if _source_declares_collection(requirement)
                else "exact_source_label")
    elif points and len(points) == len(selected):
        mode = "measured_source_anchor"
    elif len({item["kind"] for item in selected}) == 1:
        mode = ("source_declared_collection"
                if _source_declares_collection(requirement)
                else "unique_measured_kind")
    else:
        mode = "unique_inventory_kind"
    return {
        "mode": mode,
        "authoritative": bool(selected) and mode != "ambiguous_or_unbound",
        "candidate_count": len(inventory),
        "selected_count": len(selected),
        "selected_labels": labels,
        "selected_object_ids": [item.get("object_id") for item in selected],
        "source_anchors": [list(point) for point in points],
        "tolerance_mm": tolerance,
    }


def _canonical_contract_fact(name: str, requirement: str) -> str:
    lowered = name.lower()
    if ("width" in lowered or "宽" in name) and "臂" in requirement:
        return "dimension:arm_width"
    if "width" in lowered or "宽" in name:
        return "dimension:width"
    if "height" in lowered or "高" in name:
        return "dimension:height"
    if "radius" in lowered or "半径" in name:
        return "dimension:radius"
    if "count" in lowered or "数量" in name or "count" in name:
        return "count"
    return f"contract:{name}"


def _mandatory_facts(requirement: str, clause: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build the complete fact list implied by one source clause.

    Checks alone are not a fact list: a clause can omit a fact from every
    generated check.  This function derives facts from the source text and from
    the contract evidence carried by the clause, then requires an explicit
    verified check for each of them.
    """
    facts: dict[str, dict[str, Any]] = {}

    def need(fact_id: str, status: str, *, expected: Any = None,
             actual: Any = None, detail: Any = None) -> None:
        existing = facts.get(fact_id)
        if existing is not None:
            if existing.get("status") == "measured" or status != "measured":
                return
        facts[fact_id] = {
            "fact": fact_id,
            "status": status,
            "expected": expected,
            "actual": actual,
            "detail": detail,
        }

    for evidence in clause.get("unsupported_evidence") or []:
        if isinstance(evidence, str):
            name = evidence
            payload: dict[str, Any] = {}
        elif isinstance(evidence, dict):
            name = str(evidence.get("fact") or evidence.get("name")
                       or evidence.get("key") or evidence.get("predicate") or "")
            payload = evidence
        else:
            continue
        if not name:
            continue
        fact_id = _canonical_contract_fact(name, requirement)
        need(fact_id, "contract_required",
             expected=payload.get("expected"), actual=payload.get("actual"),
             detail={"source": "contract", "name": name, "raw": payload})

    dimension_specs: list[tuple[tuple[str, ...], str]] = [
        (("总宽", "整体宽", "外框宽"), "dimension:width"),
        (("总高", "整体高", "外框高"), "dimension:height"),
        (("水平臂长",), "dimension:horizontal_arm_length"),
        (("竖直臂高",), "dimension:vertical_arm_height"),
        (("壁厚",), "dimension:wall_thickness"),
        (("跨度",), "dimension:span"),
        (("振幅",), "dimension:amplitude"),
        (("外圆半径",), "dimension:outer_radius"),
        (("外半径",), "dimension:outer_radius"),
        (("内孔半径",), "dimension:inner_radius"),
        (("内半径",), "dimension:inner_radius"),
        (("半径",), "dimension:radius"),
        (("直径",), "dimension:diameter"),
    ]
    for keywords, fact_id in dimension_specs:
        if not any(keyword in requirement for keyword in keywords):
            continue
        value = _length(requirement, *keywords)
        if value is not None:
            need(fact_id, "measured", expected=value)

    for keyword, fact_id in (
            ("水平臂[^，。；;]{0,20}宽", "dimension:horizontal_arm_width"),
            ("竖直臂[^，。；;]{0,20}宽", "dimension:vertical_arm_width"),
    ):
        value = _length(requirement, keyword)
        if value is not None:
            need(fact_id, "measured", expected=value, detail={"source_keyword": keyword})

    if "臂" in requirement and "宽" in requirement \
            and not re.search(r"水平臂|竖直臂|横臂|竖臂|总宽|外框", requirement):
        value = _length(requirement, "宽")
        if value is not None:
            need("dimension:arm_width", "measured", expected=value)

    bbox = re.search(
        rf"({_NUMBER})\s*({_UNIT})\s*(?:乘|×|x|\*)\s*"
        rf"({_NUMBER})\s*({_UNIT})", requirement, re.IGNORECASE,
    )
    if bbox:
        need("dimension:width", "measured",
             expected=_mm(bbox.group(1), bbox.group(2)),
             detail={"bbox": True})
        need("dimension:height", "measured",
             expected=_mm(bbox.group(3), bbox.group(4)),
             detail={"bbox": True})

    for index, point in enumerate(_raw_points(requirement)):
        need(f"point:{index}", "measured", expected=list(point))

    point_scale = _coordinate_factor(requirement, str(clause.get("source_text") or ""))
    if point_scale != 1.0:
        need("unit", "measured", expected="source_coordinate_unit",
             actual=point_scale,
             detail={"kind": "coordinate_scale", "factor": point_scale})

    conversions = [
        {
            "raw": float(match.group(1)),
            "unit": match.group(2),
            "factor": _mm(1.0, match.group(2)),
        }
        for match in re.finditer(rf"({_NUMBER})\s*({_UNIT})", requirement,
                                 re.IGNORECASE)
    ]
    if conversions:
        need("unit", "measured", expected="source_declared_unit",
             detail={"conversions": conversions})

    if re.search(r"各放一个|各画一个|分别放|分别画", requirement):
        need("count:per_point", "measured",
             expected=len(_raw_points(requirement)))

    if "闭合" in requirement and "不闭合" not in requirement:
        need("closure", "measured", expected="closed")
    if re.search(r"不闭合|断开|开口", requirement):
        need("open", "measured", expected="open")
    if re.search(r"平滑|光滑|连续", requirement):
        need("continuity", "measured", expected="continuous")
    if "左右对称" in requirement:
        need("symmetry", "measured", expected="mirror")
    if re.search(r"回字形|内外轮廓|内外边界", requirement):
        need("ring_topology", "measured")
    if re.search(r"孔|管口", requirement) and "半径" in requirement:
        need("holes_inside", "measured")
    if "半径都是" in requirement or "半径均为" in requirement:
        need("common_radius", "measured")
    if "最宽处" in requirement and "正中" in requirement:
        need("widest_at_mid", "measured")
    if "一个完整周期" in requirement:
        need("period", "measured")
    if "只画" in requirement or "只保留" in requirement:
        need("only_requested", "measured")
    if re.search(r"不能粘|分开|独立|不同对象|分别成对象", requirement):
        need("distinct_objects", "measured")
        need("not_merged", "measured")
    if "同心" in requirement:
        need("concentric", "measured")

    count = _count(requirement, "circle")
    if count is None and re.search(r"圆弧|弧", requirement):
        count = _count(requirement, "arc")
    if count is None and re.search(r"轮廓|外形|外框", requirement):
        count = _count(requirement, "outline")
    if count is not None:
        need("count", "measured", expected=count)
    elif re.search(r"画|绘制|创建|生成|添加|构造|放|加", requirement):
        need("object_exists", "measured")

    identity_required = bool(
        _raw_points(requirement)
        or any(value.get("status") == "measured"
               for key, value in facts.items()
               if key.startswith("dimension:") or key in {
                   "closure", "open", "continuity", "symmetry", "ring_topology",
                   "holes_inside", "common_radius", "period", "distinct_objects",
                   "not_merged", "concentric", "count",
               })
    )
    if identity_required:
        need("object_identity", "measured")
    return facts


def _measurement_values(selected: list[dict[str, Any]],
                        tolerance: float) -> list[float]:
    values: list[float] = []
    for item in selected:
        for measured in item.get("geometries") or []:
            if not isinstance(measured, dict):
                continue
            if measured.get("kind") in {"circle", "arc"}:
                values.append(float(measured.get("radius_mm") or 0.0))
                values.extend(float(value) for value in measured.get("center_mm") or [])
            elif measured.get("kind") == "line":
                values.extend(float(value) for value in measured.get("start_mm") or [])
                values.extend(float(value) for value in measured.get("end_mm") or [])
            else:
                polygon = [tuple(point) for point in measured.get("points_mm") or []]
                if not polygon:
                    continue
                bounds = measured.get("bounds") or _bounds(polygon)
                values.extend([bounds["min_x"], bounds["max_x"],
                               bounds["min_y"], bounds["max_y"],
                               measured.get("width_mm") or 0.0,
                               measured.get("height_mm") or 0.0])
                for axis in ("x", "y"):
                    dominant = _dominant_section_thickness(polygon, axis, tolerance)
                    if dominant:
                        values.append(dominant["value"])
    return [value for value in values if math.isfinite(value)]


def _unit_conversion_evidence(requirement: str,
                              selected: list[dict[str, Any]],
                              tolerance: float) -> dict[str, Any]:
    conversions = [
        {
            "raw": float(match.group(1)),
            "unit": match.group(2),
            "declared_factor": _mm(1.0, match.group(2)),
            "internal_mm": float(match.group(1)) * _mm(1.0, match.group(2)),
        }
        for match in re.finditer(rf"({_NUMBER})\s*({_UNIT})", requirement,
                                 re.IGNORECASE)
    ]
    actual = _measurement_values(selected, tolerance)
    for conversion in conversions:
        conversion["matched_measurement_mm"] = next(
            (value for value in actual
             if abs(value - conversion["internal_mm"]) <= tolerance),
            None,
        )
    return {
        "conversions": conversions,
        "measurement_values_mm": actual,
        "verified": bool(conversions)
        and all(item["declared_factor"] > 0 for item in conversions)
        and any(item["matched_measurement_mm"] is not None
                for item in conversions),
    }


_PREDICATE_FACT_COVERAGE: dict[str, set[str]] = {
    "source_object_exists": {"object_exists"},
    "object_identity_binding": {"object_identity"},
    "outline_width": {"dimension:width"},
    "outline_height": {"dimension:height"},
    "horizontal_arm_length": {"dimension:horizontal_arm_length"},
    "horizontal_arm_width": {"dimension:horizontal_arm_width",
                             "dimension:arm_width"},
    "vertical_arm_height": {"dimension:vertical_arm_height"},
    "vertical_arm_width": {"dimension:vertical_arm_width",
                           "dimension:arm_width"},
    "cross_arm_widths": {"dimension:horizontal_arm_width",
                         "dimension:vertical_arm_width",
                         "dimension:arm_width"},
    "wall_thickness": {"dimension:wall_thickness"},
    "outline_closure_and_continuity": {"closure", "continuity", "open"},
    "all_named_outlines_closed": {"closure"},
    "left_right_symmetry": {"symmetry"},
    "widest_point_at_mid_height": {"widest_at_mid"},
    "widest_at_mid_height": {"widest_at_mid"},
    "horizontal_span": {"dimension:span"},
    "amplitude": {"dimension:amplitude"},
    "one_complete_period": {"period"},
    "circle_radius": {"dimension:radius"},
    "source_unit_honoured": {"unit"},
    "source_unit_conversion": {"unit"},
    "inner_concentric_with_outer": {"concentric"},
    "line_endpoints_match_source": {"point:0", "point:1"},
    "line_length": {"dimension:line_length"},
    "circle_count": {"count"},
    "source_object_count": {"count"},
    "distinct_objects": {"distinct_objects"},
    "not_merged": {"not_merged"},
    "circle_centres_match_source": {"point:0", "point:1", "point:2",
                                    "point:3", "point:4", "point:5"},
    "multiple_centres_match_source": {"point:0", "point:1", "point:2",
                                      "point:3", "point:4", "point:5"},
    "radius_matches_source": {"dimension:radius"},
    "common_radius": {"dimension:radius"},
    "outer_radius": {"dimension:outer_radius", "dimension:radius"},
    "inner_radius": {"dimension:inner_radius"},
    "ring_topology": {"ring_topology"},
    "holes_inside_outline": {"holes_inside"},
    "one_circle_per_source_point": {"count:per_point"},
    "inner_concentric": {"concentric"},
    "arc_radius": {"dimension:radius"},
    "arc_angular_span": {"arc_angles"},
    "only_requested_primitive": {"only_requested"},
    "line_start_matches_source": {"point:0"},
    "line_end_matches_source": {"point:1"},
    "line_length": {"dimension:line_length"},
    "lower_left_matches_source": {"point:0"},
    "centre_matches_source": {"point:0"},
    "bottom_tip_matches_source": {"point:0"},
    "start_point_matches_source": {"point:0"},
    "source_unit_conversion": {"unit"},
}


def _check(name: str, passed: bool, *, expected: Any = None, actual: Any = None,
           detail: Any = None,
           covers: set[str] | list[str] | tuple[str, ...] | None = None
           ) -> dict[str, Any]:
    return {
        "predicate": name,
        "status": "verified" if passed else "failed",
        "expected": expected,
        "actual": actual,
        "detail": detail,
        "covers": sorted(set(covers or _PREDICATE_FACT_COVERAGE.get(name, set()))),
    }


def _point_check(name: str, actual: tuple[float, float] | None,
                 expected: tuple[float, float], tolerance: float,
                 covers: set[str] | None = None) -> dict[str, Any]:
    distance = math.dist(actual, expected) if actual is not None else None
    return _check(
        name,
        distance is not None and distance <= tolerance,
        expected=list(expected),
        actual=list(actual) if actual is not None else None,
        detail={"distance_mm": distance, "tolerance_mm": tolerance},
        covers=covers,
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
                  tolerance: float, source_text: str = "") -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    points = _points(requirement,
                     _coordinate_factor(requirement, source_text))
    if not points:
        return checks
    all_point_facts = {f"point:{index}" for index in range(len(points))}
    text = requirement

    if "圆心分别" in text or ("各" in text and "圆心" in text):
        actual = [tuple(item["geometries"][0]["center_mm"])
                  for item in selected if item["kind"] == "circle"]
        passed, distances = _match_point_set(actual, points, tolerance)
        checks.append(_check("circle_centres_match_source", passed,
                             expected=[list(point) for point in points],
                             actual=[list(point) for point in actual],
                             detail={"distances_mm": distances},
                             covers=all_point_facts))
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
                             detail={"distances_mm": distances},
                             covers=all_point_facts))
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
                             actual=[[list(start), list(end)] for start, end in endpoints],
                             covers={f"point:{index}" for index in range(len(points))}))
        if len(points) == 2:
            expected_length = math.dist(points[0], points[1])
            actual_lengths = [math.dist(start, end) for start, end in endpoints]
            checks.append(_check(
                "line_length",
                bool(actual_lengths)
                and all(abs(length - expected_length) <= tolerance
                        for length in actual_lengths),
                expected=expected_length,
                actual=actual_lengths,
            ))
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
    points = _points(requirement, _coordinate_factor(requirement)) \
        or _points(source_text, _coordinate_factor(requirement, source_text))
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
    horizontal_width = _length(requirement, "水平臂[^，。；;]{0,20}宽")
    vertical_width = _length(requirement, "竖直臂[^，。；;]{0,20}宽")
    horizontal = _dominant_section_thickness(polygon, "x", tolerance)
    vertical = _dominant_section_thickness(polygon, "y", tolerance)
    if horizontal_width is not None:
        checks.append(_check(
            "horizontal_arm_width",
            horizontal is not None
            and abs(horizontal["value"] - horizontal_width) <= tolerance,
            expected=horizontal_width,
            actual=horizontal["value"] if horizontal else None,
            detail={"measurement": horizontal, "method": "dominant_stable_section"},
        ))
    if vertical_width is not None:
        checks.append(_check(
            "vertical_arm_width",
            vertical is not None
            and abs(vertical["value"] - vertical_width) <= tolerance,
            expected=vertical_width,
            actual=vertical["value"] if vertical else None,
            detail={"measurement": vertical, "method": "dominant_stable_section"},
        ))

    if "横臂和竖臂宽度" in requirement or "横竖臂宽" in requirement:
        value = _length(requirement, "宽度", "宽")
        if value is not None:
            checks.append(_check(
                "cross_arm_widths",
                horizontal is not None and vertical is not None
                and abs(horizontal["value"] - value) <= tolerance
                and abs(vertical["value"] - value) <= tolerance,
                expected=value,
                actual={
                    "horizontal_arm_mm": horizontal["value"] if horizontal else None,
                    "vertical_arm_mm": vertical["value"] if vertical else None,
                },
                detail={"horizontal": horizontal, "vertical": vertical,
                        "method": "dominant_stable_section"},
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
                             expected=expected_count, actual=len(circles),
                             covers={"count"}))
    if ("分别成对象" in requirement or "独立的" in requirement
            or "不能粘" in requirement or "分开" in requirement):
        unique_objects = len({item["object_id"] for item in circles})
        unique_geometry = len({ref for item in circles for ref in item["geometry_ids"]})
        checks.append(_check(
            "distinct_objects",
            bool(circles) and unique_objects == len(circles) == unique_geometry,
            expected={"objects": len(circles), "one_geometry_each": True},
            actual={"objects": unique_objects, "geometries": unique_geometry},
            covers={"distinct_objects", "not_merged"},
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
            covers={"not_merged"},
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
    # "新建图纸" is an operation, not a geometric object.  It is proved only by
    # the project/write receipt path, never by finding an unrelated object.
    if (re.search(r"新建|创建|生成", requirement)
            and "图纸" in requirement
            and not re.search(r"矩形|圆|弧|线|轮廓|外形|支架|板|孔", requirement)):
        return None

    source_points = _points(requirement, _coordinate_factor(requirement, source_text))
    selected = _select(requirement, inventory, points=source_points,
                       tolerance=tolerance_mm)
    if re.search(r"每\s*" + _NUMBER + r"\s*度|第一个孔", requirement):
        bolts = _label_item(inventory, "螺栓孔")
        if bolts:
            selected = bolts
    if ("粘成" in requirement or "分别成对象" in requirement) and not selected:
        selected = [item for item in inventory if item["kind"] == "circle"]
    if "壁厚" in requirement:
        outlines = [item for item in inventory if item["kind"] == "outline"]
        if len(outlines) >= 2:
            selected = outlines
    elif "左下角" in requirement or "臂" in requirement:
        outlines = [item for item in inventory if item["kind"] == "outline"]
        if len(outlines) == 1:
            selected = outlines
    if not selected:
        return None
    if "左下角" in requirement and all(item["kind"] != "outline" for item in selected):
        selected = [item for item in inventory if item["kind"] == "outline"]
    identity = _identity_evidence(requirement, inventory, selected,
                                  source_points, tolerance_mm)
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

    if not identity["authoritative"]:
        # A measurement against an ambiguously bound object is not evidence.
        checks.append(_check(
            "object_identity_binding", False,
            expected="one source-authoritative object set",
            actual=identity,
            detail="对象身份存在歧义，不能作为强制事实证明",
            covers={"object_identity"},
        ))
    else:
        checks.append(_check(
            "object_identity_binding", True,
            expected="one source-authoritative object set",
            actual=identity,
            covers={"object_identity"},
        ))
    checks.extend(_prove_points(requirement, selected, tolerance_mm, source_text))
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
                                 expected=value, actual=radii,
                                 covers={"dimension:radius", "common_radius"}))

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
            nested = _polygon_contains(outer_points, inner_points, tolerance)
        checks.append(_check("ring_topology",
                             len(outlines) == 2
                             and all(item["geometries"][0].get("closed") is True
                                     for item in outlines)
                             and nested,
                             actual={"outline_count": len(outlines),
                                     "nested": nested,
                                     "method": "full_boundary_containment"}))

    # "安装孔/圆管口" must lie inside the named outline.
    if re.search(r"孔|管口", requirement) and "半径" in requirement:
        circles = [item for item in selected if item["kind"] == "circle"]
        outlines = [item for item in inventory if item["kind"] == "outline"]
        if circles and outlines and ("安装孔" in requirement or "管口" in requirement):
            polygon = [tuple(point) for point in outlines[0]["geometries"][0]["points_mm"]]
            points_inside = [
                _circle_inside_polygon(
                    tuple(item["geometries"][0]["center_mm"]),
                    float(item["geometries"][0]["radius_mm"]),
                    polygon,
                    tolerance,
                )
                for item in circles
            ]
            checks.append(_check("holes_inside_outline",
                                 all(points_inside),
                                 actual=points_inside,
                                 detail={"method": "full_circle_boundary"}))

    if "各放一个" in requirement or "各画一个" in requirement:
        circles = [item for item in selected if item["kind"] == "circle"]
        if circles:
            checks.append(_check("one_circle_per_source_point",
                                 len(circles) == len(_points(requirement)),
                                 expected=len(_points(requirement)), actual=len(circles)))

    facts = _mandatory_facts(requirement, clause)
    if "unit" in facts:
        unit_evidence = _unit_conversion_evidence(requirement, selected, tolerance_mm)
        checks.append(_check(
            "source_unit_honoured",
            unit_evidence["verified"],
            expected="source value multiplied by its declared unit factor",
            actual=unit_evidence["conversions"],
            detail=unit_evidence,
            covers={"unit"},
        ))

    if not checks:
        return None
    covered = {fact for check in checks for fact in check.get("covers") or []}
    uncovered = sorted(fact for fact in facts if fact not in covered)
    unmeasured = sorted(fact for fact, value in facts.items()
                        if value.get("status") != "measured")
    checks.append(_check(
        "mandatory_fact_coverage",
        not uncovered and not unmeasured,
        expected=sorted(facts),
        actual={"uncovered": uncovered, "unmeasured": unmeasured,
                "covered": sorted(covered & set(facts))},
        detail={"facts": facts},
        covers=set(),
    ))
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
        # A count is an inventory proof only when every counted member is one
        # unique object with one unique geometry.  A duplicated object or a
        # shared geometry cannot clear an inventory unknown.
        for check in proof["checks"]:
            if check["predicate"] not in {"source_object_count", "circle_count"} \
                    or check["status"] != "verified":
                continue
            object_ids = [item["logical_object_id"] for item in proof["objects"]]
            geometry_ids = [ref for item in proof["objects"]
                            for ref in item["geometry_ids"]]
            unique = (
                bool(object_ids)
                and len(object_ids) == len(set(object_ids)) == check.get("actual")
                and len(geometry_ids) == len(set(geometry_ids)) == check.get("actual")
            )
            if not unique:
                check["status"] = "failed"
                check["detail"] = {
                    "reason": "count_proof_requires_unique_objects_and_geometries",
                    "object_ids": object_ids,
                    "geometry_ids": geometry_ids,
                    "expected": check.get("actual"),
                }
        if any(check["predicate"] in {"source_object_count", "circle_count"}
               and check["status"] != "verified" for check in proof["checks"]):
            proof["status"] = "failed"
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
        if proof["status"] == "verified" and clause.get("binding_failures"):
            # The first pass measured this candidate against the same source
            # fact and found a conflict.  A second, narrower predicate cannot
            # overrule that conflict; record the atomic evidence but keep the
            # clause blocked.
            proof["status"] = "failed"
            proof["first_pass_conflict"] = deepcopy(clause.get("binding_failures"))
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
        if proof["status"] == "failed" and clause.get("status") in {"partial", "unbound"}:
            # Keep the first-pass blocking state; the failed measurement is
            # still recorded in evidence and remains blocking.  "unbound"
            # specifically records that no uniquely typed candidate existed,
            # which is the correct conclusion for a wrong-shape trial.
            clause["status"] = clause.get("status")
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
                    category = (
                        "circle" if "圆" in requirement_text
                        else "arc" if re.search(r"圆弧|弧", requirement_text)
                        else "outline" if re.search(r"轮廓|外形|外框", requirement_text)
                        else None
                    )
                    count_proofs.append({
                        "source_requirement_id": clause.get("requirement_id"),
                        "requirement_id": clause.get("requirement_id"),
                        "category": category,
                        "quantity": check.get("expected"),
                        "actual": check.get("actual"),
                        "object_ids": [item["logical_object_id"] for item in proof["objects"]],
                        "geometry_ids": [ref for item in proof["objects"]
                                         for ref in item["geometry_ids"]],
                        "unique_objects": True,
                        "unique_geometries": True,
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
