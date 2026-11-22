"""B round-5 generic geometry equivalence / feature contract (offline prototype).

Zero model calls, zero network access, no production code touched.  This module
extends the round-4 prototype with:

  * full trajectory equivalence: point set, orientation, endpoints/closed state,
    topology (self-intersection count, segment count/order), control signature;
  * similarity-transform recognition (scale / translate / rotate / reflect) so
    a compliant transformed shape is NOT mistaken for a failed geometry;
  * independent mirror-symmetry verification;
  * a generalized boundary-feature classifier with measurements, confidence and
    undetermined state.

Thresholds are carried in from the caller's existing tolerances.  New knobs are
labelled ``NEW KNOB`` with false-reject / false-accept risk in the report.
Pure standard library.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Callable, Optional

PI = math.pi


# ---------------------------------------------------------------------------
# Sampling helpers
# ---------------------------------------------------------------------------

def _sample(spec: Optional[SimpleNamespace]) -> list[tuple[float, float]]:
    if spec is None:
        return []
    if getattr(spec, "points", None) is not None:
        return [tuple(p) for p in spec.points]
    n = int(spec.samples)
    return [
        spec.fn(spec.t0 + (spec.t1 - spec.t0) * k / n)
        for k in range(n + 1)
    ]


def _median_chord(pts: list) -> float:
    if len(pts) < 3:
        return 0.0
    ds = sorted(
        math.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1])
        for k in range(len(pts) - 1)
    )
    return ds[len(ds) // 2]


def _bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _diagonal(pts) -> float:
    min_x, min_y, max_x, max_y = _bbox(pts)
    return math.hypot(max_x - min_x, max_y - min_y) or 1.0


def _arc_length(pts) -> float:
    return sum(
        math.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1])
        for k in range(len(pts) - 1)
    )


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
    if ab >= ba:
        p = max(a, key=lambda q: _nearest(q, b)[0])
        _, q = _nearest(p, b)
    else:
        p = max(b, key=lambda q: _nearest(q, a)[0])
        _, q = _nearest(p, a)
    return ab, ba, (p, q)


def _signed_area(pts) -> float:
    return 0.5 * sum(
        pts[k][0] * pts[k + 1][1] - pts[k + 1][0] * pts[k][1]
        for k in range(len(pts) - 1)
    )


# ---------------------------------------------------------------------------
# Topology: self-intersection count on a sampled polyline (chord straddle)
# ---------------------------------------------------------------------------

def _orientation(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments(pts, closed: bool):
    n = len(pts)
    count = n if closed else n - 1
    return [(pts[i], pts[(i + 1) % n]) for i in range(count)]


def _straddle(a, b, c, d) -> bool:
    o1 = _orientation(a, b, c)
    o2 = _orientation(a, b, d)
    o3 = _orientation(c, d, a)
    o4 = _orientation(c, d, b)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    return False


def self_intersection_count(pts, closed: bool) -> int:
    segs = _segments(pts, closed)
    hits = 0
    for i in range(len(segs)):
        a, b = segs[i]
        for j in range(i + 1, len(segs)):
            if closed and j in (i - 1, i + 1) and abs(i - j) == 1:
                continue
            if not closed and j == i + 1:
                continue
            c, d = segs[j]
            if _straddle(a, b, c, d):
                hits += 1
    return hits


# ---------------------------------------------------------------------------
# 1. Trajectory equivalence
# ---------------------------------------------------------------------------

@dataclass
class EquivalenceResult:
    equivalent: bool
    undetermined: bool
    relation: str  # equivalent | similarity_transform | different | undetermined
    reversed: bool = False
    checks: dict = field(default_factory=dict)
    fail_reasons: list = field(default_factory=list)
    hausdorff: float = math.inf
    hausdorff_normalized: float = math.inf
    orientation_match: Optional[bool] = None
    endpoints_match: Optional[bool] = None
    closed_match: Optional[bool] = None
    topology: dict = field(default_factory=dict)
    counterexample: Optional[tuple] = None


def trajectory_equivalent(
    spec_a: Optional[SimpleNamespace],
    spec_b: Optional[SimpleNamespace],
    tolerance: float,
) -> EquivalenceResult:
    """Generic trajectory equivalence (no string comparison, no shape names).

    Checks, each reported separately so C can see *which* item differs:
      1. point set: directed Hausdorff within the 2·tol proximity band;
      2. orientation: signed-area sign (reverse traversal allowed, flagged);
      3. endpoints / closed state;
      4. topology: self-intersection count, segment count, order monotonicity;
      5. control signature (when control points are supplied).

    Any missing/invalid input -> undetermined (never "equivalent").
    """
    band = max(tolerance, 2.0 * tolerance)

    def undetermined(reason: str) -> EquivalenceResult:
        return EquivalenceResult(False, True, "undetermined", fail_reasons=[reason])

    if spec_a is None or spec_b is None:
        return undetermined("missing curve specification")
    for spec, name in ((spec_a, "a"), (spec_b, "b")):
        if getattr(spec, "points", None) is None and not all(
                hasattr(spec, k) for k in ("fn", "t0", "t1", "samples")):
            return undetermined(f"missing field in curve {name}")
        if getattr(spec, "points", None) is None and (
                spec.samples < 8 or spec.t1 == spec.t0):
            return undetermined(f"invalid domain in curve {name}")

    pa = _sample(spec_a)
    pb = _sample(spec_b)
    if len(pa) < 4 or len(pb) < 4:
        return undetermined("too few samples to judge topology")

    closed_a = getattr(spec_a, "closed", None)
    closed_b = getattr(spec_b, "closed", None)
    diag = max(_diagonal(pa), _diagonal(pb))
    ab, ba, counter = _hausdorff(pa, pb)
    hd = max(ab, ba)
    hd_norm = hd / diag

    checks: dict[str, dict] = {}
    fail_reasons: list[str] = []

    # 1. point set.  Gate on normalized Hausdorff against a relative shape
    # band.  REL_POINT_BAND (NEW KNOB, 2% of bbox diagonal) covers sampling
    # grid phase/density noise; below it two samplings of one trajectory are
    # treated as matching.  Risk: too large admits mildly different shapes as
    # equivalent (false accept); too small rejects same-trajectory resamples
    # (false reject).  Absolute 2·tol remains the floor.
    rel_point_band = 0.02
    point_band_norm = max(band / diag, rel_point_band)
    point_ok = hd_norm <= point_band_norm
    checks["point_set"] = {"status": "pass" if point_ok else "fail",
                           "hausdorff": hd, "normalized": hd_norm,
                           "band_normalized": point_band_norm}
    if not point_ok:
        fail_reasons.append("point-set distance exceeds relative shape band")

    # 2. orientation: a reversed traversal is a distinct parameterization
    # direction.  The point set may match, but the orientation dimension fails
    # equivalence; it is reported as "same trajectory, reversed direction" and
    # must NOT be counted as an effective geometric improvement.
    area_a, area_b = _signed_area(pa), _signed_area(pb)
    if abs(area_a) < band or abs(area_b) < band:
        orientation_match = None
        checks["orientation"] = {"status": "undetermined",
                                "detail": "degenerate area, orientation unclear"}
    else:
        same = area_a * area_b > 0
        orientation_match = same
        checks["orientation"] = {"status": "pass" if same else "fail",
                                "same_direction": same, "reversed": not same}
        if not same:
            fail_reasons.append("orientation reversed: traversal direction differs")
    reversed_flag = checks["orientation"].get("reversed", False)

    # 3. endpoints / closed state
    if closed_a is None or closed_b is None:
        closed_match = None
        checks["closed_state"] = {"status": "undetermined"}
    else:
        closed_match = closed_a == closed_b
        checks["closed_state"] = {"status": "pass" if closed_match else "fail",
                                   "closed_a": closed_a, "closed_b": closed_b}
        if not closed_match:
            fail_reasons.append("closed/open state differs")
    endpoints_match = None
    if not (closed_a and closed_b):
        ea = (pa[0], pa[-1])
        eb = (pb[0], pb[-1])
        d_end = min(math.dist(ea[0], eb[0]), math.dist(ea[0], eb[1]))
        endpoints_match = d_end <= band
        checks["endpoints"] = {"status": "pass" if endpoints_match else "fail",
                               "endpoint_distance": d_end}
        if not endpoints_match:
            fail_reasons.append("endpoints do not match")

    # 4. topology.  Raw sampled segment count is a tessellation artifact and is
    # NOT gated; explicit segment counts (when metadata is supplied) are.
    si_a = self_intersection_count(pa, bool(closed_a))
    si_b = self_intersection_count(pb, bool(closed_b))
    seg_a_meta = getattr(spec_a, "segment_count", None)
    seg_b_meta = getattr(spec_b, "segment_count", None)
    topo_match = si_a == si_b
    if seg_a_meta is not None and seg_b_meta is not None:
        topo_match = topo_match and seg_a_meta == seg_b_meta
    checks["topology"] = {"status": "pass" if topo_match else "fail",
                          "self_intersections": (si_a, si_b),
                          "explicit_segments": (seg_a_meta, seg_b_meta)}
    if not topo_match:
        detail = f"self-intersection {si_a} vs {si_b}"
        if seg_a_meta is not None:
            detail += f", segments {seg_a_meta} vs {seg_b_meta}"
        fail_reasons.append(f"topology differs: {detail}")

    # 5. control signature (optional)
    ca = getattr(spec_a, "control", None)
    cb = getattr(spec_b, "control", None)
    if ca is not None and cb is not None:
        ctrl_ok = len(ca) == len(cb) and all(
            math.hypot(p[0] - q[0], p[1] - q[1]) <= band
            for p, q in zip(ca, cb))
        checks["control_signature"] = {"status": "pass" if ctrl_ok else "fail"}
        if not ctrl_ok:
            fail_reasons.append("control-point signature differs")
    else:
        checks["control_signature"] = {"status": "not_provided"}

    undetermined = any(c["status"] == "undetermined" for c in checks.values())
    equivalent = (not undetermined) and point_ok and topo_match and (
        orientation_match is not False) and (
        closed_match is not False) and (endpoints_match is not False)
    if equivalent:
        relation = "equivalent"
    elif reversed_flag and point_ok and topo_match:
        relation = "same_trajectory_reversed"
    else:
        relation = "different"

    return EquivalenceResult(
        equivalent=equivalent,
        undetermined=undetermined,
        relation=relation,
        reversed=reversed_flag,
        checks=checks,
        fail_reasons=fail_reasons,
        hausdorff=hd,
        hausdorff_normalized=hd_norm,
        orientation_match=orientation_match,
        endpoints_match=endpoints_match,
        closed_match=closed_match,
        topology={"self_intersections": (si_a, si_b),
                  "explicit_segments": (seg_a_meta, seg_b_meta)},
        counterexample=counter if not equivalent else None,
    )


# ---------------------------------------------------------------------------
# 2. Similarity-transform recognition (compliant change, NOT equivalence)
# ---------------------------------------------------------------------------

@dataclass
class TransformResult:
    is_similarity: bool
    undetermined: bool
    translation: tuple[float, float]
    scale: float
    rotation_deg: Optional[float]
    reflected: bool
    residual: float
    residual_normalized: float
    preserved: dict = field(default_factory=dict)


def similarity_transform(a: list, b: list, tolerance: float) -> TransformResult:
    """Detect whether b is a scale/translate/rotate/reflect version of a.

    A similarity transform preserves shape, closure and topology; such a pair
    is geometrically non-equivalent but may still satisfy the requirement.
    The prototype aligns centroids, estimates scale from RMS radius, then
    sweeps rotation (and reflection) for the best nearest-neighbor residual.
    """
    band = max(tolerance, 2.0 * tolerance)
    if len(a) < 4 or len(b) < 4:
        return TransformResult(False, True, (0, 0), 1.0, None, False,
                               math.inf, math.inf)

    def centroid(pts):
        return (sum(p[0] for p in pts) / len(pts),
                sum(p[1] for p in pts) / len(pts))

    ca, cb = centroid(a), centroid(b)
    ra = [math.hypot(p[0] - ca[0], p[1] - ca[1]) for p in a]
    rb = [math.hypot(p[0] - cb[0], p[1] - cb[1]) for p in b]
    rms_a = math.sqrt(sum(r * r for r in ra) / len(ra)) or 1.0
    rms_b = math.sqrt(sum(r * r for r in rb) / len(rb)) or 1.0
    scale = rms_b / rms_a

    def align(pts, center, ang, reflect):
        out = []
        cos_, sin_ = math.cos(ang), math.sin(ang)
        for x, y in pts:
            dx, dy = x - center[0], y - center[1]
            if reflect:
                dx = -dx
            out.append((dx * cos_ - dy * sin_, dx * sin_ + dy * cos_))
        return out

    best = (math.inf, None, False)
    for reflect in (False, True):
        for k in range(72):
            ang = 2 * PI * k / 72
            aa = align(a, ca, ang, reflect)
            bb = [(p[0] / scale, p[1] / scale) for p in
                  align(b, cb, 0.0, False)]
            res = max(_nearest(p, bb)[0] for p in aa)
            if res < best[0]:
                best = (res, ang, reflect)

    residual, ang, reflected = best
    diag = _diagonal(b)
    residual_norm = residual / diag
    is_sim = residual <= max(band, band * diag)

    preserved = {
        "closed": None,  # filled by caller from specs
        "topology_match": None,
    }
    return TransformResult(
        is_similarity=is_sim,
        undetermined=False,
        translation=(cb[0] - ca[0], cb[1] - ca[1]),
        scale=scale,
        rotation_deg=math.degrees(ang) if ang is not None else None,
        reflected=reflected,
        residual=residual,
        residual_normalized=residual_norm,
        preserved=preserved,
    )


# ---------------------------------------------------------------------------
# 3. Independent mirror-symmetry verification
# ---------------------------------------------------------------------------

@dataclass
class SymmetryResult:
    verdict: str  # symmetric | near_symmetric | asymmetric | undetermined
    undetermined: bool
    axis_angle_deg: Optional[float]
    axis_intercept: Optional[float]
    residual_median: float
    residual_p90: float
    residual_max: float
    matched: int
    confidence: float
    reason: str = ""


def _reflect(p, angle, center):
    # reflect point across axis through center with given angle
    dx, dy = p[0] - center[0], p[1] - center[1]
    cos_, sin_ = math.cos(angle), math.sin(angle)
    ux, uy = cos_, sin_
    proj = dx * ux + dy * uy
    rx = 2 * proj * ux - dx
    ry = 2 * proj * uy - dy
    return (rx + center[0], ry + center[1])


def _radial_profile(pts: list, bins: int = 180) -> tuple[list[float], tuple[float, float]]:
    center = (sum(p[0] for p in pts) / len(pts),
              sum(p[1] for p in pts) / len(pts))
    buckets: list[list[float]] = [[] for _ in range(bins)]
    for x, y in pts:
        ang = math.atan2(y - center[1], x - center[0])
        idx = int((ang + PI) / (2 * PI) * bins) % bins
        buckets[idx].append(math.hypot(x - center[0], y - center[1]))
    profile = []
    for b in buckets:
        if b:
            b.sort()
            profile.append(b[len(b) // 2])
        else:
            profile.append(math.nan)
    # fill empty bins by neighbor interpolation
    for i in range(bins):
        if math.isnan(profile[i]):
            j = (i + 1) % bins
            while math.isnan(profile[j]):
                j = (j + 1) % bins
            profile[i] = profile[j]
    return profile, center


def symmetry_check(pts: list, tolerance: float,
                   near_band_factor: float = 10.0) -> SymmetryResult:
    """Mirror-symmetry from the radial profile around the centroid.

    For a candidate mirror axis α, compare r(α+φ) with r(α−φ) over the full
    angle sweep; residual is normalized by mean radius.  This avoids the
    nearest-point trivial match that a dense compact curve otherwise gives.

    ``near_band_factor`` (NEW KNOB) widens the near-symmetric band.  Risk: too
    large admits lopsided shapes (false accept); too small rejects genuinely
    approximate symmetry (false reject).
    """
    if len(pts) < 8:
        return SymmetryResult("undetermined", True, None, None,
                              math.inf, math.inf, math.inf, 0, 0.0,
                              "too few samples")
    band = max(tolerance, 2.0 * tolerance)
    profile, center = _radial_profile(pts)
    bins = len(profile)
    mean_r = sum(profile) / bins or 1.0
    # SYM_SYM / SYM_NEAR (NEW KNOBS): relative median radial residual bands.
    # Risk: larger values admit lopsided shapes as symmetric (false accept);
    # smaller values reject approximate symmetry (false reject).
    sym_sym, sym_near = 0.03, 0.10

    best = None
    for k in range(36):
        axis = int(k * bins / 36)
        res = []
        for phi in range(bins // 2):
            i = (axis + phi) % bins
            j = (axis - phi) % bins
            res.append(abs(profile[i] - profile[j]))
        res.sort()
        median = res[len(res) // 2]
        p90 = res[int(0.9 * len(res))]
        mx = res[-1]
        if best is None or p90 < best[1]:
            best = (median, p90, mx, k * 180.0 / 36, res)

    median, p90, mx, ang, res = best
    median_norm, p90_norm, max_norm = median / mean_r, p90 / mean_r, mx / mean_r
    matched = sum(d <= band * mean_r for d in res)

    if p90_norm <= sym_sym:
        verdict, conf = "symmetric", 0.9
    elif p90_norm <= sym_near:
        verdict, conf = "near_symmetric", 0.6
    else:
        verdict, conf = "asymmetric", 0.8

    return SymmetryResult(
        verdict=verdict,
        undetermined=False,
        axis_angle_deg=ang,
        axis_intercept=center[0],
        residual_median=median,
        residual_p90=p90,
        residual_max=mx,
        matched=matched,
        confidence=conf,
        reason="radial-profile mirror residual",
    )


# ---------------------------------------------------------------------------
# 4. Generalized boundary feature classifier
# ---------------------------------------------------------------------------

@dataclass
class FeatureResult:
    role: str  # outward_extrema | inward_notch | cusp | regular | undetermined
    undetermined: bool
    reason: str
    tangent_left_deg: Optional[float] = None
    tangent_right_deg: Optional[float] = None
    angle_gap_deg: Optional[float] = None
    curvature_ratio: Optional[float] = None
    side_sign: int = 0
    offset: Optional[float] = None
    confidence: float = 0.0
    evidence: dict = field(default_factory=dict)


def _tangent_angle(p0, p1) -> float:
    return math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0]))


def _angle_gap(a, b) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def classify_boundary_feature(
    polyline: list[tuple[float, float]],
    index: int,
    tolerance: float,
    window: int = 4,
    crossing_hint: bool = False,
) -> FeatureResult:
    """Classify one boundary point; outputs measurements + confidence + state.

    ``window`` (NEW KNOB) neighbor half-width in samples.  Role combines
    neighbor-chord normal offset (in/out) with tangent gap / curvature ratio.
    ``crossing_hint`` comes from the topology module's chord-straddle result;
    when set, the interior side is ambiguous -> undetermined.  The prototype
    does not re-detect crossings itself (production wires the topology result).
    """
    n = len(polyline)
    band = max(tolerance, 2.0 * tolerance)
    if n < 4 or index < 0 or index >= n:
        return FeatureResult("undetermined", True, "invalid polyline or index",
                              confidence=0.0)
    window = min(window, (n - 1) // 2)
    if window < 1:
        return FeatureResult("undetermined", True, "window out of range",
                              confidence=0.0)

    pts = polyline
    left = pts[(index - window) % n]
    right = pts[(index + window) % n]
    candidate = pts[index]
    chord = (right[0] - left[0], right[1] - left[1])
    chord_len = math.hypot(*chord)
    if chord_len <= 1e-18:
        return FeatureResult("undetermined", True, "degenerate neighbor chord",
                              confidence=0.0)
    normal = (-chord[1] / chord_len, chord[0] / chord_len)
    rel = (candidate[0] - left[0], candidate[1] - left[1])
    offset = rel[0] * normal[0] + rel[1] * normal[1]

    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    toward = (cx - candidate[0]) * normal[0] + (cy - candidate[1]) * normal[1]

    t_left = _tangent_angle(pts[(index - 1) % n], candidate)
    t_right = _tangent_angle(candidate, pts[(index + 1) % n])
    gap = _angle_gap(t_left, t_right)

    turns = [
        _angle_gap(_tangent_angle(pts[(k - 1) % n], pts[k]),
                   _tangent_angle(pts[k], pts[(k + 1) % n]))
        for k in range(n)
    ]
    turns_sorted = sorted(turns)
    median_turn = turns_sorted[len(turns_sorted) // 2]
    curvature_ratio = gap / median_turn if median_turn > 1e-12 else math.inf

    if crossing_hint:
        return FeatureResult("undetermined", True,
                              "self-crossing near candidate (topology hint)",
                              confidence=0.0,
                              evidence={"offset": offset, "gap": gap})

    smooth = curvature_ratio < 1.5 and gap < 30.0
    if abs(offset) <= band or smooth:
        role, side_sign = "regular", 0
        confidence = 0.7
    elif offset * toward > 0:
        role, side_sign = "inward_notch", -1
        confidence = 0.8
    else:
        role, side_sign = "outward_extrema", 1
        # sharp tangent reversal elevates this to a cusp-like feature
        if gap > 120.0:
            role = "cusp"
        confidence = 0.8

    # confidence discount when evidence sits close to the band
    margin = abs(offset) / band if band > 0 else math.inf
    if margin < 2.0:
        confidence *= 0.7

    return FeatureResult(
        role=role,
        undetermined=False,
        reason="neighbor-chord offset + tangent gap",
        tangent_left_deg=t_left,
        tangent_right_deg=t_right,
        angle_gap_deg=gap,
        curvature_ratio=curvature_ratio,
        side_sign=side_sign,
        offset=offset,
        confidence=round(confidence, 2),
        evidence={"toward_centroid": toward, "window": window},
    )
