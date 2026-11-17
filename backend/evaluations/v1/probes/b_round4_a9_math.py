"""B round-4 offline numeric probe for the A9 parametric curve.

Pure numeric experiment; no model call, no network, no production code.
Curve (verbatim from the D case record):

    x(t) = 2 + 2 sin t
    y(t) = 3 + 2 cos t + 2 sqrt(abs(sin t)) cos t

Round 1 domain [0, 2*pi]; round 2 domain [-pi, pi].
"""
from __future__ import annotations

import math
import sys

PI = math.pi


def point(t: float) -> tuple[float, float]:
    return (
        2.0 + 2.0 * math.sin(t),
        3.0 + 2.0 * math.cos(t) + 2.0 * math.sqrt(abs(math.sin(t))) * math.cos(t),
    )


def sample(a: float, b: float, n: int) -> list[tuple[float, float]]:
    return [point(a + (b - a) * k / n) for k in range(n + 1)]


def nearest_dist(p, others) -> float:
    return min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in others)


def hausdorff(a, b) -> tuple[float, float, float]:
    ab = max(nearest_dist(p, b) for p in a)
    ba = max(nearest_dist(p, a) for p in b)
    return ab, ba, max(ab, ba)


def arc_length(pts) -> float:
    return sum(
        math.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1])
        for k in range(len(pts) - 1)
    )


def bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def deriv(t: float, h: float) -> tuple[float, float]:
    p0 = point(t - h)
    p1 = point(t + h)
    return ((p1[0] - p0[0]) / (2 * h), (p1[1] - p0[1]) / (2 * h))


def curvature(t: float, h: float) -> float:
    x1, y1 = deriv(t, h)
    # second derivative via central difference of first derivative
    x0, y0 = deriv(t - h, h)
    x2, y2 = deriv(t + h, h)
    x2d = (x2 - 2 * x1 + x0) / h**2
    y2d = (y2 - 2 * y1 + y0) / h**2
    denom = (x1**2 + y1**2) ** 1.5
    if denom <= 1e-18:
        return math.inf
    return abs(x1 * y2d - y1 * x2d) / denom


def main() -> None:
    n = 2000
    s1 = sample(0.0, 2 * PI, n)
    s2 = sample(-PI, PI, n)

    print("== set-equivalence: [0,2pi] vs [-pi,pi] ==")
    print("bbox s1:", tuple(round(v, 6) for v in bbox(s1)))
    print("bbox s2:", tuple(round(v, 6) for v in bbox(s2)))
    print("arc length s1: %.6f  s2: %.6f" % (arc_length(s1), arc_length(s2)))
    ab, ba, hd = hausdorff(s1, s2)
    print("Hausdorff a->b=%.3e b->a=%.3e max=%.3e" % (ab, ba, hd))

    print("\n== global y extrema along [0,2pi] ==")
    ys = [(point(t)[1], t, point(t)[0]) for t in (2 * PI * k / 4000 for k in range(4000))]
    ys_sorted = sorted(ys)
    print("lowest 5:")
    for y, t, x in ys_sorted[:5]:
        print("  t=%.4f x=%.4f y=%.6f" % (t, x, y))
    print("highest 5:")
    for y, t, x in ys_sorted[-5:][::-1]:
        print("  t=%.4f x=%.4f y=%.6f" % (t, x, y))

    print("\n== local structure near t=pi ==")
    for u in (-0.05, -0.01, -0.003, 0.0, 0.003, 0.01, 0.05):
        t = PI + u
        x, y = point(t)
        print("  u=%+.3f t=%.4f x=%.5f y=%.6f" % (u, t, x, y))

    print("\n== one-sided derivatives / slopes / curvature near pi ==")
    for side, h in (("left u<0", 1e-3), ("right u>0", 1e-3)):
        t = PI + (-h if side.startswith("left") else h)
        vx, vy = deriv(t, h)
        slope = math.inf if abs(vx) < 1e-12 else vy / vx
        k = curvature(t, h)
        print("  %s t=%.5f v=(%.5f,%.5f) slope=%.4f curvature=%.4g"
              % (side, t, vx, vy, slope, k))

    # regular reference point t=pi/2
    vx, vy = deriv(PI / 2, 1e-4)
    print("  regular t=pi/2 v=(%.5f,%.5f) curvature=%.4g" %
          (vx, vy, curvature(PI / 2, 1e-4)))

    print("\n== separation baseline: deliberately modified variant ==")
    def point_mod(t):
        return (
            2.0 + 2.0 * math.sin(t),
            3.0 + 2.0 * math.cos(t) - 2.0 * math.sqrt(abs(math.sin(t))) * math.cos(t),
        )
    sm = [point_mod(2 * PI * k / n) for k in range(n + 1)]
    ab2, ba2, hd2 = hausdorff(s1, sm)
    print("Hausdorff original vs modified: max=%.4f" % hd2)


def feature_check() -> None:
    pts = sample(0.0, 2 * PI, 4000)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    w, h = max_x - min_x, max_y - min_y
    norm = [((x - min_x) / w, (y - min_y) / h) for x, y in pts]
    lower_tip = any(abs(x - 0.5) < 0.1 and y < 0.01 for x, y in norm)
    center = point(PI)
    ncx = (center[0] - min_x) / w
    ncy = (center[1] - min_y) / h
    print("\n== detector rule replay (lower_tip: |x-.5|<.1 and y<.01) ==")
    print("bbox x[%.4f,%.4f] y[%.4f,%.4f]" % (min_x, max_x, min_y, max_y))
    print("t=pi point normalized=(%.4f, %.4f)  lower_tip=%s" % (ncx, ncy, lower_tip))
    lows = sorted(zip(ys, xs))[:2]
    for y, x in lows:
        print("  side low point norm=(%.4f, %.5f)" % ((x - min_x) / w, (y - min_y) / h))

    # left-right symmetry about x=2: compare f(t) and reflection of f(pi-t)
    worst = 0.0
    for k in range(1, 4000):
        t = 2 * PI * k / 4000
        a = point(t)
        b = point(PI - t)
        reflected = (4.0 - b[0], b[1])
        worst = max(worst, math.hypot(a[0] - reflected[0], a[1] - reflected[1]))
    print("left-right symmetry max residual about x=2: %.3e" % worst)

    # pi-periodicity check: f(t+pi) vs f(t)
    worst_pi = 0.0
    for k in range(1, 2000):
        t = 2 * PI * k / 4000
        worst_pi = max(worst_pi, math.dist(point(t), point(t + PI)))
    print("max |f(t+pi)-f(t)| (pi-periodicity residual): %.4f" % worst_pi)


if __name__ == "__main__":
    main()
    feature_check()
