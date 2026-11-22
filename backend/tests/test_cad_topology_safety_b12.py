"""B1.2 line: arc / spline curve-level intersection and error bounds.

All fixtures are plain line / bezier / arc / spline geometry.  The analyzer
must not read any case id, shape name or fixed control-point constant; every
reported contact is derived from the curves and their parameter values.
"""
from __future__ import annotations

import math

import app.cad_topology_safety as safety


def _line(a, b):
    return {
        "kind": "line",
        "start": {"x": a[0], "y": a[1]},
        "end": {"x": b[0], "y": b[1]},
    }


def _arc(cx, cy, radius, start, end, clockwise=False):
    return {
        "kind": "arc",
        "center": {"x": cx, "y": cy},
        "radius": radius,
        "start_angle": start,
        "end_angle": end,
        "clockwise": clockwise,
    }


def _spline(points, degree=3):
    return {
        "kind": "spline",
        "degree": degree,
        "control_points": [{"x": x, "y": y} for x, y in points],
    }


def _bez(points):
    return {
        "kind": "bezier",
        "control_points": [{"x": x, "y": y} for x, y in points],
    }


# ---------------------------------------------------------------------------
# Arc: detected crossing, negative control, closed-form error bound
# ---------------------------------------------------------------------------

def test_arc_crossing_a_line_is_detected() -> None:
    # Quarter circle R=100 centred on the origin, horizontal line y=50.
    # Analytic intersection: x = sqrt(100**2 - 50**2) = 86.6025.
    segments = [
        _line((-20, 50), (120, 50)),
        _line((120, 50), (120, 0)),
        _arc(0, 0, 100.0, 0, 90),
    ]
    report = safety.analyze_composite_segments(segments, tolerance=1e-4)
    crossings = [c for c in report.contacts if c.kind == safety.CONTACT_CROSSING]
    assert crossings, "arc-line crossing was not detected"
    pair = {crossings[0].segment_a, crossings[0].segment_b}
    assert pair == {0, 2}
    assert abs(crossings[0].point_a[0] - 86.6025) < 1.0
    assert abs(crossings[0].point_a[1] - 50.0) < 1.0
    assert report.unresolved is False


def test_separated_arches_arc_pair_is_clear() -> None:
    segments = [
        _arc(0, 0, 100.0, 0, 90),
        _line((100, 0), (300, 0)),
        _arc(300, 0, 100.0, 0, 90),
    ]
    report = safety.analyze_composite_segments(segments, tolerance=1e-4)
    assert report.contacts == []
    assert report.unresolved is False


def test_arc_chord_count_inversion_satisfies_sagitta_bound() -> None:
    radius, sweep, h_max = 100.0, 90.0, 1e-3
    count = safety.arc_chord_count_for_tolerance(radius, sweep, h_max)
    assert count >= 1
    assert safety.arc_chord_height(radius, sweep, count) <= h_max
    # One fewer chord must already exceed the bound (count is minimal).
    if count > 1:
        assert safety.arc_chord_height(radius, sweep, count - 1) > h_max


def test_arc_sagitta_is_monotone_and_quadratic_at_small_steps() -> None:
    radius, angle = 100.0, 90.0
    heights = [safety.arc_chord_height(radius, angle, n) for n in (1, 2, 4, 8)]
    assert heights == sorted(heights, reverse=True)
    n = 8
    half = math.radians(angle) / (2.0 * n)
    approx = radius * half * half / 2.0
    # 1 - cos x <= x**2/2, so the quadratic form is a conservative upper bound.
    assert safety.arc_chord_height(radius, angle, n) <= approx * (1 + 1e-3)


# ---------------------------------------------------------------------------
# Spline: detected crossing, negative control, residual bound
# ---------------------------------------------------------------------------

def test_spline_crossing_a_line_is_detected() -> None:
    segments = [
        _line((-20, 50), (120, 50)),
        _line((120, 50), (120, 0)),
        _spline([(0, 0), (20, 100), (80, 100), (100, 0)]),
    ]
    report = safety.analyze_composite_segments(segments, tolerance=1e-3)
    crossings = [c for c in report.contacts if c.kind == safety.CONTACT_CROSSING]
    assert crossings, "spline-line crossing was not detected"
    assert {crossings[0].segment_a, crossings[0].segment_b} == {0, 2}
    assert report.unresolved is False


def test_separated_splines_are_clear() -> None:
    segments = [
        _spline([(0, 0), (20, 100), (80, 100), (100, 0)]),
        _spline([(0, 300), (20, 400), (80, 400), (100, 300)]),
    ]
    report = safety.analyze_composite_segments(segments, tolerance=1e-3)
    assert report.contacts == []
    assert report.unresolved is False


def test_spline_residual_bound_shrinks_with_density_and_meets_tolerance() -> None:
    control = [(0, 0), (20, 100), (80, 100), (100, 0)]
    coarse = safety.spline_residual_bound(control, 3, 16)
    fine = safety.spline_residual_bound(control, 3, 128)
    assert fine < coarse
    chosen = 256
    assert safety.spline_residual_bound(control, 3, chosen) <= 1e-2


# ---------------------------------------------------------------------------
# Fail-closed contract: truncation never emits a definite classification
# ---------------------------------------------------------------------------

DEFINITE_KINDS = {
    safety.CONTACT_CROSSING,
    safety.CONTACT_TANGENT,
    safety.CONTACT_SELF,
    safety.CONTACT_ENDPOINT,
}


def _offset_arches(gap: float) -> list[dict]:
    return [
        _bez([(0, 0), (0, 1), (1, 1), (1, 0)]),
        _line((1, 0), (1, gap)),
        _bez([(1, gap), (1, 1 + gap), (0, 1 + gap), (0, gap)]),
    ]


def test_truncation_keeps_unresolved_and_no_definite_contact(monkeypatch) -> None:
    monkeypatch.setattr(safety, "NODE_BUDGET_CAP", 5)
    report = safety.analyze_composite_segments(
        _offset_arches(5e-3), tolerance=1e-6)
    assert report.unresolved is True
    assert {c.kind for c in report.contacts} <= {safety.CONTACT_NEAR}


# ---------------------------------------------------------------------------
# Legal-geometry batch: false-rejection scan
# ---------------------------------------------------------------------------

def _legal_fixtures() -> list[tuple[str, list[dict], float]]:
    return [
        ("separated bezier arches", [
            _bez([(0, 0), (0, 1), (1, 1), (1, 0)]),
            _bez([(0, 3), (0, 4), (1, 4), (1, 3)]),
            _bez([(5, 0), (5, 4), (9, 4), (9, 0)]),
        ], 1e-6),
        ("offset arches near band", _offset_arches(5e-3), 1e-6),
        ("separated arcs", [
            _arc(0, 0, 100.0, 0, 90),
            _line((100, 0), (300, 0)),
            _arc(300, 0, 100.0, 0, 90),
        ], 1e-4),
        ("separated splines", [
            _spline([(0, 0), (20, 100), (80, 100), (100, 0)]),
            _spline([(0, 300), (20, 400), (80, 400), (100, 300)]),
        ], 1e-3),
        ("convex smooth cubic", [
            _bez([(0, 0), (0.2, 1), (0.8, 1), (1, 0)]),
        ], 1e-6),
    ]


def test_legal_batch_has_no_unresolved_or_false_contact() -> None:
    rejected = []
    for label, segments, tolerance in _legal_fixtures():
        report = safety.analyze_composite_segments(segments, tolerance=tolerance)
        if report.unresolved or report.contacts:
            rejected.append((label, report.unresolved,
                             [c.kind for c in report.contacts]))
    assert rejected == []
