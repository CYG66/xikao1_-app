"""B1.1 line: generic topology convergence, feedback and regression cases.

All fixtures are built from plain line / Bezier geometry.  The analyzer
under test must not depend on any case id, shape name or fixed
control-point constant.  Contact geometry (segment indices, parameter
intervals, kind, distance, points) is derived from the curves only.
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


def _bez(points):
    return {
        "kind": "bezier",
        "control_points": [{"x": x, "y": y} for x, y in points],
    }


# Wide-control-hull single cubic loop; analytic crossing at (250, 300),
# t ~= 0.1127 / 0.8873.  This is the narrow-loop case that the coarse
# flattened-polyline gate could miss.
LOOP = [(0, 0), (1000, 1000), (-500, 1000), (500, 0)]


def _scale(points, factor):
    return [(x * factor, y * factor) for x, y in points]


def test_single_loop_self_intersection_is_detected_at_crossing() -> None:
    report = safety.analyze_composite_segments([_bez(LOOP)], tolerance=1e-6)
    self_contacts = [c for c in report.contacts if c.kind == safety.CONTACT_SELF]
    assert self_contacts, "loop crossing was not detected"
    assert report.unresolved is False
    contact = self_contacts[0]
    # Analytic reference crossing (250, 300).
    assert abs(contact.point_a[0] - 250.0) < 1.0
    assert abs(contact.point_a[1] - 300.0) < 1.0
    assert abs(contact.parameter_a - 0.1127) < 0.01
    assert abs(contact.parameter_b - 0.8873) < 0.01
    # Generic feedback carries both parameter intervals.
    assert contact.interval_a[0] <= contact.parameter_a <= contact.interval_a[1]
    assert contact.interval_b[0] <= contact.parameter_b <= contact.interval_b[1]


def test_loop_detection_is_scale_invariant() -> None:
    for factor, tolerance in [(100.0, 1e-4), (0.01, 1e-8)]:
        segments = [_bez(_scale(LOOP, factor))]
        report = safety.analyze_composite_segments(segments, tolerance=tolerance)
        self_contacts = [c for c in report.contacts if c.kind == safety.CONTACT_SELF]
        assert self_contacts, f"loop missed at scale {factor}"
        assert report.unresolved is False


def test_mixed_degree_pair_crossing_is_classified() -> None:
    # Quadratic (3 points) against cubic (4 points), leaves cross.
    segments = [
        _bez([(0, 0), (0, 1), (1, 1)]),
        _line((1, 1), (1, 0)),
        _bez([(0, 1), (0, 0), (1, 1), (1, 0)]),
    ]
    report = safety.analyze_composite_segments(segments, tolerance=1e-6)
    crossings = [c for c in report.contacts if c.kind == safety.CONTACT_CROSSING]
    assert crossings, "mixed-degree crossing was not detected"
    pair = {crossings[0].segment_a, crossings[0].segment_b}
    assert pair == {0, 2}
    assert report.unresolved is False


def test_shared_endpoint_is_classified_as_endpoint_contact() -> None:
    # Segment 0 and segment 2 share (0, 0) but are not adjacent in order.
    segments = [
        _line((0, 0), (1, 0)),
        _line((1, 0), (1, 1)),
        _line((1, 1), (0, 0)),
    ]
    report = safety.analyze_composite_segments(segments, tolerance=1e-6)
    endpoints = [c for c in report.contacts if c.kind == safety.CONTACT_ENDPOINT]
    assert endpoints, "shared endpoint was not classified"
    assert {endpoints[0].segment_a, endpoints[0].segment_b} == {0, 2}
    assert abs(endpoints[0].point_a[0]) < 1e-6
    assert abs(endpoints[0].point_a[1]) < 1e-6


def test_convex_and_separated_curves_have_no_contact() -> None:
    segments = [
        _bez([(0, 0), (0, 1), (1, 1), (1, 0)]),
        _bez([(0, 3), (0, 4), (1, 4), (1, 3)]),
        _bez([(5, 0), (5, 4), (9, 4), (9, 0)]),
    ]
    report = safety.analyze_composite_segments(segments, tolerance=1e-6)
    assert report.contacts == []
    assert report.unresolved is False


def test_gate_rejects_loop_composite_path() -> None:
    import pytest

    from app.cad_construction import execute_construction_plan, ConstructionPlanError

    loop = _bez(LOOP)
    plan = {
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [{
            "step_id": "b11-loop",
            "op": "add_composite_path",
            "output_ref": "b11-loop.path",
            "semantic": {"label": "loop probe"},
            "segments": [loop],
        }],
    }
    with pytest.raises(ConstructionPlanError) as caught:
        execute_construction_plan(plan)
    assert caught.value.code == "self_intersecting_composite_path"
    contacts = (caught.value.details or {}).get("curve_contacts") or []
    assert any(c["kind"] == "self" for c in contacts)


def _offset_arches(gap: float) -> list[dict]:
    """Two convex arches whose hulls overlap but bodies stay separated.

    The vertical gap sits outside the proximity band; with an adequate
    search budget the pair resolves clear, while a deliberately truncated
    budget exhausts inside the uncertain band and must report unresolved.
    """
    return [
        _bez([(0, 0), (0, 1), (1, 1), (1, 0)]),
        _line((1, 0), (1, gap)),
        _bez([(1, gap), (1, 1 + gap), (0, 1 + gap), (0, gap)]),
    ]


def test_full_budget_resolves_separated_arches_as_clear() -> None:
    report = safety.analyze_composite_segments(
        _offset_arches(5e-3), tolerance=1e-6)
    assert report.contacts == []
    assert report.unresolved is False


def test_budget_exhaustion_flags_unresolved(monkeypatch) -> None:
    # Deterministic truncation: shrink the per-search node budget so the
    # search exhausts inside the uncertain band.  This does not depend on
    # wall-clock timeout.
    monkeypatch.setattr(safety, "NODE_BUDGET_CAP", 5)
    report = safety.analyze_composite_segments(
        _offset_arches(5e-3), tolerance=1e-6)
    assert report.unresolved is True
    assert report.contacts == []


def test_gate_rejects_unresolved_topology(monkeypatch) -> None:
    import pytest

    from app.cad_construction import (
        ConstructionPlanError,
        execute_construction_plan,
    )

    monkeypatch.setattr(safety, "NODE_BUDGET_CAP", 5)
    plan = {
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [{
            "step_id": "b11-unresolved",
            "op": "add_composite_path",
            "output_ref": "b11-unresolved.path",
            "semantic": {"label": "unresolved probe"},
            "allow_self_intersection": False,
            "segments": _offset_arches(5e-3),
        }],
    }
    with pytest.raises(ConstructionPlanError) as caught:
        execute_construction_plan(plan)
    details = caught.value.details or {}
    assert caught.value.code == "self_intersecting_composite_path"
    assert details["failure_scope"] == "unresolved_topology"
    assert details["escalation"] == "replan_or_human_review"
    assert details["unresolved_topology"] is True


def test_arc_chord_height_bound_monotonic_and_quadratic() -> None:
    radius, angle = 100.0, 90.0
    heights = [safety.arc_chord_height(radius, angle, n) for n in (1, 2, 4, 8)]
    # More chords -> smaller sagitta.
    assert heights == sorted(heights, reverse=True)
    # Small-step quadratic approximation h ~= R (phi/2n)^2 / 2.
    n = 8
    half = math.radians(angle) / (2.0 * n)
    approx = radius * half * half / 2.0
    assert abs(safety.arc_chord_height(radius, angle, n) - approx) / approx < 1e-3
