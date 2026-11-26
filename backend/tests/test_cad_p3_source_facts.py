"""R04 source-fact binding tests: local nouns, counts, and C6 non-injection."""
from __future__ import annotations

from app.cad_requirement_contract import requirement_contract
from app.cad_residual_repair import collect_source_acceptance_residuals
from app.cad_source_acceptance import (
    build_requirement_coverage_evidence,
    verify_final_source_contract,
)

C31 = "生成一个太极图，外圆半径2米，S形分割线，两个对称小圆"
C6 = "画一朵花的轮廓，5片花瓣，闭合曲线\n宽度5米，高度5米。"


def _c31_geometry():
    geoms = [
        {"id": 1, "type": "circle", "radius": 2000.0,
         "center": {"x": 0.0, "y": 0.0}, "selected": True},
        {"id": 4, "type": "circle", "radius": 250.0,
         "center": {"x": 0.0, "y": 1000.0}, "selected": True},
        {"id": 5, "type": "circle", "radius": 250.0,
         "center": {"x": 0.0, "y": -1000.0}, "selected": True},
    ]
    objects = [
        {"label": "太极图外圆", "geometry_refs": [1]},
        {"label": "上方对称小圆", "geometry_refs": [4]},
        {"label": "下方对称小圆", "geometry_refs": [5]},
    ]
    return geoms, objects


def test_local_subject_binds_outer_circle_radius_instead_of_leaving_unknown():
    contract = requirement_contract([{"source_id": "user:0", "text": C31}])
    radius = [f for f in contract["facts"] if f["field"] == "radius"][0]
    assert radius["binding"] == "local_subject_pending"
    assert radius["local_subject"] == "外圆"
    geoms, objects = _c31_geometry()
    result = verify_final_source_contract(C31, geoms, objects)
    assert result["unknown_requirements"] == []
    assert result["review_required"] is False
    radius_check = [c for c in result["checks"] if c["field"] == "radius"][0]
    assert radius_check["status"] == "passed"
    assert radius_check["actual_mm"] == 2000.0


def test_local_subject_final_measurement_closes_the_coverage_clause():
    geoms, objects = _c31_geometry()
    final = verify_final_source_contract(C31, geoms, objects)
    coverage = build_requirement_coverage_evidence(
        C31, {"final_source_acceptance": final})
    radius_clause = next(c for c in coverage["clauses"]
                         if c["requirement"] == "外圆半径2米")
    assert radius_clause["status"] == "verified"
    assert "user:0:scalar-1:radius:外圆" not in radius_clause.get(
        "unsupported_evidence", [])


def test_two_small_circles_source_count_is_measured_but_grade_expected_is_not_injected():
    geoms, objects = _c31_geometry()
    result = verify_final_source_contract(C31, geoms, objects)
    count = [c for c in result["checks"] if c["field"] == "object_count"][0]
    assert count["expected_count"] == 2
    assert count["actual_count"] == 2
    assert count["status"] == "passed"
    # There is no source text for a 500mm eye radius, cubic Bezier divider or
    # four-entity object count; these remain absent rather than being copied
    # from the frozen harness.
    assert not [c for c in result["checks"] if c.get("field") == "curve_type"]
    assert len([c for c in result["checks"] if c["field"] == "radius"]) == 1


def test_c6_harness_center_and_turn_metrics_do_not_enter_source_contract():
    contract = requirement_contract([{"source_id": "user:0", "text": C6}])
    assert {f["field"] for f in contract["facts"]} == {"width", "height"}
    assert not [f for f in contract["facts"] if f["field"] in {"center", "max_turn"}]


def test_source_count_failure_becomes_a_discrete_production_residual():
    acceptance = {"checks": [{
        "status": "failed", "source_requirement_id": "user:0:count:21",
        "field": "object_count", "expected_count": 2, "actual_count": 3,
        "object_noun": "小圆",
    }]}
    records = collect_source_acceptance_residuals(acceptance, {"steps": []})
    assert len(records) == 1
    assert records[0]["residual_type"] == "discrete"
    assert records[0]["expected"] == 2
    assert records[0]["measured"] == 3
    assert records[0]["mandatory"] is True
