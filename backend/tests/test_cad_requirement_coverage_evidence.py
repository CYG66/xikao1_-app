from copy import deepcopy

from app.cad_source_acceptance import build_requirement_coverage_evidence


def _final_width_check(source_id, text, start, end, actual_mm=1948.4269441632714,
                       expected_mm=3000.0):
    return {
        "field": "width", "actual_mm": actual_mm, "expected_mm": expected_mm,
        "operator": "lte", "tolerance_mm": 0.5,
        "source_requirement_id": source_id,
        "source_evidence": {"start": start, "end": end, "text": text},
        "status": "passed", "geometry_ids": [1],
    }


def _cardioid_report():
    return {
        "status": "passed",
        "coverage": "cardioid_shape_and_declared_direction",
        "checks": [{
            "name": "cardioid_polar_identity", "status": "passed",
            "measurements": {
                "max_relative_radial_residual": 1.04e-05,
                "tolerance_relative_to_extent": 0.005,
                "cusp_pointing_unit_vector": [2.7e-09, -1.0],
                "cusp_mm": [-5.4e-06, -0.000722],
            },
        }],
        "review_required": False,
        "applicable_requirement_kinds": ["cardioid_identity"],
    }


def _path_report():
    return {
        "status": "passed",
        "coverage": "explicit_perpendicular_arm_extents_and_width",
        "checks": [{
            "name": "perpendicular_arm_dimensions", "status": "passed",
            "geometry_ids": [1], "required_arm_extents_m": [3.0, 2.0],
            "required_width_m": 1.0,
            "expected_boundary_lengths_m": [1.0, 1.0, 1.0, 2.0, 2.0, 3.0],
            "actual_boundary_lengths_m": [1.0, 1.0, 1.0, 2.0, 2.0, 3.0],
            "orthogonal": True, "polygon_count": 1,
            "authority": "backend_measured_geometry",
        }],
    }


def _path_source_acceptance():
    return {
        "status": "not_checked", "coverage": "partial", "checks": [],
        "final_source_acceptance": {"status": "not_checked", "coverage": "partial",
                                    "checks": [], "unknown_requirements": []},
        "semantic_acceptance": {"status": "not_checked", "coverage": "partial",
                                "checks": [], "review_required": True,
                                "applicable_requirement_kinds": []},
        "path_relation_acceptance": _path_report(),
    }


def test_circular_corridor_is_not_verified_by_l_shaped_path_measurements():
    """L-path dimensions must not stand in for an explicitly circular corridor."""
    coverage = build_requirement_coverage_evidence(
        "画一个圆形走廊，宽1米，两条臂分别长3米和2米，直角连接",
        _path_source_acceptance())
    assert coverage["state"] == "partial"
    clauses = {item["requirement"]: item for item in coverage["clauses"]}
    assert clauses["画一个圆形走廊"]["status"] == "unverified"
    assert clauses["宽1米"]["status"] == "verified"
    assert clauses["两条臂分别长3米和2米"]["status"] == "verified"
    assert coverage["blocking_requirements"][0]["requirement"] == "画一个圆形走廊"


def test_attached_door_cannot_inherit_verified_l_path_clause():
    """An attached door is a separate requirement even without a comma."""
    coverage = build_requirement_coverage_evidence(
        "画一个L形走廊，宽1米，两条臂分别长3米和2米，直角连接并在墙上加一扇门",
        _path_source_acceptance())
    assert coverage["state"] == "partial"
    clauses = {item["requirement"]: item for item in coverage["clauses"]}
    assert clauses["直角连接"]["status"] == "verified"
    assert clauses["并在墙上加一扇门"]["status"] == "unverified"
    assert coverage["verified_requirement_count"] == 4
    assert coverage["blocking_requirements"][0]["requirement"] == "并在墙上加一扇门"


def test_cardioid_each_source_clause_is_bound_to_backend_measurement():
    source = "生成一个心形线（cardioid），尖点朝下，最大宽度3米"
    coverage = build_requirement_coverage_evidence(source, {
        "status": "partial", "coverage": "partial", "checks": [],
        "final_source_acceptance": {
            "status": "partial", "coverage": "partial",
            "checks": [_final_width_check(
                "user:0:scalar-1:width:心形线", "最大宽度3米", 23, 29)],
            "unknown_requirements": [], "review_required": False,
        },
        "semantic_acceptance": _cardioid_report(),
    })
    assert coverage["state"] == "complete"
    assert coverage["verified_requirement_count"] == 3
    clauses = {item["requirement"]: item for item in coverage["clauses"]}
    assert clauses["生成一个心形线（cardioid）"]["status"] == "verified"
    assert clauses["尖点朝下"]["status"] == "verified"
    assert clauses["最大宽度3米"]["status"] == "verified"
    assert all(item["authority"] == "backend_measured_geometry"
               for item in coverage["clauses"])
    assert any(e["verifier"] == "verify_final_source_contract"
               for e in clauses["最大宽度3米"]["evidence"])


def test_cardioid_semantic_partial_never_promotes_shape_or_direction():
    report = _cardioid_report()
    report["status"] = "partial"
    coverage = build_requirement_coverage_evidence(
        "生成一个心形线（cardioid），尖点朝下，最大宽度3米",
        {"status": "partial", "coverage": "partial", "checks": [],
         "final_source_acceptance": {"status": "partial", "coverage": "partial",
                                     "checks": [], "unknown_requirements": []},
         "semantic_acceptance": report})
    assert coverage["state"] == "partial"
    clauses = {item["requirement"]: item for item in coverage["clauses"]}
    assert clauses["生成一个心形线（cardioid）"]["status"] == "partial"
    assert clauses["尖点朝下"]["status"] == "partial"
    assert coverage["blocking_requirements"]


def test_path_measurement_closes_all_four_clauses_without_new_rule():
    source = "画一个L形走廊，宽1米，两条臂分别长3米和2米，直角连接"
    check = {
        "name": "perpendicular_arm_dimensions", "status": "passed",
        "geometry_ids": [1], "required_arm_extents_m": [3.0, 2.0],
        "required_width_m": 1.0,
        "expected_boundary_lengths_m": [1.0, 1.0, 1.0, 2.0, 2.0, 3.0],
        "actual_boundary_lengths_m": [1.0, 1.0, 1.0, 2.0, 2.0, 3.0],
        "orthogonal": True, "polygon_count": 1,
        "authority": "backend_measured_geometry",
    }
    coverage = build_requirement_coverage_evidence(source, {
        "status": "not_checked", "coverage": "partial", "checks": [],
        "final_source_acceptance": {"status": "not_checked", "coverage": "partial",
                                    "checks": [], "unknown_requirements": []},
        "semantic_acceptance": {"status": "not_checked", "coverage": "partial",
                                "checks": [], "review_required": True,
                                "applicable_requirement_kinds": []},
        "path_relation_acceptance": {
            "status": "passed",
            "coverage": "explicit_perpendicular_arm_extents_and_width",
            "checks": [check],
        },
    })
    assert coverage["state"] == "complete"
    assert coverage["verified_requirement_count"] == 4
    width = next(item for item in coverage["clauses"] if item["requirement"] == "宽1米")
    assert len(width["evidence"]) == 1
    assert width["evidence"][0]["measurement"]["actual_mm"] == 1000.0


def test_unresolved_dimensions_remain_unbound_negative_protection():
    source = "画一个矩形宽4米高2米，在四个角各放一个半径0.5米的圆"
    coverage = build_requirement_coverage_evidence(source, {
        "status": "not_checked", "coverage": "partial", "checks": [],
        "final_source_acceptance": {"status": "not_checked", "coverage": "partial",
                                    "checks": [], "unknown_requirements": []},
        "semantic_acceptance": {"status": "not_checked", "coverage": "partial",
                                "checks": [], "review_required": True,
                                "applicable_requirement_kinds": []},
    })
    assert coverage["state"] == "partial"
    assert coverage["verified_requirement_count"] == 0
    assert {item["status"] for item in coverage["clauses"]} == {"unbound"}
    assert all(item["reason"] == "无法唯一绑定验证对象"
               for item in coverage["blocking_requirements"])


def test_semantic_partial_with_all_checks_passed_stays_blocking():
    source = "生成一个房子轮廓，宽4米高3米，屋顶是三角形，下面加一个门"
    semantic = {
        "status": "partial",
        "coverage": "triangle_roof_house_structural_relations_only",
        "requirements": [{
            "kind": "triangle_roof_house",
            "source_evidence": ["房子轮廓", "屋顶是三角", "门"],
        }],
        "checks": [
            {"name": "墙体与三角屋顶", "status": "passed"},
            {"name": "门位置", "status": "passed"},
        ],
        "review_required": False,
        "applicable_requirement_kinds": ["triangle_roof_house"],
    }
    coverage = build_requirement_coverage_evidence(source, {
        "status": "partial", "coverage": "partial", "checks": [],
        "final_source_acceptance": {"status": "not_checked", "coverage": "partial",
                                    "checks": [], "unknown_requirements": []},
        "semantic_acceptance": semantic,
    })
    assert coverage["state"] == "partial"
    clauses = {item["requirement"]: item for item in coverage["clauses"]}
    assert clauses["屋顶是三角形"]["status"] == "partial"
    assert clauses["下面加一个门"]["status"] == "partial"
    assert any(item["reason"] == "semantic_report_status_partial"
               for item in coverage["blocking_requirements"])


def test_unknown_requirement_is_preserved_not_silently_completed():
    source = "生成一个齿轮轮廓，外径2米，8个齿"
    coverage = build_requirement_coverage_evidence(source, {
        "status": "not_checked", "coverage": "partial", "checks": [],
        "final_source_acceptance": {
            "status": "not_checked", "coverage": "partial", "checks": [],
            "unknown_requirements": [{
                "source_requirement_id": "user:0:scalar-1:diameter:齿轮轮廓",
                "reason": "当前测量器不支持此要求",
            }],
            "review_required": True,
        },
        "semantic_acceptance": {"status": "not_checked", "coverage": "partial",
                                "checks": [], "review_required": True,
                                "applicable_requirement_kinds": []},
    })
    assert coverage["state"] == "partial"
    assert any("当前测量器不支持此要求" == item["reason"]
               for item in coverage["blocking_requirements"])
    diameter = next(item for item in coverage["clauses"]
                    if item["requirement"] == "外径2米")
    assert diameter["status"] == "unverified"
    assert diameter["authority"] == "backend_measured_geometry"


def test_complete_scope_evidence_is_reused_without_new_authority():
    coverage = build_requirement_coverage_evidence("完整部件清单：\n外圆：圆，圆心(0,0)，半径1米，坐标单位米", {
        "status": "passed", "coverage": "complete", "checks": [{
            "status": "passed", "authority": "backend_measured_geometry",
            "source_requirement": {"subject": "外圆", "evidence": "外圆：圆，圆心(0,0)，半径1米，坐标单位米"},
        }],
        "scope_evidence": {
            "state": "complete",
            "entries": [{
                "requirement_id": "source-scope:外圆",
                "evidence": "外圆：圆，圆心(0,0)，半径1米，坐标单位米",
                "measurement": {"kind": "圆", "center": [0, 0], "radius": 1000},
            }],
        },
    })
    assert coverage["state"] == "complete"
    assert coverage["verified_requirement_count"] == 1
    assert coverage["clauses"][0]["verifier"] == "verify_scoped_primitives"
    assert coverage["clauses"][0]["authority"] == "backend_measured_geometry"
