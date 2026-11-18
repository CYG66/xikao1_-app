"""Round9 G1 summary guard regression (Agent C).

Zero real model calls. These tests exercise the production summary gate and the
real interpreter entry against A's three-state semantic verdict. They do not
extend geometry algorithms, do not add a star-specific verifier or generator,
and do not change H2/H3/H4 gates, ``max_repairs`` or candidate-save
authorization.
"""

import math

from app.cad_construction import execute_construction_plan
from app.cad_construction_interpreter import (
    _verify_semantic_requirements_bound,
    construction_acceptance_summary,
)
from app.cad_candidate_state import candidate_is_accepted

HEART_TEXT = "生成一个闭合爱心轮廓，宽度4米，高度4米"
HEART_RECON_TEXT = "生成一个左右对称、平滑闭合的爱心，宽4米高4米"
C10_TEXT = "生成一个爱心和一个五角星，爱心在左，五角星在右"
LETTER_TEXT = "生成一个大写字母A的轮廓，高3米宽2米"
HOUSE_TEXT = "生成一个房子轮廓，宽4米高3米，屋顶是三角形，下面加一个门"
STAR_TEXT = "生成一个五角星，外接圆半径2米"
VASE_TEXT = "画一个花瓶"


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


def _summary(source_acceptance, source=None):
    return construction_acceptance_summary(
        preflight_structure=None, structure_contract=None, structure_validation=None,
        composition_contract=None, composition_validation=None,
        source_acceptance=source_acceptance, source=source)


def _base_source(semantic=None, coverage="complete"):
    source = {"coverage": coverage, "unknown_requirements": [],
              "checks": [{"status": "passed", "field": "primitive_dimension"}]}
    if semantic is not None:
        source["semantic_acceptance"] = semantic
    return source


# --- Contract positives: T1 / T2 -------------------------------------------

def test_T1_no_applicable_requirement_allows_summary_pass():
    # Stray review_required flag on a no-applicable report must not false-fail.
    report = {"status": "not_checked", "review_required": True,
              "applicable_requirement_kinds": []}
    summary = _summary(_base_source(report), source=VASE_TEXT)
    assert summary["status"] == "passed"
    assert summary["review_required"] is False
    assert summary["semantic_requirement_state"] == "no_applicable_requirement"
    assert candidate_is_accepted({"acceptance_summary": summary}) is True


def test_T2_fully_verified_special_branch_allows_summary_pass():
    report = {"status": "passed", "review_required": False,
               "applicable_requirement_kinds": ["regular_polygon"],
               "object_acceptance": [
                   {"target_ref": {"geometry_ids": [1]}, "status": "passed"}]}
    summary = _summary(_base_source(report), source="生成一个正五边形，外接圆半径2米")
    assert summary["status"] == "passed"
    assert summary["review_required"] is False
    assert summary["semantic_requirement_state"] == "fully_verified"
    assert candidate_is_accepted({"acceptance_summary": summary}) is True


# --- Blocking negatives: R1, C10, star-only, unknown kind ------------------

def test_R1_complete_coverage_partial_review_false_is_not_accepted():
    report = {"status": "partial", "review_required": False,
              "applicable_requirement_kinds": ["heart_outline_features"]}
    summary = _summary(_base_source(report), source=HEART_TEXT)
    assert summary["status"] == "review_required"
    assert summary["review_required"] is True
    assert summary["semantic_requirement_state"] == "unverified_or_partial"
    assert "partial_overall" in summary["semantic_incomplete_reasons"]
    assert candidate_is_accepted({"acceptance_summary": summary}) is False


def test_C10_heart_passed_star_not_checked_overall_not_accepted():
    result = _exec([
        _step("h", "heart", "爱心", _heart(2000)),
        _step("s", "star", "五角星", _star()),
    ])
    proof = _verify_semantic_requirements_bound(C10_TEXT, result)
    assert proof["status"] == "partial"
    assert [t["status"] for t in proof["object_acceptance"]] == ["passed", "not_checked"]
    summary = _summary({"coverage": "partial", "unknown_requirements": [],
                        "semantic_acceptance": proof, "checks": []}, source=C10_TEXT)
    assert summary["review_required"] is True
    assert summary["semantic_requirement_state"] == "unverified_or_partial"
    reasons = summary["semantic_incomplete_reasons"]
    assert "object_not_checked" in reasons
    assert "no_verifier" in reasons
    affected = summary["semantic_incomplete_objects"]
    assert any(entry.get("geometry_ids") == [2] for entry in affected)
    assert candidate_is_accepted({"acceptance_summary": summary}) is False


def test_star_only_report_is_retained_and_summary_blocks():
    from app.cad_construction_interpreter import interpret_construction_request

    def callback(_text, _schema):
        return {"schema_version": "cad.construction-interpretation.v1",
                "is_construction_request": True, "confidence": 0.99,
                "evidence_text": [STAR_TEXT], "assumptions": [],
                "plan": {"units": "mm", "steps": [
                    {"op": "add_polyline", "step_id": "star", "output_ref": "star",
                     "semantic": {"label": "五角星"}, "closed": True,
                     "vertices": [{"x": x, "y": y} for x, y in _star(ox=0, cy=2000)]}]}}

    result = interpret_construction_request(STAR_TEXT, callback, force_structured_model=True)
    assert result["status"] == "ready"
    semantic = result["source_acceptance"].get("semantic_acceptance")
    # The dropped-report guard is fixed: an applicable mandatory kind survives.
    assert semantic is not None
    assert semantic["status"] == "not_checked"
    assert semantic.get("applicable_requirement_kinds") == ["star_profile"]
    summary = result["acceptance_summary"]
    assert summary["review_required"] is True
    assert summary["semantic_requirement_state"] == "unverified_or_partial"
    assert "report_unchecked_applicable" in summary["semantic_incomplete_reasons"]
    assert candidate_is_accepted({"acceptance_summary": summary}) is False


def test_unknown_kind_is_not_silently_accepted():
    report = {"status": "unverified", "review_required": True,
              "unsupported_kind": "mystery_contour",
              "applicable_requirement_kinds": ["mystery_contour"],
              "reason": "no_verifier_for_kind"}
    summary = _summary(_base_source(report), source="画一个神秘轮廓")
    assert summary["review_required"] is True
    assert summary["semantic_requirement_state"] == "unverified_or_partial"
    reasons = summary["semantic_incomplete_reasons"]
    assert "unknown_kind" in reasons
    assert "no_verifier" in reasons
    assert candidate_is_accepted({"acceptance_summary": summary}) is False


# --- Inherited partial channels: house / capital A must stay blocked -------

def test_C26_capital_a_inherited_partial_still_not_accepted():
    result = _exec([
        _step("o", "outer", "字母A外轮廓", _letter_outer()),
        _step("t", "tri", "三角区域", _letter_triangle()),
    ])
    proof = _verify_semantic_requirements_bound(LETTER_TEXT, result)
    assert proof["status"] == "partial"
    assert proof["review_required"] is False  # inherited 423E
    summary = _summary({"coverage": "partial", "unknown_requirements": [],
                        "semantic_acceptance": proof, "checks": []}, source=LETTER_TEXT)
    assert summary["review_required"] is True
    assert summary["semantic_requirement_state"] == "unverified_or_partial"
    assert "partial_overall" in summary["semantic_incomplete_reasons"]
    assert candidate_is_accepted({"acceptance_summary": summary}) is False


def test_house_real_entry_still_not_accepted():
    from app.cad_construction_interpreter import interpret_construction_request

    def callback(_text, _schema):
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
    assert summary["semantic_requirement_state"] == "unverified_or_partial"
    assert candidate_is_accepted({"acceptance_summary": summary}) is False


def test_A1_and_A9_heart_fixtures_still_not_accepted():
    for text, scale in ((HEART_TEXT, 4000), (HEART_RECON_TEXT, 2000)):
        result = _exec([_step("h", "heart", "爱心", _heart(scale))])
        proof = _verify_semantic_requirements_bound(text, result)
        summary = _summary({"coverage": "partial", "unknown_requirements": [],
                            "semantic_acceptance": proof, "checks": []}, source=text)
        assert summary["review_required"] is True
        assert summary["semantic_requirement_state"] == "unverified_or_partial"
        assert candidate_is_accepted({"acceptance_summary": summary}) is False


# --- Missing report: blocked only when the source recognizes a kind --------

def test_missing_report_blocks_when_source_recognizes_mandatory_kind():
    summary = _summary(_base_source(None), source=HEART_TEXT)
    assert summary["review_required"] is True
    assert summary["semantic_requirement_state"] == "unverified_or_partial"
    assert "report_unavailable" in summary["semantic_incomplete_reasons"]
    assert candidate_is_accepted({"acceptance_summary": summary}) is False


def test_missing_report_stays_non_blocking_without_source_signal():
    summary = _summary(_base_source(None), source=VASE_TEXT)
    assert summary["semantic_requirement_state"] == "no_applicable_requirement"
    # coverage=complete with a passed check: no signal keeps the prior pass.
    assert summary["status"] == "passed"
    assert candidate_is_accepted({"acceptance_summary": summary}) is True


# --- Round9 recon truth table regression (R1-R6) ---------------------------

def test_recon_truth_table_R1_to_R6():
    cases = [
        ("R1", {"status": "partial", "review_required": False}, "complete", False),
        ("R2", {"status": "partial", "review_required": True}, "complete", False),
        ("R3", {"status": "unverified", "review_required": True}, "complete", False),
        ("R4", None, "complete", True),
        ("R5", {"status": "not_checked", "review_required": True}, "complete", True),
        ("R6", {"status": "partial", "review_required": False}, "partial", False),
    ]
    for _name, semantic, coverage, allows_pass in cases:
        summary = _summary(_base_source(semantic, coverage=coverage), source=VASE_TEXT)
        assert candidate_is_accepted({"acceptance_summary": summary}) is allows_pass
        if allows_pass:
            assert summary["review_required"] is False
        else:
            assert summary["review_required"] is True
