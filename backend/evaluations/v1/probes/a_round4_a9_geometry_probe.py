"""Read-only geometry probe for round-4 case A9 (heart, deepseek-flash attempt 1/2).

Zero network, zero model call, zero production-code change. Reproduces the
normalization and feature booleans used by the production semantic acceptance
check (cad_semantic_acceptance.py:211-214) and the structure contract check
(cad_structure_contract.py:340-343), on the two rejected plans recorded in
round4/A9_case_record.json:

  attempt 1: x=2+2*sin(t), y=3+2*cos(t)+2*sqrt(abs(sin(t)))*cos(t), [0, 2*pi]
  attempt 2: same expressions, interval [-pi, pi]

The probe only samples the already-recorded expressions; it does not generate
geometry, call a provider, or mutate the frozen case record.
"""
from __future__ import annotations

import math
import statistics

X_EXPR = "2+2*sin(t)"
Y_EXPR = "3+2*cos(t)+2*sqrt(abs(sin(t)))*cos(t)"

# Recorded plans use metres; the acceptance rules expect width/height 4 m,
# centre (2, 3) m.
EXPECTED_WIDTH_M = 4.0
EXPECTED_HEIGHT_M = 4.0
EXPECTED_CENTER_M = (2.0, 3.0)


def x_of(t: float) -> float:
    return 2 + 2 * math.sin(t)


def y_of(t: float) -> float:
    return 3 + 2 * math.cos(t) + 2 * math.sqrt(abs(math.sin(t))) * math.cos(t)


def sample(start: float, end: float, n: int = 12_000):
    return [(x_of(start + (end - start) * i / n),
             y_of(start + (end - start) * i / n)) for i in range(n + 1)]


def features(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    norm = [((x - min(xs)) / w, (y - min(ys)) / h) for x, y in points]
    # Thresholds copied verbatim from cad_semantic_acceptance.py:211-214.
    sem = {
        "center_notch": any(abs(x - 0.5) < 0.03 and 0.5 < y < 0.9 for x, y in norm),
        "left_upper_lobe": any(x < 0.45 and y > 0.85 for x, y in norm),
        "right_upper_lobe": any(x > 0.55 and y > 0.85 for x, y in norm),
        "lower_tip": any(abs(x - 0.5) < 0.1 and y < 0.01 for x, y in norm),
    }
    # Stricter thresholds copied from cad_structure_contract.py:340-343.
    struct = {
        "center_notch": any(abs(x - 0.5) < 0.03 and 0.5 < y < 0.98 for x, y in norm),
        "left_upper_lobe": any(x < 0.45 and y > 0.98 for x, y in norm),
        "right_upper_lobe": any(x > 0.55 and y > 0.98 for x, y in norm),
        "lower_tip": any(abs(x - 0.5) < 0.1 and y < 0.01 for x, y in norm),
    }
    bottom = min(points, key=lambda p: p[1])
    center = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    return {
        "bounds": (min(xs), max(xs), min(ys), max(ys)),
        "width_m": w,
        "height_m": h,
        "measured_center_m": center,
        "bottommost_point_m": bottom,
        "bottom_x_normalized": (bottom[0] - min(xs)) / w,
        "features_semantic": sem,
        "features_structure_contract": struct,
    }


def summarize(label, start, end):
    pts = sample(start, end)
    rep = features(pts)
    print(f"== {label} interval [{start}, {end}] ==")
    print(f"  bounds(xmin,xmax,ymin,ymax) = {tuple(round(v, 6) for v in rep['bounds'])}")
    print(f"  width={rep['width_m']:.6f} m  height={rep['height_m']:.6f} m")
    print(f"  measured center = ({rep['measured_center_m'][0]:.6f}, {rep['measured_center_m'][1]:.6f}) m")
    print(f"  bottommost point = ({rep['bottommost_point_m'][0]:.6f}, {rep['bottommost_point_m'][1]:.6f}) m")
    print(f"  bottom x normalized = {rep['bottom_x_normalized']:.6f} (tip band |x-0.5|<0.1)")
    print(f"  features (semantic acceptance)   = {rep['features_semantic']}")
    print(f"  features (structure contract)   = {rep['features_structure_contract']}")
    return pts, rep


def geometry_equivalent(a, b, tol=1e-6):
    """Compare extrema and feature booleans; the expressions are 2*pi-periodic
    in t, so two full-period intervals [0,2pi] and [-pi,pi] must cover the
    same closed curve. Exact multiset comparison would be redundant here."""
    ra, rb = features(a), features(b)
    return (
        abs(ra["width_m"] - rb["width_m"]) <= tol
        and abs(ra["height_m"] - rb["height_m"]) <= tol
        and all(abs(x - y) <= tol for x, y in zip(ra["measured_center_m"], rb["measured_center_m"]))
        and ra["features_semantic"] == rb["features_semantic"]
        and ra["features_structure_contract"] == rb["features_structure_contract"]
    )


if __name__ == "__main__":
    p1, r1 = summarize("attempt 1", 0.0, 2 * math.pi)
    print()
    p2, r2 = summarize("attempt 2", -math.pi, math.pi)
    print()
    same = geometry_equivalent(p1, p2)
    print(f"periodic point-set equivalence attempt1 vs attempt2: {same}")
    print(f"expected width/height/center: {EXPECTED_WIDTH_M} / {EXPECTED_HEIGHT_M} / {EXPECTED_CENTER_M}")
    print("NOTE: this probe reports sampled estimates only; production acceptance")
    print("uses adaptive chord sampling (cad_parametric.sample_curve), not a uniform grid.")
