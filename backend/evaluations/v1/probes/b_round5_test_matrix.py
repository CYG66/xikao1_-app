"""B round-5 independent test matrix (offline, deterministic, no model/network).

Categories (each reported separately, not only totals):
  A  equivalent: same trajectory, parameterization / domain / density / phase differs
  B  reversed direction: same point set, opposite traversal -> non-equivalent (orientation)
  C  compliant real change: geometry changes but requirement invariants preserved
  D  genuinely different geometry
  E  tolerance boundary: inside / outside the 2·tol band
  F  curve type x shape x scale grid (parametric / bezier / spline / arc; 0.1 and 1000)
  G  undetermined triggers

Misclassification rates:
  false inequivalent: known-equivalent (A) judged non-equivalent
  false equivalent:   known non-equivalent (B/C/D/E2/G) judged equivalent

Run: python evaluations/v1/probes/b_round5_test_matrix.py
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import b_round5_geometry_contract as gc

PI = math.pi
TOL = 1e-6


# ---------------------------------------------------------------------------
# Generic curve generators (no A9/heart coordinates, no case-id whitelist)
# ---------------------------------------------------------------------------

def circle_fn(cx, cy, r):
    return lambda t: (cx + r * math.cos(t), cy + r * math.sin(t))


def ellipse_fn(cx, cy, rx, ry):
    return lambda t: (cx + rx * math.cos(t), cy + ry * math.sin(t))


def bowtie_fn():
    return lambda t: (math.sin(2 * t), math.sin(t))


def bumped_fn(cx, cy, r, amp=0.18, phase=0.0):
    def f(t):
        rr = r * (1.0 + amp * max(0.0, math.cos(t - phase)) ** 2)
        return (cx + rr * math.cos(t), cy + rr * math.sin(t))
    return f


def bean_fn(cx, cy, r):
    # lopsided closed loop: not invariant under rotation/reflection
    return lambda t: (
        cx + r * (1 + 0.25 * math.cos(t)) * math.cos(t),
        cy + r * (1 + 0.15 * math.sin(t)) * math.sin(t),
    )


def reparam_circle(cx, cy, r):
    # monotone non-uniform reparameterization of the same circle
    return lambda t: (cx + r * math.cos(t + 0.4 * math.sin(t)),
                      cy + r * math.sin(t + 0.4 * math.sin(t)))


def cubic_bezier(p0, p1, p2, p3, n=80):
    def b(t):
        u = 1 - t
        return (
            u ** 3 * p0[0] + 3 * u ** 2 * t * p1[0] + 3 * u * t ** 2 * p2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u ** 2 * t * p1[1] + 3 * u * t ** 2 * p2[1] + t ** 3 * p3[1],
        )
    return [b(k / n) for k in range(n + 1)]


def bezier_loop(scale=1.0):
    top = cubic_bezier((-1, 0), (-1, 1.2), (1, 1.2), (1, 0))
    bottom = cubic_bezier((1, 0), (1, -1.2), (-1, -1.2), (-1, 0))
    return [(x * scale, y * scale) for x, y in top + bottom]


def _cr(p0, p1, p2, p3, t):
    t2, t3 = t * t, t * t * t
    x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t +
               (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 +
               (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
    y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t +
               (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 +
               (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
    return (x, y)


def spline_loop(knots, per=16, scale=1.0):
    m = len(knots)
    pts = []
    for i in range(m):
        p0, p1 = knots[(i - 1) % m], knots[i]
        p2, p3 = knots[(i + 1) % m], knots[(i + 2) % m]
        for j in range(per):
            pts.append(_cr(p0, p1, p2, p3, j / per))
    return [(x * scale, y * scale) for x, y in pts]


def square_points(cx, cy, size):
    h = size / 2
    return [(cx - h, cy - h), (cx + h, cy - h),
            (cx + h, cy + h), (cx - h, cy + h), (cx - h, cy - h)]


def arc_points(cx, cy, r, a0, a1, n=60):
    return [(cx + r * math.cos(a0 + (a1 - a0) * k / n),
             cy + r * math.sin(a0 + (a1 - a0) * k / n)) for k in range(n + 1)]


def two_loops(scale=1.0):
    a = arc_points(-1.2 * scale, 0, 0.6 * scale, 0, 2 * PI, 40)
    b = arc_points(1.2 * scale, 0, 0.6 * scale, 0, 2 * PI, 40)
    return a + b


def make(fn, t0=0.0, t1=2 * PI, samples=400, closed=True, kind="parametric"):
    return SimpleNamespace(fn=fn, t0=t0, t1=t1, samples=samples,
                            closed=closed, kind=kind)


def points_spec(pts, closed=True, kind="polyline"):
    return SimpleNamespace(points=pts, closed=closed, kind=kind)


def transform(pts, scale=1.0, trans=(0.0, 0.0), rot=0.0, reflect=False):
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    cos_, sin_ = math.cos(rot), math.sin(rot)
    out = []
    for x, y in pts:
        dx, dy = x - cx, y - cy
        if reflect:
            dx = -dx
        dx, dy = dx * scale, dy * scale
        out.append((cx + trans[0] + dx * cos_ - dy * sin_,
                    cy + trans[1] + dx * sin_ + dy * cos_))
    return out


def perturb_circle(r, delta):
    return lambda t: (2 + (r + delta) * math.cos(t), 3 + (r + delta) * math.sin(t))


# ---------------------------------------------------------------------------

def main() -> int:
    rows = []

    def add(group, name, spec_a, spec_b, expect, note=""):
        res = gc.trajectory_equivalent(spec_a, spec_b, TOL)
        pts_a, pts_b = gc._sample(spec_a), gc._sample(spec_b)
        sim = gc.similarity_transform(pts_a, pts_b, TOL) if pts_a and pts_b else None
        rows.append({
            "group": group, "name": name, "expect": expect,
            "equivalent": res.equivalent, "undetermined": res.undetermined,
            "similarity": sim.is_similarity if sim else False,
            "hd": res.hausdorff, "hd_norm": res.hausdorff_normalized,
            "relation": res.relation, "reasons": res.fail_reasons, "note": note,
        })

    base = make(circle_fn(2, 3, 1.5))
    base_pts = gc._sample(base)

    # ---- A. equivalent: same trajectory, different parameterization ----
    add("A-equivalent", "parametric domain shift [0,2pi] vs [-pi,pi]",
        base, make(circle_fn(2, 3, 1.5), -PI, PI), "equivalent")
    add("A-equivalent", "non-uniform reparameterization, same circle",
        base, make(reparam_circle(2, 3, 1.5)), "equivalent")
    add("A-equivalent", "density 300 vs 1000",
        make(circle_fn(2, 3, 1.5), samples=300),
        make(circle_fn(2, 3, 1.5), samples=1000), "equivalent")
    add("A-equivalent", "start phase shift",
        base, make(circle_fn(2, 3, 1.5), 0.5, 2 * PI + 0.5), "equivalent")
    add("A-equivalent", "bezier loop resample",
        points_spec(bezier_loop()), points_spec(bezier_loop()), "equivalent")
    add("A-equivalent", "spline loop resample",
        points_spec(spline_loop([(-1, 0), (0, 1), (1, 0), (0, -1)])),
        points_spec(spline_loop([(-1, 0), (0, 1), (1, 0), (0, -1)])), "equivalent")

    # ---- B. reversed direction: same point set, opposite traversal ----
    add("B-reversed", "reversed parameter domain [2pi,0]",
        base, make(circle_fn(2, 3, 1.5), 2 * PI, 0.0),
        "same_trajectory_reversed", "orientation dimension fails")
    add("B-reversed", "reversed point order",
        base, points_spec(list(reversed(base_pts))),
        "same_trajectory_reversed", "orientation dimension fails")

    # ---- C. compliant real change: invariants preserved ----
    add("C-compliant", "uniform scale x1.5",
        base, points_spec(transform(base_pts, scale=1.5)), "similarity")
    add("C-compliant", "translation (3,-2)",
        base, points_spec(transform(base_pts, trans=(3, -2))), "similarity")
    bean = make(bean_fn(2, 3, 1.5))
    bean_pts = gc._sample(bean)
    add("C-compliant", "rotation 30 deg (lopsided loop)",
        bean, points_spec(transform(bean_pts, rot=math.radians(30))), "similarity")
    add("C-compliant", "reflection (lopsided loop)",
        bean, points_spec(transform(bean_pts, reflect=True)), "similarity")
    square = square_points(0, 0, 2)
    smooth = spline_loop([(-1, -1), (1, -1), (1, 1), (-1, 1)])
    add("C-compliant", "square -> smoothed closed loop (topology preserved)",
        points_spec(square), points_spec(smooth), "compliant_other",
        "closed + 0 self-intersections + symmetric preserved")

    # ---- D. genuinely different ----
    add("D-different", "circle vs ellipse",
        base, make(ellipse_fn(2, 3, 2.2, 1.0)), "different")
    add("D-different", "circle vs one-sided bump",
        base, make(bumped_fn(2, 3, 1.5)), "different")
    add("D-different", "closed loop vs self-intersecting bowtie",
        base, make(bowtie_fn()), "different")
    add("D-different", "closed circle vs open arc",
        base, points_spec(arc_points(2, 3, 1.5, 0, PI), closed=False),
        "different")
    add("D-different", "single loop vs two near-contact loops",
        base, points_spec(two_loops()), "different")

    # ---- E. tolerance boundary: inside vs outside the combined band ----
    add("E-boundary", "radius perturb +1e-7 (inside 2·tol band)",
        base, make(perturb_circle(1.5, 1e-7)), "equivalent")
    add("E-boundary", "radius perturb +0.35 (outside resolution band)",
        base, make(perturb_circle(1.5, 0.35)), "different")

    # ---- F. curve type x scale grid (0.1 and 1000) ----
    grid = []
    for scale in (0.1, 1000.0):
        # parametric circle, domain-shift equivalence
        a = make(circle_fn(0, 0, 1.5 * scale))
        b = make(circle_fn(0, 0, 1.5 * scale), -PI, PI)
        r = gc.trajectory_equivalent(a, b, TOL * scale)
        grid.append(("parametric circle", scale, "equivalent", r.equivalent,
                     r.hausdorff_normalized, r.relation))
        # bezier loop, resample equivalence
        a = points_spec(bezier_loop(scale))
        b = points_spec(bezier_loop(scale))
        r = gc.trajectory_equivalent(a, b, TOL * scale)
        grid.append(("bezier loop", scale, "equivalent", r.equivalent,
                     r.hausdorff_normalized, r.relation))
        # spline loop, resample equivalence
        knots = [(-1, 0), (0, 1), (1, 0), (0, -1)]
        a = points_spec(spline_loop(knots, scale=scale))
        b = points_spec(spline_loop(knots, scale=scale))
        r = gc.trajectory_equivalent(a, b, TOL * scale)
        grid.append(("spline loop", scale, "equivalent", r.equivalent,
                     r.hausdorff_normalized, r.relation))
        # open arc: open state recorded (equivalence not applicable)
        a = points_spec(arc_points(0, 0, 1.5 * scale, 0, PI), closed=False)
        r = gc.trajectory_equivalent(a, points_spec(
            arc_points(0, 0, 1.5 * scale, 0, PI), closed=False), TOL * scale)
        grid.append(("open arc", scale, "equivalent", r.equivalent,
                     r.hausdorff_normalized, r.relation))

    # ---- G. undetermined triggers ----
    add("G-undetermined", "missing spec", None, base, "undetermined")
    add("G-undetermined", "too few samples",
        points_spec(base_pts[:3]), points_spec(base_pts[:3]), "undetermined")

    # ---- symmetry ----
    sym_rows = []
    def sym(name, pts, expect):
        s = gc.symmetry_check(pts, TOL)
        sym_rows.append((name, expect, s.verdict, s.residual_median,
                         s.residual_p90, s.residual_max, s.axis_angle_deg,
                         s.confidence))

    sym("circle", gc._sample(make(circle_fn(0, 0, 1.5))), "symmetric")
    sym("ellipse", gc._sample(make(ellipse_fn(0, 0, 2.2, 1.0))), "symmetric")
    sym("deliberately bumped", gc._sample(make(bumped_fn(0, 0, 1.5, 0.60))),
        "asymmetric")
    sym("slightly perturbed", gc._sample(make(bumped_fn(0, 0, 1.5, 0.05))),
        "near|asymmetric")

    # ---- boundary feature classifier ----
    feat_rows = []
    corner = gc.classify_boundary_feature(square_points(0, 0, 2), 1, TOL)
    feat_rows.append(("square corner", "outward|cusp", corner.role,
                      corner.confidence, corner.angle_gap_deg, corner.side_sign))
    circ = gc._sample(make(circle_fn(0, 0, 1.5)))
    regular = gc.classify_boundary_feature(circ, 0, TOL)
    feat_rows.append(("circle regular point", "regular", regular.role,
                      regular.confidence, regular.angle_gap_deg, regular.side_sign))
    bow = gc._sample(make(bowtie_fn()))
    cross = gc.classify_boundary_feature(bow, len(bow) // 2, TOL,
                                         crossing_hint=True)
    feat_rows.append(("bowtie crossing neighborhood", "undetermined",
                      cross.role, cross.confidence, cross.angle_gap_deg,
                      cross.side_sign))

    # ---- report ----
    print("=== A-G matrix ===")
    for r in rows:
        print(f"[{r['group']:13}] {r['name']:44} expect={r['expect']:26} "
              f"eq={int(r['equivalent'])} und={int(r['undetermined'])} "
              f"sim={int(r['similarity'])} hd_norm={r['hd_norm']:.2e} "
              f"rel={r['relation']}")
        for reason in r["reasons"]:
            print(f"      dimension: {reason}")

    print("\n=== F grid: curve type x scale ===")
    for ctype, scale, expect, ok, hdn, rel in grid:
        print(f"{ctype:18} scale={scale:<7} expect={expect:11} eq={int(ok)} "
              f"hd_norm={hdn:.3e} rel={rel}")

    print("\n=== symmetry ===")
    for name, expect, verdict, med, p90, mx, ang, conf in sym_rows:
        print(f"{name:24} expect={expect:18} verdict={verdict:15} "
              f"median={med:.3e} p90={p90:.3e} max={mx:.3e} "
              f"axis={ang:.1f} conf={conf:.2f}")

    print("\n=== boundary features ===")
    for name, expect, role, conf, gap, side in feat_rows:
        gap_s = "n/a" if gap is None else f"{gap:.1f}"
        print(f"{name:32} expect={expect:18} role={role:18} "
              f"conf={conf:.2f} gap={gap_s} side={side}")

    # ---- misclassification rates ----
    a_rows = [r for r in rows if r["group"] == "A-equivalent"]
    non_eq = [r for r in rows if r["expect"] != "equivalent"]
    false_ineq = sum(not r["equivalent"] for r in a_rows)
    false_eq = sum(r["equivalent"] for r in non_eq)
    sim_miss = sum(not r["similarity"] for r in rows if r["group"] == "C-compliant"
                   and r["expect"] == "similarity")

    print("\n=== misclassification ===")
    print(f"false inequivalent: {false_ineq}/{len(a_rows)} "
          f"(known-equivalent judged non-equivalent)")
    print(f"false equivalent:   {false_eq}/{len(non_eq)} "
          f"(known non-equivalent judged equivalent)")
    print(f"similarity missed:  {sim_miss}/4")

    # ---- deterministic gate ----
    assert false_ineq == 0, "known-equivalent pair rejected"
    assert false_eq == 0, "known non-equivalent pair accepted as equivalent"
    for ctype, scale, expect, ok, _, rel in grid:
        assert ok, f"grid equivalence failed: {ctype} scale {scale}"
    for name, expect, role, conf, gap, side in feat_rows:
        if expect == "undetermined":
            assert role == "undetermined"
    print("\nALL MATRIX ASSERTIONS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
