"""Generic composite-path topology safety (B1 line).

Shape-agnostic curve-level contact detection for composite construction
paths.  The module operates on plain segment mappings and contains no
case ids, no shape names and no fixed control-point constants.

Curves are refined by de Casteljau subdivision with convex-hull bounding
box exclusion; only overlapping hull pairs are refined locally, and leaf
proximity is verified by direct sampling.  Line and Bezier
(quadratic/cubic) segments are analysed at curve level; other segment
kinds are left to the caller's flattened-polyline checks.

The detector is fail-closed: when the subdivision budget is exhausted
while two curve hulls still overlap, the report flags ``unresolved``
instead of assuming the path is clear.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

PROXIMITY_TOLERANCE = 1e-6
SUBDIVISION_MAX_DEPTH = 14
LEAF_SAMPLE_COUNT = 5
MIN_PARAM_GAP = 1e-3
LEAF_SIZE_FACTOR = 4.0
PROXIMITY_FACTOR = 2.0

CONTACT_CROSSING = "crossing"
CONTACT_TANGENT = "tangent"
CONTACT_SELF = "self"


@dataclass(frozen=True)
class Contact:
    """One verified curve-level contact between two path portions."""

    segment_a: int
    segment_b: int
    parameter_a: float
    parameter_b: float
    point_a: tuple[float, float]
    point_b: tuple[float, float]
    distance: float
    kind: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "segment_indices": [self.segment_a, self.segment_b],
            "parameters": [
                round(self.parameter_a, 6),
                round(self.parameter_b, 6),
            ],
            "points": [
                {"x": round(self.point_a[0], 9), "y": round(self.point_a[1], 9)},
                {"x": round(self.point_b[0], 9), "y": round(self.point_b[1], 9)},
            ],
            "distance": round(self.distance, 12),
            "kind": self.kind,
        }


@dataclass
class TopologyReport:
    contacts: list[Contact] = field(default_factory=list)
    unresolved: bool = False


def _point(value: Any) -> tuple[float, float]:
    if isinstance(value, dict):
        return float(value["x"]), float(value["y"])
    return float(value[0]), float(value[1])


def _parse_segment(segment: Any) -> tuple[str, list[tuple[float, float]]]:
    kind = str(segment.get("kind", ""))
    if kind == "line":
        return "line", [_point(segment["start"]), _point(segment["end"])]
    if kind == "bezier":
        return "bezier", [_point(point) for point in segment["control_points"]]
    return kind, []


def _eval_bezier(points: list[tuple[float, float]], t: float) -> tuple[float, float]:
    values = list(points)
    while len(values) > 1:
        values = [
            (left[0] + (right[0] - left[0]) * t,
             left[1] + (right[1] - left[1]) * t)
            for left, right in zip(values, values[1:])
        ]
    return values[0]


def _split_bezier(points: list[tuple[float, float]]) -> tuple[
    list[tuple[float, float]], list[tuple[float, float]]
]:
    left: list[tuple[float, float]] = []
    right: list[tuple[float, float]] = []
    chain = list(points)
    left.append(chain[0])
    right.append(chain[-1])
    while len(chain) > 1:
        chain = [
            ((l[0] + r[0]) * 0.5, (l[1] + r[1]) * 0.5)
            for l, r in zip(chain, chain[1:])
        ]
        left.append(chain[0])
        right.append(chain[-1])
    return left, list(reversed(right))


def _bbox(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    tolerance: float,
) -> bool:
    return not (
        first[2] + tolerance < second[0]
        or second[2] + tolerance < first[0]
        or first[3] + tolerance < second[1]
        or second[3] + tolerance < first[1]
    )


def _bbox_diagonal(box: tuple[float, float, float, float]) -> float:
    return math.hypot(box[2] - box[0], box[3] - box[1])


def _orientation(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _leaf_sample_points(
    kind: str,
    points: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    if kind == "line":
        middle = (
            (points[0][0] + points[-1][0]) * 0.5,
            (points[0][1] + points[-1][1]) * 0.5,
        )
        return [points[0], middle, points[-1]]
    return [
        _eval_bezier(points, index / (LEAF_SAMPLE_COUNT - 1))
        for index in range(LEAF_SAMPLE_COUNT)
    ]


def _point_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[float, tuple[float, float]]:
    ab = (end[0] - start[0], end[1] - start[1])
    denom = ab[0] ** 2 + ab[1] ** 2
    if denom <= 1e-18:
        return math.hypot(point[0] - start[0], point[1] - start[1]), start
    ratio = ((point[0] - start[0]) * ab[0] + (point[1] - start[1]) * ab[1]) / denom
    ratio = max(0.0, min(1.0, ratio))
    projection = (start[0] + ratio * ab[0], start[1] + ratio * ab[1])
    return math.hypot(point[0] - projection[0], point[1] - projection[1]), projection


def _min_distance(
    first: list[tuple[float, float]],
    second: list[tuple[float, float]],
    second_is_line: bool = False,
) -> tuple[float, tuple[float, float], tuple[float, float]]:
    best = math.inf
    best_a = first[0]
    best_b = second[0]
    if second_is_line:
        line_a, line_b = second[0], second[-1]
        for point_a in first:
            distance, projection = _point_segment_distance(point_a, line_a, line_b)
            if distance < best:
                best, best_a, best_b = distance, point_a, projection
        return best, best_a, best_b
    for point_a in first:
        for point_b in second:
            distance = math.hypot(point_a[0] - point_b[0], point_a[1] - point_b[1])
            if distance < best:
                best, best_a, best_b = distance, point_a, point_b
    return best, best_a, best_b


def _leaf_chord(
    kind: str,
    points: list[tuple[float, float]],
) -> tuple[tuple[float, float], tuple[float, float]]:
    if kind == "line":
        return points[0], points[-1]
    return _eval_bezier(points, 0.0), _eval_bezier(points, 1.0)


def _classify_crossing(
    kind_a: str,
    points_a: list[tuple[float, float]],
    kind_b: str,
    points_b: list[tuple[float, float]],
) -> bool:
    a0, a1 = _leaf_chord(kind_a, points_a)
    b0, b1 = _leaf_chord(kind_b, points_b)
    o1 = _orientation(a0, a1, b0)
    o2 = _orientation(a0, a1, b1)
    o3 = _orientation(b0, b1, a0)
    o4 = _orientation(b0, b1, a1)
    return o1 * o2 < 0 and o3 * o4 < 0


def _children(
    kind: str,
    points: list[tuple[float, float]],
    t0: float,
    t1: float,
    depth: int,
    leaf_size: float,
) -> list[tuple[list[tuple[float, float]], float, float, int]]:
    if kind == "line" or _bbox_diagonal(_bbox(points)) <= leaf_size:
        return [(points, t0, t1, depth)]
    left, right = _split_bezier(points)
    middle = (t0 + t1) * 0.5
    return [
        (left, t0, middle, depth + 1),
        (right, middle, t1, depth + 1),
    ]


NODE_BUDGET_CAP = 4000
SELF_HALF_DEPTH = 10


def _search_pair(
    index_a: int,
    kind_a: str,
    points_a: list[tuple[float, float]],
    ta0: float,
    ta1: float,
    index_b: int,
    kind_b: str,
    points_b: list[tuple[float, float]],
    tb0: float,
    tb1: float,
    tolerance: float,
    contact_kind: str,
    boundary: float | None = None,
    param_gap: float = 0.0,
) -> tuple[list[Contact], bool]:
    contacts: list[Contact] = []
    unresolved = False
    tol = max(tolerance, 1e-12)
    proximity = PROXIMITY_FACTOR * tol
    scale = max(
        _bbox_diagonal(_bbox(points_a)),
        _bbox_diagonal(_bbox(points_b)),
        tol,
    )
    leaf_size = max(LEAF_SIZE_FACTOR * tol, 0.002 * scale)
    loose_band = max(8.0 * leaf_size, 16.0 * tol)
    node_budget = 0

    def node_distance(
        pa: list[tuple[float, float]], pb: list[tuple[float, float]]
    ) -> tuple[float, tuple[float, float], tuple[float, float]]:
        samples_a = _leaf_sample_points(kind_a, pa)
        samples_b = _leaf_sample_points(kind_b, pb)
        if kind_b == "line":
            return _min_distance(samples_a, samples_b, second_is_line=True)
        if kind_a == "line":
            distance, point_b, point_a = _min_distance(
                samples_b, samples_a, second_is_line=True)
            return distance, point_a, point_b
        return _min_distance(samples_a, samples_b)

    def recurse(
        pa: list[tuple[float, float]], ta0: float, ta1: float, da: int,
        pb: list[tuple[float, float]], tb0: float, tb1: float, db: int,
    ) -> None:
        nonlocal unresolved, node_budget
        node_budget += 1
        if node_budget > NODE_BUDGET_CAP:
            unresolved = True
            return
        if not _bbox_overlap(_bbox(pa), _bbox(pb), tolerance):
            return
        distance, point_a, point_b = node_distance(pa, pb)
        if distance > loose_band:
            return
        small_a = kind_a == "line" or _bbox_diagonal(_bbox(pa)) <= leaf_size
        small_b = kind_b == "line" or _bbox_diagonal(_bbox(pb)) <= leaf_size
        depth_cap = da >= SUBDIVISION_MAX_DEPTH or db >= SUBDIVISION_MAX_DEPTH
        if (small_a and small_b) or depth_cap:
            mid_a = (ta0 + ta1) * 0.5
            mid_b = (tb0 + tb1) * 0.5
            on_boundary = (
                boundary is not None
                and abs(mid_a - boundary) <= param_gap
                and abs(mid_b - boundary) <= param_gap
            )
            if distance <= proximity and not on_boundary:
                crossing = contact_kind != CONTACT_SELF and _classify_crossing(
                    kind_a, pa, kind_b, pb)
                contacts.append(Contact(
                    segment_a=index_a,
                    segment_b=index_b,
                    parameter_a=mid_a,
                    parameter_b=mid_b,
                    point_a=point_a,
                    point_b=point_b,
                    distance=distance,
                    kind=CONTACT_CROSSING if crossing else contact_kind,
                ))
            elif depth_cap:
                unresolved = True
            return

        children_a = _children(kind_a, pa, ta0, ta1, da, leaf_size)
        children_b = _children(kind_b, pb, tb0, tb1, db, leaf_size)
        for child_a in children_a:
            for child_b in children_b:
                recurse(*child_a, *child_b)

    recurse(points_a, ta0, ta1, 0, points_b, tb0, tb1, 0)
    return contacts, unresolved


def _analyze_pair(
    index_a: int,
    kind_a: str,
    points_a: list[tuple[float, float]],
    index_b: int,
    kind_b: str,
    points_b: list[tuple[float, float]],
    tolerance: float,
) -> tuple[list[Contact], bool]:
    return _search_pair(
        index_a, kind_a, points_a, 0.0, 1.0,
        index_b, kind_b, points_b, 0.0, 1.0,
        tolerance, CONTACT_TANGENT,
    )


def _analyze_self(
    index: int,
    points: list[tuple[float, float]],
    tolerance: float,
) -> tuple[list[Contact], bool]:
    contacts: list[Contact] = []
    unresolved = False

    def halve(
        current: list[tuple[float, float]], t0: float, t1: float, depth: int
    ) -> None:
        nonlocal unresolved
        if depth >= SELF_HALF_DEPTH:
            return
        left, right = _split_bezier(current)
        middle = (t0 + t1) * 0.5
        pair_contacts, pair_unresolved = _search_pair(
            index, "bezier", left, t0, middle,
            index, "bezier", right, middle, t1,
            tolerance, CONTACT_SELF, boundary=middle,
            param_gap=MIN_PARAM_GAP,
        )
        contacts.extend(pair_contacts)
        unresolved = unresolved or pair_unresolved
        halve(left, t0, middle, depth + 1)
        halve(right, middle, t1, depth + 1)

    halve(points, 0.0, 1.0, 0)
    return contacts, unresolved


def _adjacent(index_a: int, index_b: int, count: int, closed: bool) -> bool:
    if index_b == index_a + 1:
        return True
    return closed and index_a == 0 and index_b == count - 1


def _dedupe(contacts: Iterable[Contact]) -> list[Contact]:
    best: dict[tuple[int, int], Contact] = {}
    for contact in contacts:
        key = (min(contact.segment_a, contact.segment_b),
               max(contact.segment_a, contact.segment_b))
        current = best.get(key)
        if current is None or contact.distance < current.distance:
            best[key] = contact
    return list(best.values())


def analyze_composite_segments(
    segments: list[Any],
    tolerance: float = PROXIMITY_TOLERANCE,
    closed: bool = False,
) -> TopologyReport:
    """Analyse a composite path's segments for curve-level contacts.

    Parameters
    ----------
    segments:
        Plain segment mappings (line / bezier).  Arc and spline segments
        are ignored here and remain covered by the flattened-polyline
        checks in the construction layer.
    tolerance:
        Junction/proximity tolerance carried from the construction plan.
    closed:
        Whether the path closes back to its first segment.
    """
    parsed = [_parse_segment(segment) for segment in segments]
    contacts: list[Contact] = []
    unresolved = False
    count = len(parsed)

    for index, (kind, points) in enumerate(parsed):
        if kind == "bezier" and len(points) >= 3:
            self_contacts, self_unresolved = _analyze_self(index, points, tolerance)
            contacts.extend(self_contacts)
            unresolved = unresolved or self_unresolved
        for other in range(index + 1, count):
            if _adjacent(index, other, count, closed):
                continue
            other_kind, other_points = parsed[other]
            if kind not in {"line", "bezier"} or other_kind not in {"line", "bezier"}:
                continue
            pair_contacts, pair_unresolved = _analyze_pair(
                index, kind, points, other, other_kind, other_points, tolerance,
            )
            contacts.extend(pair_contacts)
            unresolved = unresolved or pair_unresolved

    return TopologyReport(contacts=_dedupe(contacts), unresolved=unresolved)
