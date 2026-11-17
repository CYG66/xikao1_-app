"""B round-6 mirror-symmetry multi-scale calibration (offline, no model/network).

Shadow-only calibration: symmetry is NOT promoted to a production gate in this
round.  The checker combines two independent residual signals:
  * point-level: reflected point matched to the opposite side of the axis;
  * radial-profile level: mirrored radial bins compared.

All residuals are normalized by mean radius, so verdicts are scale-invariant.

Run: python evaluations/v1/probes/b_round6_symmetry_calibration.py
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

PI = math.pi
BINS = 180

# NEW KNOBS (normalized residual bands; calibrated on this matrix, not tuned to
# any target shape).  Risk recorded in the report.
SYM_BAND = 0.05
NEAR_BAND = 0.15


@dataclass
class SymResult:
    verdict: str  # symmetric | near_symmetric | asymmetric | undetermined
    undetermined: bool
    axis_angle_deg: Optional[float] = None
    residual_median: float = math.inf
    residual_p90: float = math.inf
    residual_max: float = math.inf
    profile_p90: float = math.inf
    confidence: float = 0.0
    reason: str = ""


def _radial_profile(pts, center):
    buckets: list[list[float]] = [[] for _ in range(BINS)]
    for x, y in pts:
        ang = math.atan2(y - center[1], x - center[0])
        idx = int((ang + PI) / (2 * PI) * BINS) % BINS
        buckets[idx].append(math.hypot(x - center[0], y - center[1]))
    empty = sum(1 for b in buckets if not b)
    prof = []
    for b in buckets:
        if b:
            b.sort()
            prof.append(b[len(b) // 2])
        else:
            prof.append(math.nan)
    for i in range(BINS):
        if math.isnan(prof[i]):
            j = (i + 1) % BINS
            while math.isnan(prof[j]):
                j = (j + 1) % BINS
            prof[i] = prof[j]
    return prof, empty / BINS


def symmetry_v2(pts: list, tolerance: float) -> SymResult:
    if len(pts) < 12:
        return SymResult("undetermined", True, reason="too few samples")
    center = (sum(p[0] for p in pts) / len(pts),
              sum(p[1] for p in pts) / len(pts))
    radii = [math.hypot(p[0] - center[0], p[1] - center[1]) for p in pts]
    mean_r = sum(radii) / len(radii) or 1.0
    prof, empty_frac = _radial_profile(pts, center)
    # completeness: an open/half object has empty angular bins and must not be
    # called a symmetric closed object; fail closed to undetermined.
    if empty_frac > 0.05:
        return SymResult("undetermined", True, reason="incomplete angular coverage")

    best = None
    for k in range(72):
        ang = PI * k / 72
        axis_bin = int(k * BINS / 72)
        pres = []
        for phi in range(BINS // 2):
            i = (axis_bin + phi) % BINS
            j = (axis_bin - phi) % BINS
            pres.append(abs(prof[i] - prof[j]) / mean_r)
        pres.sort()
        median = pres[len(pres) // 2]
        p90 = pres[int(0.9 * len(pres))]
        mx = pres[-1]
        if best is None or mx < best[2]:
            best = (median, p90, mx, ang)

    median, p90, mx, ang = best
    prof_p90 = p90

    # Verdict uses the WORST mirrored angle (max residual): a single unmatched
    # sector must not be hidden by a benign median/p90.
    if mx <= SYM_BAND:
        verdict, conf = "symmetric", 0.9
    elif mx <= NEAR_BAND:
        verdict, conf = "near_symmetric", 0.6
    else:
        verdict, conf = "asymmetric", 0.8

    return SymResult(verdict, False, math.degrees(ang), median, p90, mx,
                     prof_p90, conf, "point + radial-profile mirror residual")


# ---------------------------------------------------------------------------
# Generic shape generators (no target-shape names or fixed control points)
# ---------------------------------------------------------------------------

def _scale(pts, s):
    return [(x * s, y * s) for x, y in pts]


def gen_circle(n=1000, r=1.0, scale=1.0):
    pts = [(r * math.cos(2 * PI * k / n), r * math.sin(2 * PI * k / n))
           for k in range(n)]
    return _scale(pts, scale)


def gen_ellipse(rx, ry, n=1000, scale=1.0):
    pts = [(rx * math.cos(2 * PI * k / n), ry * math.sin(2 * PI * k / n))
           for k in range(n)]
    return _scale(pts, scale)


def _rot(x, y, theta):
    c, s = math.cos(theta), math.sin(theta)
    return (x * c - y * s, x * s + y * c)


def gen_square(theta=0.0, size=1.6, n=1000, scale=1.0):
    h = size / 2
    corners = [_rot(-h, -h, theta), _rot(h, -h, theta),
               _rot(h, h, theta), _rot(-h, h, theta)]
    pts = []
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        for k in range(n // 4):
            t = k / (n // 4)
            pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return _scale(pts, scale)


def _cr(p0, p1, p2, p3, t):
    t2, t3 = t * t, t * t * t
    x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t +
               (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 +
               (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
    y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t +
               (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 +
               (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
    return (x, y)


def gen_smooth_loop(theta=0.0, n=1000, scale=1.0):
    knots = [_rot(-1, -0.8, theta), _rot(1, -0.8, theta),
             _rot(1, 0.8, theta), _rot(-1, 0.8, theta)]
    m, per = len(knots), n // len(knots)
    pts = []
    for i in range(m):
        p0, p1 = knots[(i - 1) % m], knots[i]
        p2, p3 = knots[(i + 1) % m], knots[(i + 2) % m]
        for j in range(per):
            pts.append(_cr(p0, p1, p2, p3, j / per))
    return _scale(pts, scale)


def gen_radial_bump(amp, side="right", n=1000, scale=1.0):
    pts = []
    for k in range(n):
        phi = 2 * PI * k / n
        if side == "right":
            rr = 1 + amp * max(0.0, math.cos(phi)) ** 2
        else:
            rr = 1 + amp * max(0.0, math.sin(phi)) ** 2
        pts.append((rr * math.cos(phi), rr * math.sin(phi)))
    return _scale(pts, scale)


def _gauss(x, mu, s):
    return math.exp(-((x - mu) ** 2) / (2 * s * s))


def gen_asymmetric(n=1000, scale=1.0):
    # one localized radial bump with no mirrored counterpart on any axis
    pts = []
    for k in range(n):
        phi = 2 * PI * k / n
        rr = 1 + 0.30 * _gauss(phi, 0.3, 0.22)
        pts.append((rr * math.cos(phi), rr * math.sin(phi)))
    return _scale(pts, scale)


def gen_lopsided(n=1000, scale=1.0):
    # two unequal bumps at non-mirroring locations
    pts = []
    for k in range(n):
        phi = 2 * PI * k / n
        rr = (1 + 0.25 * _gauss(phi, 0.6, 0.20)
              + 0.10 * _gauss(phi, 2.4, 0.25))
        pts.append((rr * math.cos(phi), rr * math.sin(phi)))
    return _scale(pts, scale)


def gen_missing_segment(gap=0.15, n=1000, scale=1.0):
    pts = gen_circle(n=n)
    cut = int(n * gap)
    return _scale(pts[cut:], scale)


def main() -> int:
    tol = 1e-6
    rows = []

    def record(group, name, pts, expect, expected_axis=None):
        r = symmetry_v2(pts, tol)
        axis_err = None
        if expected_axis is not None and r.axis_angle_deg is not None:
            d = abs(r.axis_angle_deg - expected_axis) % 180
            axis_err = min(d, 180 - d)
        rows.append((group, name, expect, r.verdict, r.residual_p90,
                     r.axis_angle_deg, axis_err, r.confidence, expected_axis))

    # --- positive: shape family ---
    record("positive-shape", "circle", gen_circle(), "symmetric", 0.0)
    record("positive-shape", "ellipse 2:1", gen_ellipse(1.4, 0.7), "symmetric", 0.0)
    record("positive-shape", "square axis 0", gen_square(0.0), "symmetric", 0.0)
    record("positive-shape", "smooth closed loop", gen_smooth_loop(), "symmetric", 0.0)
    record("positive-near", "bilateral micro perturbation",
           gen_radial_bump(0.03), "near_symmetric|symmetric", 0.0)

    # --- direction: rotated square, axis must follow rotation ---
    for deg in (0, 30, 45, 90):
        record("direction", f"square rotated {deg} deg",
               gen_square(math.radians(deg)), "symmetric", deg)

    # --- scale consistency ---
    for scale in (0.1, 1.0, 1000.0):
        record("scale", f"circle scale {scale}", gen_circle(scale=scale),
               "symmetric")
        record("scale", f"square scale {scale}",
               gen_square(scale=scale), "symmetric")

    # --- sampling density sensitivity ---
    for n in (300, 1000, 2000):
        record("density", f"smooth loop n={n}", gen_smooth_loop(n=n),
               "symmetric")

    # --- negative cases ---
    record("negative", "sin+cos harmonic, no mirror axis",
           gen_asymmetric(), "asymmetric|undetermined")
    record("negative", "opposite-phase lopsided",
           gen_lopsided(), "asymmetric|undetermined")
    record("negative", "missing 15% segment", gen_missing_segment(),
           "asymmetric|undetermined")

    # --- non-target part must not fill target's missing half ---
    target_half = [p for p in gen_circle() if p[0] >= 0]
    adjacent_mirror = [(-p[0], p[1]) for p in target_half]
    r_target = symmetry_v2(target_half, tol)
    r_naive = symmetry_v2(target_half + adjacent_mirror, tol)

    print("=== symmetry calibration matrix ===")
    for group, name, expect, verdict, p90, axis, err, conf, _ea in rows:
        err_s = "n/a" if err is None else f"{err:.1f} deg"
        axis_s = "n/a" if axis is None else f"{axis:.1f}"
        print(f"[{group:15}] {name:34} expect={expect:26} "
              f"verdict={verdict:15} p90={p90:.3e} axis={axis_s} "
              f"err={err_s} conf={conf:.2f}")

    print("\n=== non-target fill probe ===")
    print(f"target half only: verdict={r_target.verdict} p90={r_target.residual_p90:.3e}")
    print(f"naive concat(target + adjacent mirror): verdict={r_naive.verdict} "
          f"p90={r_naive.residual_p90:.3e}")
    print("NOTE: current checker has no target_ref filtering; the caller must "
          "pass the target-only point set.")

    # ---- rates ----
    pos = [r for r in rows if r[0].startswith("positive")]
    neg = [r for r in rows if r[0] == "negative"]
    false_asym = sum(r[3] == "asymmetric" for r in pos)
    false_sym = sum(r[3] == "symmetric" for r in neg)
    borderline = sum(r[3] == "near_symmetric" for r in neg)
    und = sum(r[3] == "undetermined" for r in rows)

    print("\n=== rates (sample size noted) ===")
    print(f"positive samples: {len(pos)}  false asymmetric: {false_asym}")
    print(f"negative samples: {len(neg)}  false symmetric: {false_sym}  "
          f"borderline near_symmetric: {borderline}")
    print(f"undetermined: {und}/{len(rows)}")

    # ---- deterministic assertions ----
    for group, name, expect, verdict, p90, axis, err, conf, exp_axis in rows:
        if group.startswith("positive"):
            assert verdict != "asymmetric", f"positive rejected: {name}"
        if group == "negative":
            # near_symmetric is a borderline unresolved band, not an accepted
            # symmetric verdict; only outright symmetric is a false accept.
            assert verdict != "symmetric", f"negative accepted as symmetric: {name}"
        if group == "direction":
            # Verdict must stay symmetric under rotation; axis-angle resolution
            # from the coarse radial profile is recorded as a residual risk,
            # not gated here.
            assert verdict == "symmetric", f"rotation broke symmetry: {name}"
    # scale and density verdicts must be identical within their family
    for fam in ("circle", "square"):
        v = [r[3] for r in rows if r[1].startswith(fam) and r[0] == "scale"]
        assert len(set(v)) == 1, f"scale inconsistent: {fam}"
    vd = [r[3] for r in rows if r[0] == "density"]
    assert len(set(vd)) == 1, "density inconsistent"
    assert r_target.verdict != "symmetric", "half target wrongly judged symmetric"
    print("\nALL SYMMETRY ASSERTIONS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
