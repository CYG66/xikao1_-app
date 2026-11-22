"""Round9 G1b sub-report acceptable-status gate regression (Agent C).

Zero real model calls. The summary layer now applies one shared blocking
status set to every generic ``*_acceptance`` report: a ``partial`` sub-report
can no longer be promoted to a complete pass when it omits ``review_required``.
The semantic report still delegates exclusively to A's three-state verdict;
``not_checked`` is not added to the blocking set.
"""

import math

from app.cad_construction import execute_construction_plan
from app.cad_construction_interpreter import (
    _verify_semantic_requirements_bound,
    construction_acceptance_summary,
)
from app.cad_candidate_state import candidate_is_accepted

VASE_TEXT = "画一个花瓶"
POLYGON_TEXT = "生成一个正五边形，外接圆半径2米"
HEART_TEXT = "生成一个闭合爱心轮廓，宽度4米，高度4米"
STAR_TEXT = "生成一个五角星，外接圆半径2米"
C10_TEXT = "生成一个爱心和一个五角星，爱心在左，五角星在右"

NON_SEMANTIC_REPORTS = [
    "stroke_acceptance",
    "path_relation_acceptance",
    "repetition_acceptance",
    "projection_acceptance",
]


def _summary(source_acceptance, source=None):
    return construction_acceptance_summary(
        preflight_structure=None, structure_contract=None, structure_validation=None,
        composition_contract=None, composition_validation=None,
        source_acceptance=source_acceptance, source=source)


def _base_source(extra=None, coverage="complete"):
    source = {"coverage": coverage, "unknown_requirements": [],
              "checks": [{"status": "passed", "field": "primitive_dimension"}]}
    if extra:
        source.update(extra)
    return source


# --- G1b negatives: partial non-semantic report must not be promoted -------

def test_partial_non_semantic_report_review_false_is_not_accepted():
    for report_key in NON_SEMANTIC_REPORTS:
        report = {"status": "partial", "review_required": False,
                  "coverage": "explicit_channel_only", "checks": []}
        summary = _summary(_base_source({report_key: report}), source=VASE_TEXT)
        assert summary["review_required"] is True, report_key
        assert summary["status"] == "review_required", report_key
        assert candidate_is_accepted({"acceptance_summary": summary}) is False, report_key


# --- Positives stay open: no applicable requirement / verified branch -------

def test_R4_no_semantic_report_still_passes():
    summary = _summary(_base_source(), source=VASE_TEXT)
    assert summary["status"] == "passed"
    assert candidate_is_accepted({"acceptance_summary": summary}) is True


def test_R5_and_T1_not_checked_empty_applicability_still_pass():
    report = {"status": "not_checked", "review_required": True,
              "applicable_requirement_kinds": []}
    summary = _summary(_base_source({"semantic_acceptance": report}), source=VASE_TEXT)
    assert summary["status"] == "passed"
    assert summary["semantic_requirement_state"] == "no_applicable_requirement"
    assert candidate_is_accepted({"acceptance_summary": summary}) is True


def test_T2_fully_verified_special_branch_still_passes():
    report = {"status": "passed", "review_required": False,
              "applicable_requirement_kinds": ["regular_polygon"],
              "object_acceptance": [{"target_ref": {"geometry_ids": [1]}, "status": "passed"}]}
    summary = _summary(_base_source({"semantic_acceptance": report}), source=POLYGON_TEXT)
    assert summary["status"] == "passed"
    assert summary["semantic_requirement_state"] == "fully_verified"
    assert candidate_is_accepted({"acceptance_summary": summary}) is True


# --- Semantic side does not regress ----------------------------------------

def test_R1_semantic_partial_review_false_still_blocked():
    report = {"status": "partial", "review_required": False,
              "applicable_requirement_kinds": ["heart_outline_features"]}
    summary = _summary(_base_source({"semantic_acceptance": report}), source=HEART_TEXT)
    assert summary["review_required"] is True
    assert summary["semantic_requirement_state"] == "unverified_or_partial"
    assert candidate_is_accepted({"acceptance_summary": summary}) is False


def test_star_only_not_checked_applicable_still_blocked():
    def callback(_text, _schema):
        return {"schema_version": "cad.construction-interpretation.v1",
                "is_construction_request": True, "confidence": 0.99,
                "evidence_text": [STAR_TEXT], "assumptions": [],
                "plan": {"units": "mm", "steps": [{
                    "op": "add_polyline", "step_id": "star", "output_ref": "star",
                    "semantic": {"label": "五角星"}, "closed": True,
                    "vertices": [{"x": x, "y": y} for x, y in _star(ox=0, cy=2000)]}]}}

    from app.cad_construction_interpreter import interpret_construction_request
    result = interpret_construction_request(STAR_TEXT, callback, force_structured_model=True)
    semantic = result["source_acceptance"].get("semantic_acceptance")
    assert semantic is not None
    assert semantic["status"] == "not_checked"
    assert semantic.get("applicable_requirement_kinds") == ["star_profile"]
    summary = result["acceptance_summary"]
    assert summary["review_required"] is True
    assert summary["semantic_requirement_state"] == "unverified_or_partial"
    assert candidate_is_accepted({"acceptance_summary": summary}) is False


def test_C10_heart_passed_star_not_checked_still_not_accepted():
    result = execute_construction_plan({"units": "mm", "steps": [
        {"op": "add_polyline", "step_id": "h", "output_ref": "heart",
         "semantic": {"label": "爱心"}, "closed": True,
         "vertices": [{"x": x, "y": y} for x, y in _heart(2000)]},
        {"op": "add_polyline", "step_id": "s", "output_ref": "star",
         "semantic": {"label": "五角星"}, "closed": True,
         "vertices": [{"x": x, "y": y} for x, y in _star()]}]})
    proof = _verify_semantic_requirements_bound(C10_TEXT, result)
    assert proof["status"] == "partial"
    assert [t["status"] for t in proof["object_acceptance"]] == ["passed", "not_checked"]
    summary = _summary({"coverage": "partial", "unknown_requirements": [],
                        "semantic_acceptance": proof, "checks": []}, source=C10_TEXT)
    assert summary["review_required"] is True
    assert summary["semantic_requirement_state"] == "unverified_or_partial"
    assert candidate_is_accepted({"acceptance_summary": summary}) is False


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
