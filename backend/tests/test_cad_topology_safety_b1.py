"""B1 line: generic composite-path topology safety regression tests.

These fixtures are constructed from generic Bezier/line geometry only.
The analyzer under test must not depend on any case id, shape name or
fixed control-point constant; the tangent contact is derived analytically
from the curve tangent at an interior parameter.
"""
from __future__ import annotations

import math

import pytest


def _bez(points, t):
    vals = [tuple(p) for p in points]
    while len(vals) > 1:
        vals = [
            (left[0] + (right[0] - left[0]) * t,
             left[1] + (right[1] - left[1]) * t)
            for left, right in zip(vals, vals[1:])
        ]
    return vals[0]


def _derivative(points, t):
    p0, p1, p2 = points[0], points[1], points[2]
    if len(points) == 3:
        return (
            2 * (1 - t) * (p1[0] - p0[0]) + 2 * t * (p2[0] - p1[0]),
            2 * (1 - t) * (p1[1] - p0[1]) + 2 * t * (p2[1] - p1[1]),
        )
    p3 = points[3]
    a = (3 * (p1[0] - p0[0]), 3 * (p1[1] - p0[1]))
    b = (3 * (p2[0] - p1[0]), 3 * (p2[1] - p1[1]))
    c = (3 * (p3[0] - p2[0]), 3 * (p3[1] - p2[1]))
    return (
        (1 - t) ** 2 * a[0] + 2 * (1 - t) * t * b[0] + t * t * c[0],
        (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * b[1] + t * t * c[1],
    )


def _tangent_line(points, tau, length=3.0):
    point = _bez(points, tau)
    dv = _derivative(points, tau)
    norm = math.hypot(*dv)
    ux, uy = dv[0] / norm, dv[1] / norm
    return [
        (point[0] - length * ux, point[1] - length * uy),
        (point[0] + length * ux, point[1] + length * uy),
    ]


def _plan(step_id, arch, tau):
    line = _tangent_line(arch, tau)
    arch_rev = list(reversed(arch))
    segments = [
        {
            "kind": "line",
            "start": {"x": line[0][0], "y": line[0][1]},
            "end": {"x": line[1][0], "y": line[1][1]},
        },
        {
            "kind": "line",
            "start": {"x": line[1][0], "y": line[1][1]},
            "end": {"x": arch_rev[0][0], "y": arch_rev[0][1]},
        },
        {
            "kind": "bezier",
            "control_points": [{"x": x, "y": y} for x, y in arch_rev],
        },
    ]
    return {
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [{
            "step_id": step_id,
            "op": "add_composite_path",
            "output_ref": f"{step_id}.path",
            "semantic": {"label": "B1 拓扑探针"},
            "segments": segments,
        }],
    }


# Independent case A: cubic arch, tangent contact on the left flank
# (contact parameter off the uniform 1/32 sample grid).
CUBIC_ARCH = [(-1.0, 0.0), (-1.0, 1.0), (1.0, 1.0), (1.0, 0.0)]
CUBIC_TAU = 0.237

# Independent case B: quadratic arch, different proportions and contact on
# the right flank; curvature extremum sits at the centre of the span.
QUADRATIC_ARCH = [(-1.2, 0.0), (0.0, 1.4), (1.2, 0.0)]
QUADRATIC_TAU = 0.71


def test_b1_cubic_arch_tangent_contact_is_rejected() -> None:
    from app.cad_construction import execute_construction_plan, ConstructionPlanError

    plan = _plan("b1-cubic", CUBIC_ARCH, CUBIC_TAU)
    with pytest.raises(ConstructionPlanError) as caught:
        execute_construction_plan(plan)
    assert caught.value.code == "self_intersecting_composite_path"
    details = caught.value.details or {}
    contacts = details.get("curve_contacts") or []
    affected = {index for item in contacts for index in item["segment_indices"]}
    assert {0, 2} <= affected


def test_b1_quadratic_arch_tangent_contact_is_rejected() -> None:
    from app.cad_construction import execute_construction_plan, ConstructionPlanError

    plan = _plan("b1-quadratic", QUADRATIC_ARCH, QUADRATIC_TAU)
    with pytest.raises(ConstructionPlanError) as caught:
        execute_construction_plan(plan)
    assert caught.value.code == "self_intersecting_composite_path"
    details = caught.value.details or {}
    contacts = details.get("curve_contacts") or []
    affected = {index for item in contacts for index in item["segment_indices"]}
    assert {0, 2} <= affected
