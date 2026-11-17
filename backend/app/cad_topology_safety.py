"""Generic composite-path topology safety (B1 line).

Shape-agnostic curve-level contact detection for composite construction
paths.  The module operates on plain segment mappings and contains no
case ids, no shape names and no fixed control-point constants.

Detection model
---------------
Lines and Bezier curves are refined by de Casteljau subdivision with
convex-hull bounding-box exclusion.  Internal nodes are pruned only by
hull separation; the coarse sample distance is *not* used to prune an
internal subtree, because a large sub-curve whose samples miss the
contact can still contain a crossing between samples.  Only at a leaf do
we verify proximity by point-to-segment projection against the leaf
chord.

Arcs and clamped-uniform splines do not have a de Casteljau hull to
subdivide, so they are rasterized into a controlled polyline whose
chord-height residual is bounded explicitly (see :func:`arc_chord_height`,
:func:`arc_chord_count_for_tolerance` and :func:`spline_residual_bound`).
If the required piece count exceeds the hard cap, or the spline residual
cannot be bounded below the tolerance, the segment pair is reported
``unresolved`` rather than assumed clear (fail-closed).

Convergence criteria (explicit)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A Bezier node becomes a leaf when either:

* both portions are spatially small: their control-hull diagonal is at
  most ``leaf_size`` (lines are leaves by construction); or
* the subdivision depth reaches ``SUBDIVISION_MAX_DEPTH``.

Each pair search is bounded by a per-search node budget
``NODE_BUDGET_CAP``.  When the budget is exhausted, or the depth cap is
reached while two hulls still overlap inside the proximity band, the
report flags ``unresolved`` instead of assuming the path is clear.

Only a proven leaf chord straddle, an endpoint match within tolerance,
or a sub-proximity parallel contact produces a definite contact kind.
Every other outcome at truncation is recorded as ``near_contact`` and
flagged unresolved; the search never concludes "definitely clear" or
"definitely intersecting" from a truncated subtree.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

PROXIMITY_TOLERANCE = 1e-6
SUBDIVISION_MAX_DEPTH = 16
LEAF_SAMPLE_COUNT = 5
MIN_PARAM_GAP = 1e-3
LEAF_SIZE_FACTOR = 4.0
LEAF_SIZE_SCALE = 0.0005
PROXIMITY_FACTOR = 2.0
NODE_BUDGET_CAP = 8000
SELF_HALF_DEPTH = 10

ARC_MAX_PIECES = 2048
SPLINE_MIN_PIECES = 8
SPLINE_MAX_PIECES = 512
# Conservative wiggle multiplier on the measured spline chord residual:
# an unsampled portion of the spline can bow away from the sampled chord
# by more than the sampled residual, so the measured bound is inflated
# before it is compared against tolerance.
SPLINE_RESIDUE_FACTOR = 3.0
# Two leaf chords meeting at a contact within this angle are accepted as
# a tangent; a sharper angle at sub-proximity distance is not proven
# tangent (it may be a shallow crossing the leaf missed) and is kept
# unresolved instead of being misclassified.
TANGENT_ANGLE_DEG = 15.0

CONTACT_CROSSING = "crossing"
CONTACT_TANGENT = "tangent"
CONTACT_SELF = "self"
CONTACT_ENDPOINT = "endpoint"
CONTACT_NEAR = "near_contact"


@dataclass(frozen=True)
class Contact:
    """One verified or flagged curve-level contact between two portions."""

    segment_a: int
    segment_b: int
    parameter_a: float
    parameter_b: float
    point_a: tuple[float, float]
    point_b: tuple[float, float]
    distance: float
    kind: str
    interval_a: tuple[float, float] = (0.0, 1.0)
    interval_b: tuple[float, float] = (0.0, 1.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "segment_indices": [self.segment_a, self.segment_b],
            "parameters": [
                round(self.parameter_a, 6),
                round(self.parameter_b, 6),
            ],
            "parameter_intervals": [
                [round(self.interval_a[0], 6), round(self.interval_a[1], 6)],
                [round(self.interval_b[0], 6), round(self.interval_b[1], 6)],
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


@dataclass
class _Piece:
    """One rasterized / subdivided portion of an original segment."""

    kind: str
    points: list[tuple[float, float]]
    t0: float
    t1: float


def _point(value: Any) -> tuple[float, float]:
    if isinstance(value, dict):
        return float(value["x"]), float(value["y"])
    return float(value[0]), float(value[1])


def _parse_segment(segment: Any) -> tuple[str, list[tuple[float, float]], dict[str, Any]]:
    kind = str(segment.get("kind", ""))
    if kind == "line":
        return "line", [_point(segment["start"]), _point(segment["end"])], dict(segment)
    if kind == "bezier":
        return "bezier", [_point(point) for point in segment["control_points"]], dict(segment)
    return kind, [], dict(segment)


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


# ---------------------------------------------------------------------------
# Arc and clamped-uniform spline evaluation (mirrors the construction layer's
# clamped-uniform knot scheme; kept local so this module stays pure geometry).
# ---------------------------------------------------------------------------

def _clamped_uniform_knots(count: int, degree: int) -> list[float]:
    interior_count = count - degree - 1
    knots = [0.0] * (degree + 1)
    if interior_count > 0:
        knots.extend(index / (interior_count + 1) for index in range(1, interior_count + 1))
    knots.extend([1.0] * (degree + 1))
    return knots


def _bspline_point(
    control: list[tuple[float, float]], degree: int, parameter: float
) -> tuple[float, float]:
    count = len(control)
    knots = _clamped_uniform_knots(count, degree)
    if parameter >= 1.0:
        return control[-1]
    span = degree
    for index in range(degree, count):
        if knots[index] <= parameter < knots[index + 1]:
            span = index
            break
    values = [list(control[index]) for index in range(span - degree, span + 1)]
    for level in range(1, degree + 1):
        for index in range(degree, level - 1, -1):
            knot_index = span - degree + index
            denominator = knots[knot_index + degree - level + 1] - knots[knot_index]
            alpha = 0.0 if abs(denominator) < 1e-12 else (
                parameter - knots[knot_index]
            ) / denominator
            values[index][0] = (1.0 - alpha) * values[index - 1][0] + alpha * values[index][0]
            values[index][1] = (1.0 - alpha) * values[index - 1][1] + alpha * values[index][1]
    return values[degree][0], values[degree][1]


def _arc_sweep(segment: dict[str, Any]) -> tuple[float, float]:
    start = float(segment["start_angle"])
    end = float(segment["end_angle"])
    clockwise = bool(segment.get("clockwise", False))
    sweep = ((start - end) % 360.0) if clockwise else ((end - start) % 360.0)
    if math.isclose(sweep, 0.0, abs_tol=1e-12) and not math.isclose(
        end, start, abs_tol=1e-12
    ):
        sweep = 360.0
    direction = -1.0 if clockwise else 1.0
    return sweep, direction


def _arc_points(
    segment: dict[str, Any], count: int
) -> list[tuple[float, float]]:
    center = _point(segment["center"])
    radius = float(segment["radius"])
    start = float(segment["start_angle"])
    sweep, direction = _arc_sweep(segment)
    return [
        (
            center[0] + radius * math.cos(math.radians(start + direction * sweep * k / count)),
            center[1] + radius * math.sin(math.radians(start + direction * sweep * k / count)),
        )
        for k in range(count + 1)
    ]


def _polylines(points: list[tuple[float, float]]) -> list[_Piece]:
    pieces: list[_Piece] = []
    for index in range(len(points) - 1):
        pieces.append(_Piece(
            "line",
            [points[index], points[index + 1]],
            index / (len(points) - 1),
            (index + 1) / (len(points) - 1),
        ))
    return pieces


# ---------------------------------------------------------------------------
# Error bounds
# ---------------------------------------------------------------------------

def arc_chord_height(
    radius: float, total_angle_deg: float, chord_count: int
) -> float:
    """Sagitta (chord-height) bound for ``chord_count`` equal chords.

    For a circular arc of radius ``radius`` swept over ``total_angle_deg``
    degrees, split into ``chord_count`` equal angular steps of
    ``phi = total_angle_deg / chord_count``, the maximum distance between
    the arc and its replacement chord is the sagitta

    ``h = R * (1 - cos(phi / 2))``.

    For small steps ``h ~= R * (phi / 2) ** 2 / 2`` (quadratic in step
    angle).  The inequality ``1 - cos x <= x**2 / 2`` makes the
    quadratic form an upper bound, so :func:`arc_chord_count_for_tolerance`
    solves a conservative count, not an asymptotic one.
    """
    if chord_count <= 0:
        raise ValueError("chord_count must be positive")
    half = math.radians(total_angle_deg) / (2.0 * chord_count)
    return radius * (1.0 - math.cos(half))


def arc_chord_count_for_tolerance(
    radius: float, sweep_deg: float, max_chord_height: float
) -> int:
    """Minimum equal-chord count keeping the sagitta under ``max_chord_height``.

    Solves ``R * (Phi/(2n))**2 / 2 <= h_max`` using the conservative
    inequality ``1 - cos x <= x**2/2``; the returned ``n`` therefore
    satisfies the exact sagitta bound as well.
    """
    if max_chord_height <= 0:
        raise ValueError("max_chord_height must be positive")
    sweep = math.radians(sweep_deg)
    count = sweep / 2.0 * math.sqrt(radius / (2.0 * max_chord_height))
    return max(1, math.ceil(count - 1e-9))


def spline_residual_bound(
    control: list[tuple[float, float]],
    degree: int,
    pieces: int,
) -> float:
    """Conservative chord-height residual bound for a rasterized spline.

    The spline is evaluated on a fine grid (twice the piece count) and the
    maximum distance from those fine samples to the coarse piece chords is
    measured.  That measured residual is inflated by
    :data:`SPLINE_RESIDUE_FACTOR` to cover unsampled bowing between the
    evaluation samples.  The bound is valid for the clamped-uniform knot
    scheme used here; it is not valid for non-uniform knots, open splines
    with unclamped ends, or a control polygon whose unsampled interior
    contains a loop the sample grid misses.
    """
    fine = 2 * pieces
    coarse: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for k in range(pieces):
        coarse.append((
            _bspline_point(control, degree, k / pieces),
            _bspline_point(control, degree, (k + 1) / pieces),
        ))
    worst = 0.0
    for k in range(fine):
        u = k / fine
        piece_index = min(pieces - 1, int(u * pieces))
        p0, p1 = coarse[piece_index]
        distance, _ = _point_segment_distance(
            _bspline_point(control, degree, u), p0, p1)
        worst = max(worst, distance)
    return SPLINE_RESIDUE_FACTOR * worst


def _arc_pieces(
    segment: dict[str, Any], tolerance: float
) -> tuple[list[_Piece], bool]:
    radius = float(segment["radius"])
    sweep, _ = _arc_sweep(segment)
    # The chord target follows the proximity band rather than the raw
    # junction tolerance: a chord deviation below the proximity band cannot
    # hide a contact the leaf-level projection would miss.
    h_max = max(PROXIMITY_FACTOR * tolerance, 1e-12)
    required = arc_chord_count_for_tolerance(radius, sweep, h_max)
    if required > ARC_MAX_PIECES:
        # Bound cannot be established within the piece cap: fail-closed.
        points = _arc_points(segment, ARC_MAX_PIECES)
        return _polylines(points), False
    points = _arc_points(segment, required)
    return _polylines(points), True


def _spline_pieces(
    segment: dict[str, Any], tolerance: float
) -> tuple[list[_Piece], bool]:
    control = [_point(point) for point in segment["control_points"]]
    degree = int(segment.get("degree", 3))
    degree = max(1, min(5, degree))
    h_max = max(tolerance, 1e-12)
    pieces = SPLINE_MIN_PIECES
    while pieces <= SPLINE_MAX_PIECES:
        bound = spline_residual_bound(control, degree, pieces)
        if bound <= h_max:
            sampled = [
                _bspline_point(control, degree, k / pieces)
                for k in range(pieces + 1)
            ]
            return _polylines(sampled), True
        pieces *= 2
    sampled = [
        _bspline_point(control, degree, k / SPLINE_MAX_PIECES)
        for k in range(SPLINE_MAX_PIECES + 1)
    ]
    return _polylines(sampled), False


# ---------------------------------------------------------------------------
# Generic hull / leaf primitives
# ---------------------------------------------------------------------------

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


def _chord_angle_deg(
    a0: tuple[float, float], a1: tuple[float, float],
    b0: tuple[float, float], b1: tuple[float, float],
) -> float:
    da = (a1[0] - a0[0], a1[1] - a0[1])
    db = (b1[0] - b0[0], b1[1] - b0[1])
    la = math.hypot(*da)
    lb = math.hypot(*db)
    if la <= 1e-18 or lb <= 1e-18:
        return 0.0
    cosine = abs(da[0] * db[0] + da[1] * db[1]) / (la * lb)
    cosine = max(-1.0, min(1.0, cosine))
    return math.degrees(math.acos(cosine))


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


def _leaf_chord(
    kind: str,
    points: list[tuple[float, float]],
) -> tuple[tuple[float, float], tuple[float, float]]:
    if kind == "line":
        return points[0], points[-1]
    return _eval_bezier(points, 0.0), _eval_bezier(points, 1.0)


def _leaf_distance(
    kind_a: str,
    points_a: list[tuple[float, float]],
    kind_b: str,
    points_b: list[tuple[float, float]],
) -> tuple[float, tuple[float, float], tuple[float, float]]:
    """Minimum distance between two leaf portions, using chord projection."""
    samples_a = _leaf_sample_points(kind_a, points_a)
    samples_b = _leaf_sample_points(kind_b, points_b)
    chord_b = _leaf_chord(kind_b, points_b)
    chord_a = _leaf_chord(kind_a, points_a)
    best = math.inf
    best_a = samples_a[0]
    best_b = samples_b[0]
    for point_a in samples_a:
        distance, projection = _point_segment_distance(point_a, chord_b[0], chord_b[1])
        if distance < best:
            best, best_a, best_b = distance, point_a, projection
    for point_b in samples_b:
        distance, projection = _point_segment_distance(point_b, chord_a[0], chord_a[1])
        if distance < best:
            best, best_a, best_b = distance, projection, point_b
    return best, best_a, best_b


def _near_endpoint(
    kind: str,
    points: list[tuple[float, float]],
    point: tuple[float, float],
    tolerance: float,
) -> bool:
    if not points:
        return False
    for endpoint in (points[0], points[-1]):
        if math.hypot(point[0] - endpoint[0], point[1] - endpoint[1]) <= tolerance:
            return True
    return False


def _chord_intersection(
    a0: tuple[float, float],
    a1: tuple[float, float],
    b0: tuple[float, float],
    b1: tuple[float, float],
) -> tuple[float, float] | None:
    """Intersection of two leaf chords, or None if they do not straddle."""
    o1 = _orientation(a0, a1, b0)
    o2 = _orientation(a0, a1, b1)
    o3 = _orientation(b0, b1, a0)
    o4 = _orientation(b0, b1, a1)
    if not (o1 * o2 < 0 and o3 * o4 < 0):
        return None
    da = (a1[0] - a0[0], a1[1] - a0[1])
    db = (b1[0] - b0[0], b1[1] - b0[1])
    denom = da[0] * db[1] - da[1] * db[0]
    if abs(denom) <= 1e-18:
        return None
    delta = (b0[0] - a0[0], b0[1] - a0[1])
    t = (delta[0] * db[1] - delta[1] * db[0]) / denom
    return (a0[0] + t * da[0], a0[1] + t * da[1])


def _children(
    kind: str,
    points: list[tuple[float, float]],
    t0: float,
    t1: float,
    depth: int,
    leaf_size: float,
    force: bool = False,
) -> list[tuple[list[tuple[float, float]], float, float, int]]:
    if kind == "line" or (not force and _bbox_diagonal(_bbox(points)) <= leaf_size):
        return [(points, t0, t1, depth)]
    left, right = _split_bezier(points)
    middle = (t0 + t1) * 0.5
    return [
        (left, t0, middle, depth + 1),
        (right, middle, t1, depth + 1),
    ]


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
    verified = False
    node_budget = 0
    tol = max(tolerance, 1e-12)
    proximity = PROXIMITY_FACTOR * tol
    scale = max(
        _bbox_diagonal(_bbox(points_a)),
        _bbox_diagonal(_bbox(points_b)),
        tol,
    )
    leaf_size = max(LEAF_SIZE_FACTOR * tol, LEAF_SIZE_SCALE * scale)
    loose_band = max(8.0 * leaf_size, 16.0 * tol)

    def recurse(
        pa: list[tuple[float, float]], ta0: float, ta1: float, da: int,
        pb: list[tuple[float, float]], tb0: float, tb1: float, db: int,
    ) -> None:
        nonlocal unresolved, verified, node_budget
        node_budget += 1
        if node_budget > NODE_BUDGET_CAP:
            unresolved = True
            return
        if not _bbox_overlap(_bbox(pa), _bbox(pb), tolerance):
            return
        small_a = kind_a == "line" or _bbox_diagonal(_bbox(pa)) <= leaf_size
        small_b = kind_b == "line" or _bbox_diagonal(_bbox(pb)) <= leaf_size
        depth_cap = da >= SUBDIVISION_MAX_DEPTH or db >= SUBDIVISION_MAX_DEPTH
        distance, point_a, point_b = _leaf_distance(kind_a, pa, kind_b, pb)
        mid_a = (ta0 + ta1) * 0.5
        mid_b = (tb0 + tb1) * 0.5
        on_boundary = (
            boundary is not None
            and abs(mid_a - boundary) <= param_gap
            and abs(mid_b - boundary) <= param_gap
        )
        if on_boundary:
            return
        # A spatially small leaf whose residual still sits in the uncertain
        # band is refined further (local subdivision) instead of being
        # called clear; only depth/budget truncation downgrades it to
        # unresolved near-contact.
        near_band = proximity < distance <= loose_band
        can_refine = near_band and (kind_a == "bezier" or kind_b == "bezier")
        if not depth_cap and not ((small_a and small_b) and not can_refine):
            children_a = _children(kind_a, pa, ta0, ta1, da, leaf_size, force=can_refine)
            children_b = _children(kind_b, pb, tb0, tb1, db, leaf_size, force=can_refine)
            for child_a in children_a:
                for child_b in children_b:
                    recurse(*child_a, *child_b)
            return
        chord_a0, chord_a1 = _leaf_chord(kind_a, pa)
        chord_b0, chord_b1 = _leaf_chord(kind_b, pb)
        cross_point = _chord_intersection(chord_a0, chord_a1, chord_b0, chord_b1)
        endpoint = _near_endpoint(kind_a, pa, point_a, tol) and _near_endpoint(
            kind_b, pb, point_b, tol)
        if cross_point is not None:
            resolved_kind = (
                CONTACT_CROSSING if contact_kind != CONTACT_SELF else CONTACT_SELF
            )
            contacts.append(Contact(
                segment_a=index_a,
                segment_b=index_b,
                parameter_a=mid_a,
                parameter_b=mid_b,
                point_a=cross_point,
                point_b=cross_point,
                distance=0.0,
                kind=resolved_kind,
                interval_a=(ta0, ta1),
                interval_b=(tb0, tb1),
            ))
            verified = True
        elif distance <= proximity:
            angle = _chord_angle_deg(chord_a0, chord_a1, chord_b0, chord_b1)
            if endpoint:
                resolved_kind = CONTACT_ENDPOINT
                verified = True
            elif angle <= TANGENT_ANGLE_DEG:
                resolved_kind = contact_kind
                verified = True
            else:
                # Sub-proximity but chords meet at a sharp angle: could be a
                # shallow crossing the leaf missed.  Keep it unresolved rather
                # than mislabelling it a tangent contact.
                contacts.append(Contact(
                    segment_a=index_a,
                    segment_b=index_b,
                    parameter_a=mid_a,
                    parameter_b=mid_b,
                    point_a=point_a,
                    point_b=point_b,
                    distance=distance,
                    kind=CONTACT_NEAR,
                    interval_a=(ta0, ta1),
                    interval_b=(tb0, tb1),
                ))
                unresolved = True
                return
            contacts.append(Contact(
                segment_a=index_a,
                segment_b=index_b,
                parameter_a=mid_a,
                parameter_b=mid_b,
                point_a=point_a,
                point_b=point_b,
                distance=distance,
                kind=resolved_kind,
                interval_a=(ta0, ta1),
                interval_b=(tb0, tb1),
            ))
        elif depth_cap and distance <= loose_band:
            # Depth/budget truncation while still inside the uncertain
            # band: record the geometry for the planner and mark
            # unresolved (fail-closed).  This is never counted as clear.
            contacts.append(Contact(
                segment_a=index_a,
                segment_b=index_b,
                parameter_a=mid_a,
                parameter_b=mid_b,
                point_a=point_a,
                point_b=point_b,
                distance=distance,
                kind=CONTACT_NEAR,
                interval_a=(ta0, ta1),
                interval_b=(tb0, tb1),
            ))
            unresolved = True

    recurse(points_a, ta0, ta1, 0, points_b, tb0, tb1, 0)
    return contacts, unresolved and not verified


def _analyze_pair(
    index_a: int,
    piece_a: _Piece,
    index_b: int,
    piece_b: _Piece,
    tolerance: float,
) -> tuple[list[Contact], bool]:
    return _search_pair(
        index_a, piece_a.kind, piece_a.points, piece_a.t0, piece_a.t1,
        index_b, piece_b.kind, piece_b.points, piece_b.t0, piece_b.t1,
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


def _expand_segment(
    segment: Any, tolerance: float
) -> tuple[list[_Piece], bool]:
    """Split one original segment into searchable pieces.

    Returns the pieces and a flag that is False when the arc/spline chord
    residual could not be bounded within the piece cap (fail-closed).
    """
    kind, points, raw = _parse_segment(segment)
    if kind == "line":
        return [_Piece("line", points, 0.0, 1.0)], True
    if kind == "bezier":
        return [_Piece("bezier", points, 0.0, 1.0)], True
    if kind == "arc":
        return _arc_pieces(raw, tolerance)
    if kind == "spline":
        return _spline_pieces(raw, tolerance)
    # Unknown kind: do not claim it was checked.
    return [], False


def analyze_composite_segments(
    segments: list[Any],
    tolerance: float = PROXIMITY_TOLERANCE,
    closed: bool = False,
) -> TopologyReport:
    """Analyse a composite path's segments for curve-level contacts.

    Parameters
    ----------
    segments:
        Plain segment mappings (line / bezier / arc / spline).  Arc and
        spline portions are rasterized under an explicit chord-height
        bound; a segment that cannot be bounded is flagged unresolved.
    tolerance:
        Junction/proximity tolerance carried from the construction plan.
    closed:
        Whether the path closes back to its first segment.
    """
    expanded = [_expand_segment(segment, tolerance) for segment in segments]
    pieces_per = [pieces for pieces, _ in expanded]
    contacts: list[Contact] = []
    unresolved = any(not bounded for _, bounded in expanded)
    count = len(expanded)

    for index, (kind, points, _) in enumerate(
        _parse_segment(segment) for segment in segments
    ):
        if kind == "bezier" and len(points) >= 3:
            self_contacts, self_unresolved = _analyze_self(
                index, points, tolerance)
            contacts.extend(self_contacts)
            unresolved = unresolved or self_unresolved

    pair_unresolved: dict[tuple[int, int], bool] = {}
    pair_verified: dict[tuple[int, int], bool] = {}
    for index in range(count):
        pieces_a = pieces_per[index]
        bboxes_a = [_bbox(piece.points) for piece in pieces_a]
        for other in range(index + 1, count):
            if _adjacent(index, other, count, closed):
                continue
            pieces_b = pieces_per[other]
            bboxes_b = [_bbox(piece.points) for piece in pieces_b]
            key = (index, other)
            for piece_a, box_a in zip(pieces_a, bboxes_a):
                for piece_b, box_b in zip(pieces_b, bboxes_b):
                    if not _bbox_overlap(box_a, box_b, tolerance):
                        continue
                    pair_contacts, pair_unresolved_flag = _analyze_pair(
                        index, piece_a, other, piece_b, tolerance,
                    )
                    contacts.extend(pair_contacts)
                    pair_unresolved[key] = (
                        pair_unresolved.get(key, False) or pair_unresolved_flag
                    )
                    pair_verified[key] = pair_verified.get(key, False) or any(
                        contact.kind != CONTACT_NEAR for contact in pair_contacts
                    )

    # A pair that produced a definite contact is resolved by that contact;
    # its residual unproven near-contact does not keep the report unresolved.
    unresolved = unresolved or any(
        flag and not pair_verified.get(key, False)
        for key, flag in pair_unresolved.items()
    )
    contacts = _suppress_near_when_verified(contacts)
    return TopologyReport(contacts=_dedupe(contacts), unresolved=unresolved)


def _suppress_near_when_verified(contacts: list[Contact]) -> list[Contact]:
    """Drop unresolved near-contact entries whose segment pair is already
    covered by a definite contact (a dense rasterization can show the same
    crossing in one piece pair and an unproven proximity residual in
    another)."""
    definite: dict[tuple[int, int], bool] = {}
    for contact in contacts:
        key = (min(contact.segment_a, contact.segment_b),
               max(contact.segment_a, contact.segment_b))
        definite[key] = definite.get(key, False) or contact.kind != CONTACT_NEAR
    return [
        contact for contact in contacts
        if contact.kind != CONTACT_NEAR
        or not definite[(min(contact.segment_a, contact.segment_b),
                         max(contact.segment_a, contact.segment_b))]
    ]
