"""D-line independent matrix for the atomic source-fact pass.

The scenes are synthetic and deliberately vary numbers, order and identities.
They never call a model and never touch the production store.
"""
from __future__ import annotations

import math

import pytest

from app.cad_requirement_binding import bind_construction_coverage
from app.cad_source_acceptance import build_requirement_coverage_evidence


def circle(gid, cx, cy, radius):
    return {"id": gid, "type": "circle", "center": {"x": cx, "y": cy},
            "radius": radius, "selected": True}


def line(gid, x1, y1, x2, y2):
    return {"id": gid, "type": "line", "start": {"x": x1, "y": y1},
            "end": {"x": x2, "y": y2}, "selected": True}


def arc(gid, cx, cy, radius, start_deg, end_deg):
    return {"id": gid, "type": "arc", "center": {"x": cx, "y": cy},
            "radius": radius, "start_angle": start_deg,
            "end_angle": end_deg, "selected": True}


def polyline(gid, points, closed=False):
    return {"id": gid, "type": "polyline", "closed": closed, "selected": True,
            "vertices": [{"x": x, "y": y} for x, y in points]}


def obj(object_id, gid, label, **extra):
    return {"object_id": object_id, "object_type": "drawing_part",
            "label": label, "geometry_refs": [gid], "confirmed": True,
            **extra}


def bind(text, geoms, objects):
    steps = [{"step_id": f"s{i}", "output_ref": item["object_id"]}
             for i, item in enumerate(objects, 1)]
    coverage = build_requirement_coverage_evidence(text, {})
    return bind_construction_coverage(
        coverage, logical_objects=objects, geometries=geoms, plan_steps=steps,
        project_evidence={"project_exists": True, "project_id": "offline"},
    )


def clause(bound, prefix):
    return next(item for item in bound["clauses"]
                if item["requirement"].startswith(prefix))


def test_arc_radius_centre_and_sweep_are_measured():
    text = ("画一段圆弧，圆心(-1500,1000)，半径2200毫米，"
            "从30度逆时针画到150度，只画这段弧")
    geoms = [arc(1, -1500, 1000, 2200, 30, 150)]
    bound = bind(text, geoms, [obj("arc_main", 1, "圆弧")])
    assert bound["state"] == "complete", bound["blocking_requirements"]
    assert clause(bound, "半径2200毫米")["status"] == "verified"


def test_line_endpoints_and_length_are_measured():
    text = ("画一条直线导轨中心线，从(-1200,800)到(3600,2200)，"
            "单位毫米，端点必须准确落在给定坐标")
    geoms = [line(1, -1200, 800, 3600, 2200)]
    bound = bind(text, geoms, [obj("line_main", 1, "直线导轨中心线")])
    assert bound["state"] == "complete", bound["blocking_requirements"]


def test_three_circles_require_three_distinct_objects():
    text = ("画三个独立的圆形柱础，圆心分别在(-1800,0)、(0,0)、(1800,0)，"
            "半径都是240毫米，三个圆必须分别成对象，不能粘成一条轮廓")
    geoms = [circle(1, -1800, 0, 240), circle(2, 0, 0, 240),
             circle(3, 1800, 0, 240)]
    objects = [obj("base_1", 1, "柱础1"), obj("base_2", 2, "柱础2"),
               obj("base_3", 3, "柱础3")]
    bound = bind(text, geoms, objects)
    assert bound["state"] == "complete", bound["blocking_requirements"]
    proofs = bound["binding"]["object_count_proofs"]
    assert any(item["quantity"] == 3 and item["actual"] == 3 for item in proofs)


def test_two_circles_do_not_satisfy_three_circle_source():
    text = ("画三个独立的圆形柱础，圆心分别在(-1800,0)、(0,0)、(1800,0)，"
            "半径都是240毫米，三个圆必须分别成对象，不能粘成一条轮廓")
    geoms = [circle(1, -1800, 0, 240), circle(2, 0, 0, 240)]
    objects = [obj("base_1", 1, "柱础1"), obj("base_2", 2, "柱础2")]
    bound = bind(text, geoms, objects)
    assert bound["state"] != "complete"
    assert clause(bound, "画三个独立的圆形柱础")["status"] != "verified"


def test_swapped_circle_radius_is_not_accepted():
    text = ("画三个独立的圆形柱础，圆心分别在(-1800,0)、(0,0)、(1800,0)，"
            "半径都是240毫米，三个圆必须分别成对象，不能粘成一条轮廓")
    geoms = [circle(1, -1800, 0, 240), circle(2, 0, 0, 200),
             circle(3, 1800, 0, 240)]
    objects = [obj("base_1", 1, "柱础1"), obj("base_2", 2, "柱础2"),
               obj("base_3", 3, "柱础3")]
    bound = bind(text, geoms, objects)
    assert bound["state"] != "complete"
    assert clause(bound, "半径都是240毫米")["status"] != "verified"


def test_singular_clause_with_two_same_kind_objects_stays_ambiguous():
    text = "画一个矩形宽4米高2米"
    geoms = [
        polyline(1, [(-2000, -1000), (2000, -1000), (2000, 1000), (-2000, 1000)],
                 closed=True),
        polyline(2, [(-2000, 3000), (2000, 3000), (2000, 5000), (-2000, 5000)],
                 closed=True),
    ]
    objects = [obj("rect_main", 1, "矩形 宽4米高2米"),
               obj("rect_extra", 2, "另一个矩形")]
    bound = bind(text, geoms, objects)
    assert bound["state"] != "complete"
    assert clause(bound, "画一个矩形")["status"] != "verified"


def test_open_smooth_sine_is_continuous_and_not_closed():
    points = [(0.0, 0.0)]
    for index in range(1, 257):
        x = 4800.0 * index / 256
        points.append((x, 200.0 * math.sin(2 * math.pi * index / 256)))
    geoms = [polyline(1, points, closed=False)]
    text = ("画一条正弦波纹板中心线，从(0,0)开始，水平跨度4800毫米，"
            "振幅200毫米，正好一个完整周期，线要连续平滑且不闭合")
    bound = bind(text, geoms, [obj("wave", 1, "正弦波纹板中心线")])
    assert bound["state"] == "complete", bound["blocking_requirements"]


def test_smooth_closed_outline_with_long_chord_is_not_accepted():
    points = []
    for index in range(128):
        angle = 2 * math.pi * index / 128
        points.append((300.0 * math.cos(angle),
                       500.0 * (1 + math.sin(angle))))
    # Deliberately remove the closing neighbourhood: the executor still says
    # closed=True, but a 95 mm chord is inserted into a smooth outline.
    points = points[:120]
    geoms = [polyline(1, points, closed=True)]
    text = ("画一个水滴形幕墙轮廓，底部尖点在(0,0)，最宽处在高度正中，"
            "左右对称，轮廓闭合且除底部尖点外平滑")
    bound = bind(text, geoms, [obj("waterdrop", 1, "水滴形幕墙轮廓")])
    assert bound["state"] != "complete"
    closure = clause(bound, "轮廓闭合")
    assert closure["status"] != "verified"
    check = next(item for item in closure["binding"]["checks"]
                 if item["predicate"] == "outline_closure_and_continuity")
    assert check["status"] == "failed"
    assert check["detail"]["closure_gap_status"] == "failed"


def test_sampling_step_gap_is_not_mistaken_for_an_inserted_chord():
    # 4 m x 4 m heart-like closed outline sampled at ~78 mm steps.  The last
    # sample sits 3 mm from the first: that is the final sampling step, not a
    # long closing chord (the A9 regression boundary).
    points = []
    for index in range(128):
        fraction = index / 128
        if fraction < 0.25:
            points.append((4000.0 * fraction * 4, 0.0))
        elif fraction < 0.5:
            points.append((4000.0, 4000.0 * (fraction - 0.25) * 4))
        elif fraction < 0.75:
            points.append((4000.0 - 4000.0 * (fraction - 0.5) * 4, 4000.0))
        else:
            points.append((0.0, 4000.0 - 4000.0 * (fraction - 0.75) * 4))
    points.append((3.0, 0.0))
    geoms = [polyline(1, points, closed=True)]
    text = "画一个矩形轮廓，宽4000毫米、高4000毫米，闭合且平滑"
    bound = bind(text, geoms, [obj("rect_outline", 1, "矩形轮廓")])
    closure = clause(bound, "闭合")
    check = next(item for item in closure["binding"]["checks"]
                 if item["predicate"] == "outline_closure_and_continuity")
    assert check["detail"]["closure_gap_status"] == "verified"


def test_composite_arm_clause_does_not_pass_with_wrong_height():
    # L outline: horizontal arm 3000 x 800, vertical arm 800 x 2200.
    points = [(0, 0), (3000, 0), (3000, 800), (800, 800),
              (800, 2200), (0, 2200)]
    geoms = [polyline(1, points, closed=True)]
    text = ("画一个L形支架的闭合外轮廓：水平臂长3000毫米、宽800毫米，"
            "竖直臂高2200毫米、宽800毫米，左下角在(0,0)")
    bound = bind(text, geoms, [obj("l_bracket", 1, "L形支架")])
    assert bound["state"] == "complete", bound["blocking_requirements"]
    # Shrinking the vertical arm must break the height fact and must not be
    # masked by the still-correct horizontal arm.
    bad = [(0, 0), (3000, 0), (3000, 800), (800, 800), (800, 1800), (0, 1800)]
    bound_bad = bind(text, [polyline(1, bad, closed=True)],
                     [obj("l_bracket", 1, "L形支架")])
    assert bound_bad["state"] != "complete"
    assert clause(bound_bad, "竖直臂高2200毫米")["status"] != "verified"


@pytest.mark.parametrize("order", [(0, 1, 2), (2, 0, 1), (1, 2, 0)])
def test_circle_order_does_not_change_the_proof(order):
    text = ("画三个独立的圆形柱础，圆心分别在(-1800,0)、(0,0)、(1800,0)，"
            "半径都是240毫米，三个圆必须分别成对象，不能粘成一条轮廓")
    coords = [(-1800, 0), (0, 0), (1800, 0)]
    geoms = [circle(i + 1, coords[index][0], coords[index][1], 240)
             for i, index in enumerate(order)]
    objects = [obj(f"base_{i}", i + 1, f"柱础{i}") for i in range(3)]
    bound = bind(text, geoms, objects)
    assert bound["state"] == "complete", bound["blocking_requirements"]
