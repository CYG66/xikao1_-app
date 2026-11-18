"""Round11 R-04 retention wiring regression (Agent C).

Zero real model calls. These tests exercise the production summary gate and
the caller-side missing-report fallback against A's three-state semantic
verdict. The caller reuses A's exported text scans only; it adds no second
vocabulary and no geometry-profile inference.

Coverage:

(a) a ``not_checked`` report carrying a non-empty applicable marker is kept
    in ``source_acceptance`` and blocks the summary;
(b) a missing report with explicit or ambiguous star wording stays blocked
    (third state), never released as "no applicable requirement";
(c) a missing report with ordinary shape wording still releases normally;
(d) the C10 heart + star fixture stays partial / review_required / rejected.

No star-specific verifier or generator is added, and H2/H3/H4 gates,
``max_repairs`` or candidate-save authorization are untouched.
"""

import math

from app.cad_construction import execute_construction_plan
from app.cad_candidate_state import candidate_is_accepted
from app.cad_construction_interpreter import (
    _verify_semantic_requirements_bound,
    construction_acceptance_summary,
)
from app.cad_semantic_acceptance import verify_semantic_requirements
from app.cad_semantic_dispatch import state_allows_summary_passed

STAR_TEXT = "生成一个五角星，外接圆半径2米"
EXPLICIT_TEXTS = ["画一个五角星", STAR_TEXT]
AMBIGUOUS_TEXTS = ["画一个五角形", "画一个星星", "画一个星形"]
ORDINARY_TEXTS = ["画一个圆", "画一个矩形"]
C10_TEXT = "生成一个爱心和一个五角星，爱心在左，五角星在右"


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


# --- (a) not_checked + non-empty applicable marker is retained --------------

def test_r04_not_checked_applicable_report_is_retained_and_blocks():
    text = "画一个五角星"
    report = verify_semantic_requirements(text, [])
    assert report["status"] == "not_checked"
    assert report.get("applicable_requirement_kinds") == ["star_profile"]

    # Mirror the interpreter storage gate (cad_construction_interpreter.py:979-981):
    # a not_checked report with a non-empty applicable marker must be kept.
    applicable = report.get("applicable_requirement_kinds") or []
    retained = report["status"] != "not_checked" or bool(applicable)
    assert retained is True

    source_acceptance = _base_source(report)
    assert source_acceptance["semantic_acceptance"] is report
    summary = _summary(source_acceptance, source=text)
    assert summary["review_required"] is True
    assert summary["semantic_requirement_state"] == "unverified_or_partial"
    assert summary["semantic_applicable_requirement_kinds"] == ["star_profile"]
    assert "report_unchecked_applicable" in summary["semantic_incomplete_reasons"]
    assert state_allows_summary_passed({"state": summary["semantic_requirement_state"]}) is False
    assert candidate_is_accepted({"acceptance_summary": summary}) is False


# --- (b) missing report: explicit / ambiguous wording must stay blocked ----

def test_r04_missing_report_explicit_star_wording_blocks():
    for text in EXPLICIT_TEXTS:
        summary = _summary(_base_source(None), source=text)
        assert summary["semantic_requirement_state"] == "unverified_or_partial"
        assert "report_unavailable" in summary["semantic_incomplete_reasons"]
        assert summary["review_required"] is True
        assert candidate_is_accepted({"acceptance_summary": summary}) is False


def test_r04_missing_report_ambiguous_wording_blocks():
    for text in AMBIGUOUS_TEXTS:
        summary = _summary(_base_source(None), source=text)
        assert summary["semantic_requirement_state"] == "unverified_or_partial"
        reasons = summary["semantic_incomplete_reasons"]
        assert "report_unavailable" in reasons
        assert "ambiguous_requirement" in reasons
        assert summary["review_required"] is True
        assert candidate_is_accepted({"acceptance_summary": summary}) is False


# --- (c) missing report: ordinary shapes still release normally ------------

def test_r04_missing_report_ordinary_shapes_are_released():
    for text in ORDINARY_TEXTS:
        summary = _summary(_base_source(None), source=text)
        assert summary["semantic_requirement_state"] == "no_applicable_requirement"
        assert summary["semantic_incomplete_reasons"] == []
        assert summary["review_required"] is False
        assert candidate_is_accepted({"acceptance_summary": summary}) is True


# --- (d) C10 regression: heart passed, star not_checked, overall rejected ---

def test_r04_c10_heart_passed_star_not_checked_still_rejected():
    result = _exec([
        _step("h", "heart", "爱心", _heart(2000)),
        _step("s", "star", "五角星", _star()),
    ])
    proof = _verify_semantic_requirements_bound(C10_TEXT, result)
    assert proof["status"] == "partial"
    assert proof["review_required"] is True
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
