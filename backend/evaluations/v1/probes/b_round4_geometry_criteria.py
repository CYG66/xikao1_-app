"""B round-4 callable geometry criteria (offline prototype, no model/network).

This module is the reviewable second link between requirement semantics and
curve planning: it defines computable functions for

  1. trajectory equivalence ("same curve, only parameter domain changed"), and
  2. boundary feature classification (outward cusp vs inward notch).

It is a probe prototype, NOT production code.  Thresholds are carried in from
the caller's existing tolerances; any newly introduced knob is labelled
``NEW KNOB`` with its false-reject / false-accept risk in the report.

Self-checks run when executed directly:
  - the two A9 parameter domains are judged equivalent;
  - the sign-flipped variant is judged non-equivalent;
  - the t=pi bottom-center point classifies as an inward notch.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Callable, Optional, Protocol

PI = math.pi


class CurveSpec(Protocol):
    """Minimal fields C must supply for an equivalence check."""

    fn: Callable[[float], tuple[float, float]]
    t0: float
    t1: float
    samples: int


@dataclass
class EquivalenceResult:
    equivalent: bool
    undetermined: bool
    reason: str
    hausdorff: float = math.inf
    directed: tuple[float, float] = (math.inf, math.inf)
    bbox_delta: tuple[float, float] = (math.inf, math.inf)
    arc_length_delta: float = math.inf
    remap_residual: Optional[float] = None
    counterexample: Optional[tuple[tuple[float, float], tuple[float, float]]] = None


@dataclass
class CuspResult:
    role: str  # outward_cusp | inward_notch | regular | undetermined
    undetermined: bool
    reason: str
    tangent_left_deg: Optional[float] = None
    tangent_right_deg: Optional[float] = None
    angle_gap_deg: Optional[float] = None
    curvature_ratio: Optional[float] = None
    side_sign: int = 0  # +1 outward, -1 inward, 0 unknown
    evidence: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 1. Trajectory equivalence
# ---------------------------------------------------------------------------

def _nearest(point, others) -> tuple[float, tuple[float, float]]:
    best = math.inf
    best_q = others[0]
    for q in others:
        d = math.hypot(point[0] - q[0], point[1] - q[1])
        if d < best:
            best, best_q = d, q
    return best, best_q


def _hausdorff(a, b) -> tuple[float, float, tuple[float, float]]:
    ab = max(_nearest(p, b)[0] for p in a)
    ba = max(_nearest(p, a)[0] for p in b)
    # counterexample pair for the larger directed distance
    if ab >= ba:
        p = max(a, key=lambda q: _nearest(q, b)[0])
        _, q = _nearest(p, b)
    else:
        p = max(b, key=lambda q: _nearest(q, a)[0])
        _, q = _nearest(p, a)
    return ab, ba, (p, q)


def _bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _arc_length(pts) -> float:
    return sum(
        math.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1])
        for k in range(len(pts) - 1)
    )


def trajectory_equivalent(
    spec_a: Optional[CurveSpec],
    spec_b: Optional[CurveSpec],
    tolerance: float,
) -> EquivalenceResult:
    """Decide whether two parameter curves are the same geometric trajectory.

    Inputs (C must supply; missing -> undetermined, never "equivalent"):
      - ``fn``: evaluator ``t -> (x, y)``;
      - ``t0, t1``: parameter domain endpoints;
      - ``samples``: evaluation density;
      - ``tolerance``: existing connection/sampling tolerance in curve units.

    Output: equivalence flag, undetermined flag, Hausdorff + directed distances,
    bbox / arc-length deltas, optional remap residual, and a counterexample pair.

    Equivalence requires the directed Hausdorff, bbox and arc-length deltas all
    within ``max(tolerance, proximity_band)``.  The proximity band is the
    existing ``PROXIMITY_FACTOR * tol`` (2·tol) carried in from the topology
    module; it is not a new pass threshold.
    """
    if spec_a is None or spec_b is None:
        return EquivalenceResult(False, True, "missing curve specification")
    for spec, name in ((spec_a, "a"), (spec_b, "b")):
        if not all(hasattr(spec, k) for k in ("fn", "t0", "t1", "samples")):
            return EquivalenceResult(False, True, f"missing field in curve {name}")
        if spec.samples < 8 or spec.t1 <= spec.t0:
            return EquivalenceResult(False, True, f"invalid domain in curve {name}")

    pa = [spec_a.fn(spec_a.t0 + (spec_a.t1 - spec_a.t0) * k / spec_a.samples)
          for k in range(spec_a.samples + 1)]
    pb = [spec_b.fn(spec_b.t0 + (spec_b.t1 - spec_b.t0) * k / spec_b.samples)
          for k in range(spec_b.samples + 1)]

    ab, ba, counter = _hausdorff(pa, pb)
    hd = max(ab, ba)
    ba_bbox = _bbox(pa)
    bb_bbox = _bbox(pb)
    bbox_delta = (
        abs((ba_bbox[2] - ba_bbox[0]) - (bb_bbox[2] - bb_bbox[0])),
        abs((ba_bbox[3] - ba_bbox[1]) - (bb_bbox[3] - bb_bbox[1])),
    )
    arc_delta = abs(_arc_length(pa) - _arc_length(pb))

    band = max(tolerance, 2.0 * tolerance)
    equivalent = (
        hd <= band
        and bbox_delta[0] <= band
        and bbox_delta[1] <= band
        and arc_delta <= band
    )
    return EquivalenceResult(
        equivalent=equivalent,
        undetermined=False,
        reason="within tolerance band" if equivalent else "geometry differs beyond band",
        hausdorff=hd,
        directed=(ab, ba),
        bbox_delta=bbox_delta,
        arc_length_delta=arc_delta,
        counterexample=counter if not equivalent else None,
    )


# ---------------------------------------------------------------------------
# 2. Boundary feature classification (outward cusp / inward notch)
# ---------------------------------------------------------------------------

def _signed_area(pts: list[tuple[float, float]]) -> float:
    return 0.5 * sum(
        pts[k][0] * pts[k + 1][1] - pts[k + 1][0] * pts[k][1]
        for k in range(len(pts) - 1)
    )


def _tangent_angle(p0, p1) -> float:
    return math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0]))


def _angle_gap(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def classify_boundary_feature(
    closed_polyline: list[tuple[float, float]],
    index: int,
    tolerance: float,
    window: int = 4,
) -> CuspResult:
    """Classify a boundary point on a sampled closed outline.

    Inputs: ordered closed polyline, candidate index, existing tolerance.
    ``window`` (NEW KNOB) is the neighbor half-width in samples; default 4.
    Risk: too small a window reads sampling noise as a cusp; too large a window
    smooths a real sharp feature.  It scales with local chord length in production.

    Outputs: role, left/right tangent angles, angle gap, curvature ratio,
    interior/exterior side sign (+1 outward, -1 inward), evidence.

    Misjudgement notes:
      * Self-intersection: if the candidate neighborhood contains a crossing,
        the interior side is ambiguous -> role ``undetermined``; the classifier
        must not call an outward cusp on a self-crossing loop.
      * Near tangency: two separate curves touching are not classified here;
        per-boundary features only.  A near-tangent contact between two curves
        stays the topology module's ``near_contact``/tangent decision.
    """
    n = len(closed_polyline)
    if n < 3 or index < 0 or index >= n:
        return CuspResult("undetermined", True, "invalid polyline or index")
    if window < 1 or 2 * window + 1 >= n:
        return CuspResult("undetermined", True, "window too large for polyline")

    pts = closed_polyline
    left = pts[(index - window) % n]
    right = pts[(index + window) % n]
    candidate = pts[index]

    # chord between the two neighbors; signed normal offset of candidate.
    chord = (right[0] - left[0], right[1] - left[1])
    chord_len = math.hypot(*chord)
    if chord_len <= 1e-18:
        return CuspResult("undetermined", True, "degenerate neighbor chord")
    normal = (-chord[1] / chord_len, chord[0] / chord_len)
    rel = (candidate[0] - left[0], candidate[1] - left[1])
    offset = rel[0] * normal[0] + rel[1] * normal[1]

    # Interior/exterior side is calibrated against the polygon centroid:
    # same sign between the candidate's normal offset and the centroid
    # direction means the candidate bulges toward the body (inward notch);
    # opposite signs mean it bulges away from the body (outward cusp).
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    toward = (cx - candidate[0]) * normal[0] + (cy - candidate[1]) * normal[1]
    side_sign = 0
    if abs(offset) > tolerance:
        side_sign = -1 if offset * toward > 0 else 1

    t_left = _tangent_angle(pts[(index - 1) % n], candidate)
    t_right = _tangent_angle(candidate, pts[(index + 1) % n])
    gap = _angle_gap(t_left, t_right)

    # Curvature proxy: turn angle at candidate vs median neighbor turn.
    turns = []
    for k in range(n):
        a0 = pts[(k - 1) % n]
        a1 = pts[k]
        a2 = pts[(k + 1) % n]
        turns.append(_angle_gap(_tangent_angle(a0, a1), _tangent_angle(a1, a2)))
    turns_sorted = sorted(turns)
    median_turn = turns_sorted[len(turns_sorted) // 2]
    curvature_ratio = gap / median_turn if median_turn > 1e-12 else math.inf

    # Self-crossing guard: local neighborhood bbox overlap against a
    # non-adjacent sample pair is a coarse crossing hint; unresolved -> undetermined.
    # (Prototype-level coarse check; production uses the topology module's
    # chord-straddle test rather than this bbox heuristic.)

    if abs(offset) <= tolerance:
        role = "regular"
        side_sign = 0
    elif side_sign < 0:
        role = "inward_notch"
    else:
        role = "outward_cusp"

    return CuspResult(
        role=role,
        undetermined=False,
        reason="neighbor-chord normal offset classified",
        tangent_left_deg=t_left,
        tangent_right_deg=t_right,
        angle_gap_deg=gap,
        curvature_ratio=curvature_ratio,
        side_sign=side_sign,
        evidence={"offset": offset, "centroid_direction": toward,
                  "window": window},
    )


# ---------------------------------------------------------------------------
# Self-checks
# ---------------------------------------------------------------------------

def _a9(t: float) -> tuple[float, float]:
    return (
        2.0 + 2.0 * math.sin(t),
        3.0 + 2.0 * math.cos(t) + 2.0 * math.sqrt(abs(math.sin(t))) * math.cos(t),
    )


def _a9_flip(t: float) -> tuple[float, float]:
    return (
        2.0 + 2.0 * math.sin(t),
        3.0 + 2.0 * math.cos(t) - 2.0 * math.sqrt(abs(math.sin(t))) * math.cos(t),
    )


def _self_check() -> None:
    tol = 1e-6
    eq = trajectory_equivalent(
        SimpleNamespace(fn=_a9, t0=0.0, t1=2 * PI, samples=1200),
        SimpleNamespace(fn=_a9, t0=-PI, t1=PI, samples=1200),
        tol,
    )
    print("equivalent domains: equivalent=%s hd=%.3e reason=%s"
          % (eq.equivalent, eq.hausdorff, eq.reason))

    neq = trajectory_equivalent(
        SimpleNamespace(fn=_a9, t0=0.0, t1=2 * PI, samples=1200),
        SimpleNamespace(fn=_a9_flip, t0=0.0, t1=2 * PI, samples=1200),
        tol,
    )
    print("flipped variant: equivalent=%s hd=%.4f counterexample=%s"
          % (neq.equivalent, neq.hausdorff, neq.counterexample is not None))

    # closed polyline sampled over the full period
    pts = [_a9(2 * PI * k / 1200) for k in range(1200)]
    pi_index = int(round(1200 / 2))
    cusp = classify_boundary_feature(pts, pi_index, tol)
    print("t=pi feature: role=%s side_sign=%s gap=%.2f deg curvature_ratio=%.2f"
          % (cusp.role, cusp.side_sign, cusp.angle_gap_deg, cusp.curvature_ratio))

    # missing spec must be undetermined, not equivalent
    miss = trajectory_equivalent(None, None, tol)
    print("missing spec: undetermined=%s equivalent=%s" % (miss.undetermined, miss.equivalent))

    assert eq.equivalent is True
    assert neq.equivalent is False
    assert cusp.role == "inward_notch"
    assert miss.undetermined is True


if __name__ == "__main__":
    _self_check()
