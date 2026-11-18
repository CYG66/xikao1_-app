"""Round 8 P0 caller-side wiring regression (Agent C).

Zero real model calls. These tests exercise the production caller wrappers in
``cad_construction_interpreter`` against executor-produced results and the real
candidate gate predicates. They do not extend geometry algorithms, do not add a
star-specific verifier, and do not change H2/H3/H4 gates, ``max_repairs`` or
candidate-save authorization.
"""

import math

from app.cad_construction import execute_construction_plan
from app.cad_construction_interpreter import (
    _semantic_backend_binding,
    _verify_semantic_requirements_bound,
    construction_acceptance_summary,
)
from app.cad_candidate_state import candidate_is_accepted, candidate_is_reviewable_draft
from app.cad_semantic_dispatch import bind_targets

HEART_TEXT = "生成一个闭合爱心轮廓，宽度4米，高度4米"
HEART_RECON_TEXT = "生成一个左右对称、平滑闭合的爱心，宽4米高4米"
C10_TEXT = "生成一个爱心和一个五角星，爱心在左，五角星在右"
LETTER_TEXT = "生成一个大写字母A的轮廓，高3米宽2米"
HOUSE_TEXT = "生成一个房子轮廓，宽4米高3米，屋顶是三角形，下面加一个门"


def _poly(i, points):
    return {"id": i, "type": "polyline", "closed": True,
            "vertices": [{"x": x, "y": y} for x, y in points]}


def _step(step_id, ref, label, points, closed=True):
    return {"op": "add_polyline", "step_id": step_id, "output_ref": ref,
            "semantic": {"label": label}, "closed": closed,
            "vertices": [{"x": x, "y": y} for x, y in points]}


def _heart(scale=2000):
    norm = [(0.20, 0.90), (0.50, 0.62), (0.80, 0.90), (0.95, 0.50),
            (0.75, 0.20), (0.50, 0.00), (0.25, 0.20), (0.05, 0.50)]
    return [(round(x * scale, 3), round(y * scale, 3)) for x, y in norm]


def _star(ox=3000, cy=1000, ro=1000, ri=400):
    points = []
    for k in range(10):
        r = ro if k % 2 == 0 else ri
        ang = math.pi / 2 + k * math.pi / 5
        points.append((round(r * math.cos(ang) + ox, 3),
                       round(r * math.sin(ang) + cy, 3)))
    return points


def _letter_outer():
    return [(0, 0), (850, 3000), (1150, 3000), (2000, 0), (1550, 0),
            (1350, 750), (650, 750), (450, 0)]


def _letter_triangle():
    return [(800, 1400), (1200, 1400), (1000, 2400)]


def _house_outer():
    return [(0, 0), (4000, 0), (4000, 2000), (2000, 3000), (0, 2000)]


def _house_door():
    return [(1500, 0), (2500, 0), (2500, 1500), (1500, 1500)]


def _exec(steps):
    return execute_construction_plan({"units": "mm", "steps": steps})


def test_A1_single_heart_uses_backend_binding_and_heart_channel():
    result = _exec([_step("h", "heart", "爱心", _heart(4000))])
    proof = _verify_semantic_requirements_bound(HEART_TEXT, result)
    assert proof["binding"]["binding_trust"] == "trusted"
    assert proof["binding"]["model_declared_object_id_trusted"] is False
    assert proof["status"] == "partial"
    assert proof["review_required"] is True
    targets = proof["object_acceptance"]
    assert [t["target_ref"]["geometry_ids"] for t in targets] == [[1]]
    assert targets[0]["status"] == "passed"


def test_A9_reconstructed_single_heart_fixture_is_not_history_replay():
    # Reconstructed fixture (built locally in this module), explicitly not a
    # historical replay record. Single heart must still take the heart channel.
    result = _exec([_step("h", "heart", "爱心", _heart(2000))])
    proof = _verify_semantic_requirements_bound(HEART_RECON_TEXT, result)
    assert proof["binding"]["binding_trust"] == "trusted"
    assert proof["object_acceptance"][0]["status"] == "passed"
    assert proof["review_required"] is True


def test_C10_heart_passed_star_not_checked_overall_partial_review():
    result = _exec([
        _step("h", "heart", "爱心", _heart(2000)),
        _step("s", "star", "五角星", _star()),
    ])
    proof = _verify_semantic_requirements_bound(C10_TEXT, result)
    assert proof["binding"]["binding_trust"] == "trusted"
    by_ids = {tuple(t["target_ref"]["geometry_ids"]): t for t in proof["object_acceptance"]}
    assert by_ids[(1,)]["status"] == "passed"
    assert by_ids[(2,)]["status"] == "not_checked"
    assert proof["status"] == "partial"
    assert proof["review_required"] is True
    assert proof["unsupported_objects"] == [[2]]


def test_C26_letter_a_inherited_partial_does_not_pass_gate_through_summary():
    result = _exec([
        _step("o", "outer", "字母A外轮廓", _letter_outer()),
        _step("t", "tri", "三角区域", _letter_triangle()),
    ])
    proof = _verify_semantic_requirements_bound(LETTER_TEXT, result)
    # Inherited 423E behavior: letter channel partial with review_required=False.
    assert proof["status"] == "partial"
    assert proof["review_required"] is False
    assert proof["coverage"] == "straight_capital_a_structural_relations_only"

    summary = construction_acceptance_summary(
        preflight_structure=None, structure_contract=None, structure_validation=None,
        composition_contract=None, composition_validation=None,
        source_acceptance={"coverage": "partial", "unknown_requirements": [],
                           "semantic_acceptance": proof, "checks": []},
    )
    assert summary["review_required"] is True
    assert candidate_is_accepted({"acceptance_summary": summary}) is False


def test_unknown_kind_is_not_silently_accepted():
    result = _exec([_step("v", "vase", "花瓶", _heart(1000))])
    proof = _verify_semantic_requirements_bound("画一个花瓶", result)
    assert proof["status"] == "not_checked"
    assert proof["review_required"] is True
    assert not proof.get("object_acceptance") or all(
        t["status"] != "passed" for t in proof["object_acceptance"])


def test_missing_logical_objects_degraded_never_passes():
    geometry = _poly(1, [(-1500, -1500), (1500, -1500), (1500, 1500), (-1500, 1500)])
    proof = _verify_semantic_requirements_bound(
        "画一个嵌套正方形，外框边长3米，内框边长2米，内框居中",
        {"geometries": [geometry]})
    assert proof["binding"]["binding_trust"] == "degraded"
    assert proof["review_required"] is True
    assert proof["status"] != "passed"


def test_wrong_geometry_ref_is_degraded():
    geometry = _poly(1, [(0, 0), (1000, 0), (1000, 1000), (0, 1000)])
    binding = _semantic_backend_binding({
        "geometries": [geometry],
        "logical_objects": [{"object_id": "x", "geometry_refs": [999]}],
    })
    assert binding["trust"] == "degraded"
    assert any(i["code"] == "dangling_geometry_refs" for i in binding["issues"])


def test_duplicate_geometry_ref_is_degraded():
    geometry = _poly(1, [(0, 0), (1000, 0), (1000, 1000), (0, 1000)])
    binding = _semantic_backend_binding({
        "geometries": [geometry],
        "logical_objects": [{"object_id": "x", "geometry_refs": [1, 1]}],
    })
    assert binding["trust"] == "degraded"


def test_stale_geometry_ref_is_degraded():
    geometry = _poly(1, [(0, 0), (1000, 0), (1000, 1000), (0, 1000)])
    binding = _semantic_backend_binding({
        "geometries": [geometry],
        "logical_objects": [{"object_id": "x", "geometry_refs": [1, 2]}],
    })
    assert binding["trust"] == "degraded"
    assert any(i["code"] == "dangling_geometry_refs" for i in binding["issues"])


def test_model_declared_id_without_refs_is_not_trusted():
    geometry = _poly(1, [(0, 0), (1000, 0), (1000, 1000), (0, 1000)])
    binding = _semantic_backend_binding({
        "geometries": [geometry],
        "logical_objects": [{"object_id": "model-claimed", "label": "爱心"}],
    })
    assert binding["trust"] == "degraded"
    assert any(i["code"] == "missing_geometry_refs" for i in binding["issues"])


def test_overlapping_objects_keep_separate_targets():
    g1 = _poly(1, [(0, 0), (1500, 0), (1500, 1000), (0, 1000)])
    g2 = _poly(2, [(500, 0), (2000, 0), (2000, 1000), (500, 1000)])
    binding = _semantic_backend_binding({
        "geometries": [g1, g2],
        "logical_objects": [{"object_id": "a", "geometry_refs": [1]},
                            {"object_id": "b", "geometry_refs": [2]}],
        "topology": {"schema_version": "cad.topology.v1", "shared_geometries": [], "relations": []},
    })
    targets = bind_targets([g1, g2], binding["logical_objects"], binding["topology"])
    assert [t["target_ref"]["geometry_ids"] for t in targets] == [[1], [2]]


def test_one_object_with_disconnected_segments_is_not_split():
    g1 = _poly(1, [(0, 0), (1000, 0), (1000, 1000), (0, 1000)])
    g3 = _poly(3, [(3000, 0), (4000, 0), (4000, 1000), (3000, 1000)])
    binding = _semantic_backend_binding({
        "geometries": [g1, g3],
        "logical_objects": [{"object_id": "one", "geometry_refs": [1, 3]}],
        "topology": {"schema_version": "cad.topology.v1", "shared_geometries": [], "relations": []},
    })
    targets = bind_targets([g1, g3], binding["logical_objects"], binding["topology"])
    assert [t["target_ref"]["geometry_ids"] for t in targets] == [[1, 3]]


def test_unowned_active_geometry_marks_membership_incomplete():
    g1 = _poly(1, [(0, 0), (1000, 0), (1000, 1000), (0, 1000)])
    g2 = _poly(2, [(1000, 0), (2000, 0), (2000, 1000), (1000, 1000)])
    binding = _semantic_backend_binding({
        "geometries": [g1, g2],
        "logical_objects": [{"object_id": "x", "geometry_refs": [1]}],
    })
    assert binding["trust"] == "degraded"
    assert any(i["code"] == "incomplete_membership" for i in binding["issues"])


def test_house_entry_summary_keeps_review_required_and_not_accepted():
    from app.cad_construction_interpreter import interpret_construction_request

    def callback(text, schema):
        return {"schema_version": "cad.construction-interpretation.v1",
                "is_construction_request": True, "confidence": 0.99,
                "evidence_text": [HOUSE_TEXT], "assumptions": [],
                "plan": {"units": "mm", "steps": [
                    _step("o", "outer", "房子外轮廓", _house_outer()),
                    _step("d", "door", "门", _house_door())]}}

    result = interpret_construction_request(HOUSE_TEXT, callback, force_structured_model=True)
    assert result["status"] == "ready"
    semantic = result["source_acceptance"]["semantic_acceptance"]
    assert semantic["status"] == "partial"
    assert semantic["review_required"] is False  # inherited 423E
    summary = result["acceptance_summary"]
    assert summary["review_required"] is True
    assert candidate_is_accepted({"acceptance_summary": summary}) is False


def test_gate_residual_condition_partial_review_false_with_complete_coverage_is_closed_by_g1_guard():
    # Round8 recorded this as a latent defect: the summary's generic report
    # filter did not list ``partial`` as a reviewable status, so a
    # coverage=complete / no-unknown source with a partial/review_required=False
    # semantic report would have been accepted. The Round9 G1 guard delegates the
    # semantic report to A's three-state verdict, under which ``partial`` is
    # always ``unverified_or_partial`` regardless of the review_required flag.
    partial_false = {"status": "partial", "review_required": False,
                     "coverage": "straight_capital_a_structural_relations_only",
                     "checks": [{"status": "passed"}]}
    summary = construction_acceptance_summary(
        preflight_structure=None, structure_contract=None, structure_validation=None,
        composition_contract=None, composition_validation=None,
        source_acceptance={"coverage": "complete", "unknown_requirements": [],
                           "semantic_acceptance": partial_false, "checks": []},
    )
    assert summary["status"] == "review_required"
    assert summary["review_required"] is True
    assert summary["semantic_requirement_state"] == "unverified_or_partial"
    assert "partial_overall" in summary["semantic_incomplete_reasons"]
    assert candidate_is_accepted({"acceptance_summary": summary}) is False
    assert candidate_is_reviewable_draft({"acceptance_summary": summary}) is False
