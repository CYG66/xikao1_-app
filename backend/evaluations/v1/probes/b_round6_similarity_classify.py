"""B round-6 similarity relation classification (offline, no model/network).

Five-level relation between two candidate geometries:
  identical    : machine-precision match, all dimensions match
  equivalent   : within equivalence tolerance band
  similar      : shape family / topology preserved, outside equivalence band
                 (PASS-THROUGH signal, NOT an equivalence claim)
  different    : topology / closed state / loop count mismatch or large gap
  undetermined : insufficient evidence

`similar` must never be consumed downstream as `equivalent`; closeness alone
is not equivalence.  Run:
  python evaluations/v1/probes/b_round6_similarity_classify.py
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

PI = math.PI if hasattr(math, "PI") else math.pi

# NEW KNOBS (normalized Hausdorff bands; calibrated on this matrix).
EQ_BAND = 0.02      # equivalence: same trajectory within 2% of diagonal
SIM_BAND = 0.08     # similar: preserved topology, close same-family gap
IDENT_BAND = 1e-12


@dataclass
class Relation:
    level: str
    undetermined: bool
    reasons: list = field(default_factory=list)
    hd_norm: float = math.inf
    closed_match: Optional[bool] = None
    self_intersections: tuple = (None, None)


# ---------------------------------------------------------------------------
# Generic geometry generators
# ---------------------------------------------------------------------------

def _circle(cx, cy, r, n=600):
    return [(cx + r * math.cos(2 * PI * k / n),
             cy + r * math.sin(2 * PI * k / n)) for k in range(n)]


def _ellipse(cx, cy, rx, ry, n=600):
    return [(cx + rx * math.cos(2 * PI * k / n),
             cy + ry * math.sin(2 * PI * k / n)) for k in range(n)]


def _square(cx, cy, size, n=600):
    h = size / 2
    corners = [(cx - h, cy - h), (cx + h, cy - h),
               (cx + h, cy + h), (cx - h, cy + h)]
    pts = []
    per = n // 4
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        for k in range(per):
            t = k / per
            pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return pts


def _cr(p0, p1, p2, p3, t):
    t2, t3 = t * t, t * t * t
    x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t +
               (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 +
               (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
    y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t +
               (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 +
               (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
    return (x, y)


def _smooth_loop(cx, cy, w, h, n=600):
    knots = [(cx - w, cy - h), (cx + w, cy - h),
             (cx + w, cy + h), (cx - w, cy + h)]
    per = n // 4
    pts = []
    for i in range(4):
        p0, p1 = knots[(i - 1) % 4], knots[i]
        p2, p3 = knots[(i + 1) % 4], knots[(i + 2) % 4]
        for j in range(per):
            pts.append(_cr(p0, p1, p2, p3, j / per))
    return pts


def _bowtie(n=600):
    return [(math.sin(2 * PI * k / n * 2), math.sin(2 * PI * k / n))
            for k in range(n)]


def _arc(cx, cy, r, n=120):
    return [(cx + r * math.cos(PI * k / n), cy + r * math.sin(PI * k / n))
            for k in range(n + 1)]


def _two_loops(n=400):
    a = _circle(-1.2, 0, 0.6, n // 2)
    b = _circle(1.2, 0, 0.6, n // 2)
    return a + b


def _bean(n=600, perturb=0.0):
    pts = []
    for k in range(n):
        phi = 2 * PI * k / n
        rr = 1 + 0.25 * math.cos(phi) + perturb * math.sin(2 * phi)
        pts.append((rr * math.cos(phi), rr * math.sin(phi)))
    return pts


def _asymmetric(n=600):
    pts = []
    for k in range(n):
        phi = 2 * PI * k / n
        rr = 1 + 0.20 * max(0.0, math.cos(phi)) ** 2 + 0.15 * max(0.0, math.sin(phi)) ** 2
        pts.append((rr * math.cos(phi), rr * math.sin(phi)))
    return pts


# ---------------------------------------------------------------------------
# Measurement helpers
# ---------------------------------------------------------------------------

def _diag(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys)) or 1.0


def _nearest(p, others):
    return min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in others)


def _hausdorff_norm(a, b):
    d = max(max(_nearest(p, b) for p in a), max(_nearest(p, a) for p in b))
    return d / max(_diag(a), _diag(b))


def _self_intersections(pts):
    # coarse chord-straddle count on sampled polyline
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    segs = [(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]
    hits = 0
    for i in range(len(segs)):
        a, b = segs[i]
        for j in range(i + 2, len(segs)):
            if i == 0 and j == len(segs) - 1:
                continue
            c, d = segs[j]
            o1, o2 = orient(a, b, c), orient(a, b, d)
            o3, o4 = orient(c, d, a), orient(c, d, b)
            if o1 * o2 < 0 and o3 * o4 < 0:
                hits += 1
    return hits


def classify(a, b, closed_a=True, closed_b=True) -> Relation:
    if not a or not b:
        return Relation("undetermined", True, ["missing geometry evidence"])
    hd = _hausdorff_norm(a, b)
    si_a, si_b = _self_intersections(a), _self_intersections(b)
    closed_match = closed_a == closed_b
    topo_match = si_a == si_b and closed_match

    reasons = []
    if hd <= IDENT_BAND and topo_match:
        return Relation("identical", False, ["machine-precision match"], hd,
                        closed_match, (si_a, si_b))
    if hd <= EQ_BAND and topo_match:
        return Relation("equivalent", False, ["within equivalence band"], hd,
                        closed_match, (si_a, si_b))
    if not topo_match:
        reasons.append("topology/closed state differs")
        return Relation("different", False, reasons, hd, closed_match,
                        (si_a, si_b))
    if hd <= SIM_BAND:
        return Relation("similar", False,
                         ["topology preserved, moderate shape gap"], hd,
                         closed_match, (si_a, si_b))
    reasons.append("shape gap exceeds similar band")
    return Relation("different", False, reasons, hd, closed_match,
                    (si_a, si_b))


def main() -> int:
    similar_cases = [
        ("circle r1.5 vs r1.7", _circle(0, 0, 1.5), _circle(0, 0, 1.7)),
        ("circle vs slight oval 1.5x1.35", _circle(0, 0, 1.5),
         _ellipse(0, 0, 1.5, 1.35)),
        ("ellipse 2.2x1.0 vs 2.0x1.1", _ellipse(0, 0, 2.2, 1.0),
         _ellipse(0, 0, 2.0, 1.1)),
        ("bean vs mildly perturbed bean", _bean(), _bean(perturb=0.05)),
        ("smooth loop vs 1.1x scaled", _smooth_loop(0, 0, 1.0, 0.8),
         _smooth_loop(0, 0, 1.1, 0.88)),
        ("circle vs near-circle oval 1.5x1.4", _circle(0, 0, 1.5),
         _ellipse(0, 0, 1.5, 1.4)),
    ]

    different_cases = [
        ("square vs smooth closed loop", _square(0, 0, 1.8),
         _smooth_loop(0, 0, 1.0, 0.8)),
        ("square vs rounded square loop", _square(0, 0, 1.8),
         _smooth_loop(0, 0, 0.95, 0.95)),
        ("square vs circle", _square(0, 0, 1.8), _circle(0, 0, 1.5)),
        ("circle vs compound asymmetric", _circle(0, 0, 1.5), _asymmetric()),
        ("circle vs self-intersecting bowtie", _circle(0, 0, 1.5), _bowtie()),
        ("closed circle vs open arc", _circle(0, 0, 1.5), _arc(0, 0, 1.5),
         True, False),
        ("single loop vs two loops", _circle(0, 0, 1.5), _two_loops()),
        ("ellipse vs bowtie", _ellipse(0, 0, 2.2, 1.0), _bowtie()),
        ("smooth loop vs two near-contact loops", _smooth_loop(0, 0, 1, 0.8),
         _two_loops()),
    ]

    print("=== similar candidates (expect similar/equivalent, NOT different) ===")
    sim_ok = 0
    for name, a, b in similar_cases:
        r = classify(a, b)
        ok = r.level in ("similar", "equivalent", "identical")
        sim_ok += ok
        print(f"{name:38} -> {r.level:12} hd_norm={r.hd_norm:.3e} "
              f"topo={r.closed_match}/{r.self_intersections} "
              f"{'OK' if ok else 'MISCLASSIFIED'}")

    print("\n=== different candidates (expect different/undetermined) ===")
    diff_ok = 0
    for tup in different_cases:
        name, a, b = tup[0], tup[1], tup[2]
        ca = tup[3] if len(tup) > 3 else True
        cb = tup[4] if len(tup) > 4 else True
        r = classify(a, b, ca, cb)
        ok = r.level in ("different", "undetermined")
        diff_ok += ok
        print(f"{name:38} -> {r.level:12} hd_norm={r.hd_norm:.3e} "
              f"topo={r.closed_match}/{r.self_intersections} "
              f"{'OK' if ok else 'MISCLASSIFIED'}")

    print("\n=== summary ===")
    print(f"similar side: {sim_ok}/{len(similar_cases)} accepted as similar-or-better")
    print(f"different side: {diff_ok}/{len(different_cases)} rejected as non-similar")

    assert sim_ok == len(similar_cases), "similar case pushed to different"
    assert diff_ok == len(different_cases), "different case accepted as similar"
    print("\nALL SIMILARITY ASSERTIONS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
