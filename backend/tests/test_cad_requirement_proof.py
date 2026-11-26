"""A-line proof tests: general requirement binding and measured predicates.

These tests use offline synthetic outlines only.  They never call a model and
never write to the production store.
"""
from __future__ import annotations

import math

import pytest

from app.cad_geometric_predicates import (
    closure_measure,
    corner_circle_collection,
    heart_cusp_points,
    mirror_symmetry,
)
from app.cad_requirement_binding import bind_construction_coverage
from app.cad_requirement_contract import split_source_clauses
from app.cad_semantic_acceptance import verify_semantic_requirements
from app.cad_source_acceptance import (
    build_requirement_coverage_evidence,
    verify_final_source_contract,
)
from app.cad_structure_contract import StructureContractError

C7_TEXT = "画一个矩形宽4米高2米，在四个角各放一个半径0.5米的圆"
A9_TEXT = "生成一个左右对称、平滑闭合的爱心，中心在(2,3)，宽4米高4米"


def rectangle(gid, cx, cy, width, height):
    x0, x1 = cx - width / 2, cx + width / 2
    y0, y1 = cy - height / 2, cy + height / 2
    return {
        "id": gid, "type": "polyline", "closed": True, "selected": True,
        "vertices": [
            {"x": x0, "y": y0}, {"x": x1, "y": y0},
            {"x": x1, "y": y1}, {"x": x0, "y": y1},
        ],
    }


def circle(gid, cx, cy, radius):
    return {"id": gid, "type": "circle", "center": {"x": cx, "y": cy},
            "radius": radius, "selected": True}


def circle_object(object_id, gid, label):
    return {"object_id": object_id, "object_type": "drawing_part",
            "label": label, "geometry_refs": [gid], "confidence": 0.95}


def rectangle_object(object_id, gid, label):
    return circle_object(object_id, gid, label)


def heart_points(cx=2000.0, cy=3000.0, width=4000.0, height=4000.0,
                 samples=192):
    raw = []
    for index in range(samples):
        t = 2 * math.pi * index / samples
        raw.append((math.sin(t) ** 3,
                    (13 * math.cos(t) - 5 * math.cos(2 * t)
                     - 2 * math.cos(3 * t) - math.cos(4 * t)) / 16.0))
    xs = [item[0] for item in raw]
    ys = [item[1] for item in raw]
    sx = width / (max(xs) - min(xs))
    sy = height / (max(ys) - min(ys))
    return [
        {"x": cx + (x - (max(xs) + min(xs)) / 2) * sx,
         "y": cy + (y - (max(ys) + min(ys)) / 2) * sy}
        for x, y in raw
    ]


def heart(gid=1, cx=2000.0, cy=3000.0, width=4000.0, height=4000.0,
          closed=True, samples=192):
    return {"id": gid, "type": "polyline", "closed": closed, "selected": True,
            "vertices": heart_points(cx, cy, width, height, samples)}


def c7_scene():
    geoms = [
        rectangle(1, 0, 0, 4000, 2000),
        circle(2, -2000, 1000, 500),
        circle(3, 2000, 1000, 500),
        circle(4, -2000, -1000, 500),
        circle(5, 2000, -1000, 500),
    ]
    objects = [
        rectangle_object("rectangle_main", 1, "矩形 宽4米高2米"),
        circle_object("circle_tl", 2, "左上角圆 半径0.5米"),
        circle_object("circle_tr", 3, "右上角圆 半径0.5米"),
        circle_object("circle_bl", 4, "左下角圆 半径0.5米"),
        circle_object("circle_br", 5, "右下角圆 半径0.5米"),
    ]
    steps = [
        {"step_id": "rect1", "output_ref": "rectangle_main"},
        {"step_id": "c1", "output_ref": "circle_tl"},
        {"step_id": "c2", "output_ref": "circle_tr"},
        {"step_id": "c3", "output_ref": "circle_bl"},
        {"step_id": "c4", "output_ref": "circle_br"},
    ]
    return geoms, objects, steps


def bind_scene(text, geoms, objects, steps):
    coverage = build_requirement_coverage_evidence(text, {})
    return bind_construction_coverage(
        coverage, logical_objects=objects, geometries=geoms,
        plan_steps=steps,
        project_evidence={"project_exists": True, "project_id": "offline"},
    )


def heart_source_acceptance(text, geometry, objects):
    semantic = verify_semantic_requirements(text, [geometry], logical_objects=objects)
    final = verify_final_source_contract(text, [geometry], logical_objects=objects)
    return {"semantic_acceptance": semantic, "final_source_acceptance": final}


def bind_heart(text, geometry, objects):
    # Deliberately omit the semantic report so this exercises the binder's own
    # measured predicates; the production path also has the semantic claim.
    final = verify_final_source_contract(text, [geometry], logical_objects=objects)
    coverage = build_requirement_coverage_evidence(
        text, {"final_source_acceptance": final})
    return bind_construction_coverage(
        coverage, logical_objects=objects, geometries=[geometry],
        plan_steps=[{"step_id": "heart", "output_ref": objects[0]["object_id"]}],
        project_evidence={"project_exists": True, "project_id": "offline"},
    )


def clause_by_text(coverage, text):
    return next(item for item in coverage["clauses"] if item["requirement"] == text)


def test_coordinate_parentheses_are_not_split():
    assert split_source_clauses(A9_TEXT) == [
        "生成一个左右对称、平滑闭合的爱心",
        "中心在(2,3)",
        "宽4米高4米",
    ]


def test_c7_four_corner_circles_bind_from_measured_geometry():
    geoms, objects, steps = c7_scene()
    bound = bind_scene(C7_TEXT, geoms, objects, steps)
    assert bound["state"] == "complete"
    assert bound["unresolved_fact_ids"] == []
    rectangle_clause = clause_by_text(bound, "画一个矩形宽4米高2米")
    circles_clause = clause_by_text(bound, "在四个角各放一个半径0.5米的圆")
    assert rectangle_clause["status"] == "verified"
    assert circles_clause["status"] == "verified"
    assert circles_clause["binding"]["kind"] == "circle_collection"
    assert circles_clause["binding"]["measurement"]["status"] == "verified"
    assert circles_clause["binding"]["measurement"]["actual_count"] == 4
    assert len(circles_clause["binding"]["measurement"]["assignments"]) == 4


@pytest.mark.parametrize("failure", ["radius", "count_low", "count_high",
                                     "position", "rectangle_size"])
def test_c7_negative_variants_never_bind(failure):
    geoms, objects, steps = c7_scene()
    if failure == "radius":
        geoms[2]["radius"] = 300
    elif failure == "count_low":
        geoms.pop()
        objects.pop()
        steps.pop()
    elif failure == "count_high":
        geoms.append(circle(6, 2000, 1000, 500))
        objects.append(circle_object("circle_extra", 6, "多余圆"))
        steps.append({"step_id": "c5", "output_ref": "circle_extra"})
    elif failure == "position":
        geoms[2]["center"] = {"x": 0, "y": 0}
    elif failure == "rectangle_size":
        geoms[0] = rectangle(1, 0, 0, 4000, 3000)
    bound = bind_scene(C7_TEXT, geoms, objects, steps)
    assert bound["state"] == "partial"
    assert bound["unresolved_fact_ids"]
    target = ("画一个矩形宽4米高2米" if failure == "rectangle_size"
              else "在四个角各放一个半径0.5米的圆")
    assert clause_by_text(bound, target)["status"] != "verified"


def test_c7_only_rectangle_without_circles_does_not_satisfy_composite_requirement():
    geoms = [rectangle(1, 0, 0, 4000, 2000)]
    objects = [rectangle_object("rectangle_main", 1, "矩形 宽4米高2米")]
    bound = bind_scene(C7_TEXT, geoms, objects,
                       [{"step_id": "rect1", "output_ref": "rectangle_main"}])
    assert bound["state"] == "partial"
    assert clause_by_text(bound, "在四个角各放一个半径0.5米的圆")["status"] != "verified"


def test_multiple_same_kind_rectangles_remain_ambiguous():
    geoms = [rectangle(1, 0, 0, 4000, 2000), rectangle(2, 0, 4000, 4000, 2000)]
    objects = [rectangle_object("rectangle_main", 1, "矩形 宽4米高2米"),
               rectangle_object("rectangle_extra", 2, "另一个矩形")]
    bound = bind_scene(C7_TEXT, geoms, objects,
                       [{"step_id": "rect1", "output_ref": "rectangle_main"},
                        {"step_id": "rect2", "output_ref": "rectangle_extra"}])
    assert bound["state"] == "partial"
    assert clause_by_text(bound, "画一个矩形宽4米高2米")["status"] != "verified"


def test_a9_symmetric_smooth_closed_heart_is_fully_bound():
    geometry = heart()
    objects = [{"object_id": "heart_outline", "object_type": "drawing_part",
                "label": "爱心闭合外轮廓", "geometry_refs": [1]}]
    bound = bind_heart(A9_TEXT, geometry, objects)
    assert bound["state"] == "complete"
    assert bound["unresolved_fact_ids"] == []
    clause = clause_by_text(bound, "生成一个左右对称、平滑闭合的爱心")
    assert clause["status"] == "verified"
    checks = {item["predicate"]: item for item in clause["binding"]["measurement"]["checks"]}
    assert checks["heart_features"]["status"] == "verified"
    assert checks["mirror_symmetry"]["status"] == "verified"
    assert checks["closure"]["status"] == "verified"


def test_a9_open_outline_is_rejected():
    geometry = heart(closed=False)
    objects = [{"object_id": "heart_outline", "object_type": "drawing_part",
                "label": "爱心闭合外轮廓", "geometry_refs": [1]}]
    with pytest.raises(StructureContractError, match="爱心"):
        verify_semantic_requirements(A9_TEXT, [geometry], logical_objects=objects)


def test_a9_asymmetric_outline_is_rejected():
    geometry = heart()
    geometry["vertices"][10]["x"] += 200
    objects = [{"object_id": "heart_outline", "object_type": "drawing_part",
                "label": "爱心闭合外轮廓", "geometry_refs": [1]}]
    with pytest.raises(StructureContractError, match="对称"):
        verify_semantic_requirements(A9_TEXT, [geometry], logical_objects=objects)


def test_a9_center_offset_is_rejected_by_existing_final_source_verifier():
    geometry = heart(cx=2100)
    objects = [{"object_id": "heart_outline", "object_type": "drawing_part",
                "label": "爱心闭合外轮廓", "geometry_refs": [1]}]
    with pytest.raises(StructureContractError, match="最终几何"):
        verify_final_source_contract(A9_TEXT, [geometry], logical_objects=objects)


def test_closure_predicate_ignores_long_implicit_edge_but_not_false_flag():
    points = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert closure_measure(points, closed=True)["status"] == "verified"
    assert closure_measure(points, closed=False)["status"] == "failed"
    assert closure_measure(points, closed=False)["closure_status"] == "failed"


def test_closure_measures_smoothness_independently_of_closed_flag():
    points = [(0, 0), (10, 0), (10, 10), (0, 10)]
    result = closure_measure(points, closed=True, require_smooth=True)
    assert result["closure_status"] == "verified"
    assert result["continuity_status"] == "failed"
    assert result["status"] == "failed"
    assert result["unexpected_turn_count"] == 4
    assert result["max_turn_deg"] == pytest.approx(90.0)
    # Closure alone is not a smoothness claim.
    assert closure_measure(points, closed=True)["continuity_status"] == "not_required"


def test_closure_allows_only_source_backed_heart_cusps():
    geometry = heart()
    points = [(item["x"], item["y"]) for item in geometry["vertices"]]
    cusps = heart_cusp_points(geometry)
    allowed = closure_measure(
        points, closed=True, require_smooth=True,
        allowed_cusp_source="heart_features", allowed_cusp_limit=2,
        allowed_cusp_points=cusps,
    )
    assert len(cusps) == 2
    assert allowed["status"] == "verified"
    assert len(allowed["intentional_cusps"]) == 2
    assert allowed["cusp_source"] == "heart_features"
    # A source label alone is not evidence, and neither is a centre-line filter.
    unsourced = closure_measure(
        points, closed=True, require_smooth=True,
        allowed_cusp_source="heart_features", allowed_cusp_limit=2,
    )
    assert unsourced["status"] == "failed"
    assert unsourced["intentional_cusps"] == []
    wrong_points = closure_measure(
        points, closed=True, require_smooth=True,
        allowed_cusp_source="heart_features", allowed_cusp_limit=2,
        allowed_cusp_points=[(0.0, 0.0), (1.0, 1.0)],
    )
    assert wrong_points["status"] == "failed"
    assert wrong_points["intentional_cusps"] == []


def test_mirror_symmetry_rejects_symmetric_vertices_with_asymmetric_edges():
    points = [(0, 0), (10, 0), (10, 10), (0, 10), (5, 5)]
    assert mirror_symmetry(points, 5.0, tolerance_mm=0.1)["status"] == "failed"
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert mirror_symmetry(square, 5.0, tolerance_mm=0.1)["status"] == "verified"


@pytest.mark.parametrize("text", [
    "生成一个对称的爱心，中心在(2,3)，宽4米高4米",
    "生成一个上下对称的爱心，中心在(2,3)，宽4米高4米",
    "生成一个旋转对称的爱心，中心在(2,3)，宽4米高4米",
])
def test_ambiguous_or_unsupported_symmetry_stays_unverified(text):
    geometry = heart()
    objects = [{"object_id": "heart_outline", "object_type": "drawing_part",
                "label": "爱心闭合外轮廓", "geometry_refs": [1]}]
    bound = bind_heart(text, geometry, objects)
    assert bound["state"] == "partial"
    assert bound["unresolved_fact_ids"]
    clause = bound["clauses"][0]
    assert clause["status"] != "verified"


def test_mirror_symmetry_does_not_invent_a_closing_edge_for_open_outline():
    """An open half-outline must not pass by borrowing an unowned closing edge."""
    points = [(0, 10), (5, 0), (0, -10), (-5, 0)]
    closed = mirror_symmetry(points, 0.0, tolerance_mm=0.1, closed=True)
    open_outline = mirror_symmetry(points, 0.0, tolerance_mm=0.1, closed=False)
    assert closed["status"] == "verified"
    assert closed["segment_count"] == 4
    assert open_outline["status"] == "failed"
    assert open_outline["segment_count"] == 3
    assert open_outline["closed"] is False


def test_mirror_symmetry_measures_hausdorff_not_bbox():
    points = [(0, 0), (100, 0), (100, 100), (0, 100)]
    result = mirror_symmetry(points, 50.0, tolerance_mm=0.5)
    assert result["status"] == "verified"
    assert result["max_error_mm"] <= 0.5
    offset = [(x + 20, y) for x, y in points]
    assert mirror_symmetry(offset, 70.0, tolerance_mm=0.5)["status"] == "verified"
    assert mirror_symmetry(offset, 50.0, tolerance_mm=0.5)["status"] == "failed"


def test_closure_rejects_sharp_join_away_from_vertical_centre():
    points = [(0, 0), (100, 0), (100, 100), (60, 100), (60, 150),
              (60, 100), (0, 100)]
    result = closure_measure(points, closed=True, require_smooth=True)
    assert result["status"] == "failed"
    assert result["unexpected_sharp_join_count"] == 1
    assert result["intentional_cusps"] == []


def test_corner_collection_rejects_duplicate_corner_assignment():
    rect = rectangle(1, 0, 0, 4000, 2000)
    circles = [circle(2, -2000, 1000, 500), circle(3, -2000, 1000, 500),
               circle(4, -2000, -1000, 500), circle(5, 2000, -1000, 500)]
    result = corner_circle_collection(rect, circles, expected_count=4,
                                      expected_radius_mm=500)
    assert result["status"] == "failed"
    assert result["unmatched_circles"]


def test_failed_final_source_check_cannot_be_masked_by_another_passed_claim():
    """A passed check from another report must not outvote a failed final check."""
    failed_final = {
        "name": "width", "field": "width", "status": "failed",
        "actual_mm": 2000.0, "expected_mm": 3000.0, "tolerance_mm": 0.5,
        "source_requirement_id": "synthetic:width",
        "source_evidence": {"text": "宽3米"},
    }
    passed_other = {
        "name": "width", "field": "width", "status": "passed",
        "source_evidence": {"text": "宽3米"},
    }
    coverage = build_requirement_coverage_evidence("宽3米", {
        "status": "partial", "checks": [],
        "final_source_acceptance": {
            "status": "passed", "checks": [failed_final],
            "unknown_requirements": [],
        },
        "source_requirement_acceptance": {
            "status": "passed", "checks": [passed_other],
        },
    })
    clause = coverage["clauses"][0]
    assert clause["requirement"] == "宽3米"
    assert clause["status"] != "verified"
    assert coverage["state"] == "partial"
    assert coverage["blocking_requirements"]


def test_composite_requirement_keeps_corner_failure_after_rectangle_promotion():
    """A passed rectangle binding must not clear a failed corner-radius fact."""
    text = "绘制一个矩形，四角各有一个半径500毫米的圆角"
    geoms, objects, steps = c7_scene()
    for geometry in geoms[1:]:
        geometry["radius"] = 400.0
    failed_corner = {
        "name": "corner_radius", "field": "corner_radius", "status": "failed",
        "actual_mm": 400.0, "expected_mm": 500.0, "tolerance_mm": 0.5,
        "source_requirement_id": "corner_radius",
        "source_evidence": {"text": "四角各有一个半径500毫米的圆角"},
    }
    coverage = build_requirement_coverage_evidence(text, {
        "final_source_acceptance": {
            "status": "partial", "checks": [failed_corner],
            "unknown_requirements": [],
        },
    })
    bound = bind_construction_coverage(
        coverage, logical_objects=objects, geometries=geoms,
        plan_steps=steps,
        project_evidence={"project_exists": True, "project_id": "offline"},
    )
    rectangle_clause = clause_by_text(bound, "绘制一个矩形")
    corner_clause = clause_by_text(bound, "四角各有一个半径500毫米的圆角")
    assert rectangle_clause["status"] == "verified"
    assert corner_clause["status"] == "partial"
    assert corner_clause["binding_failures"]
    assert bound["state"] == "partial"
    assert bound["blocking_requirements"]


def test_binder_does_not_clear_failed_final_fact_from_unrelated_passed_claim():
    """The direct binder must keep a failed final fact blocking."""
    failed_final = {
        "name": "width", "field": "width", "status": "failed",
        "actual_mm": 2000.0, "expected_mm": 3000.0, "tolerance_mm": 0.5,
        "source_requirement_id": "synthetic:width",
        "source_evidence": {"text": "宽3米"},
    }
    passed_other = {
        "name": "width", "field": "width", "status": "passed",
        "source_evidence": {"text": "宽3米"},
    }
    coverage = build_requirement_coverage_evidence("宽3米", {
        "status": "partial", "checks": [],
        "final_source_acceptance": {
            "status": "passed", "checks": [failed_final],
            "unknown_requirements": [],
        },
        "source_requirement_acceptance": {
            "status": "passed", "checks": [passed_other],
        },
    })
    bound = bind_construction_coverage(
        coverage,
        logical_objects=[rectangle_object("rectangle_main", 1, "矩形 宽3米")],
        geometries=[rectangle(1, 0, 0, 2000, 2000)],
        plan_steps=[{"step_id": "rect1", "output_ref": "rectangle_main"}],
        project_evidence={"project_exists": True, "project_id": "offline"},
    )
    assert bound["state"] == "partial"
    assert bound["blocking_requirements"]
    assert clause_by_text(bound, "宽3米")["status"] != "verified"
