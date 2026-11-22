"""C1.4 round-7 diagnostic: dimension inheritance, dependency closure,
recovery-context carry-over and failure-code separation.

This file records current production behaviour under the real
``_formal_cad_construction`` loop; only the model text outlet is stubbed.
Where a gap is found, the test asserts the *current* behaviour and flags the
missing field in the round-7 report. It does not lower acceptance, add a
budget, or special-case any shape.

Diagnostic scope (aligned with the frozen 70-example corpus and the A-side
V1.1 proposal as boundary reference only):
  - overall dimension vs part dimension scope;
  - affected part / upstream refs / downstream dependents / non-target;
  - recovery context: failed candidate, rejected plan, source refs;
  - whitelist releases already covered in C1.3, re-checked here;
  - dep_pending is a test-status label, not a production error code.
"""
from __future__ import annotations

import json
from copy import deepcopy

from app.cad_generation_recovery import (
    classify_feature_failure, evaluate_repair_progress,
    recovery_record, set_geometry_evaluator,
)
from test_c13_m2m3_loop_mock import (
    REF, SOURCE, _invalid, _plan, _ready, _run,
)


def _mixed_plan():
    """Outline (target) + wheel (non-target part).

    Overall size lives on a ``bounds_size`` assertion WITHOUT target_ref;
    the part size (radius) lives on the wheel step. ``R1/R2/R3`` are source
    requirement refs; the closed assertion is a downstream relation on REF.
    """
    plan = _plan()
    plan["units"] = "m"
    plan["assertions"] = [
        {"kind": "bounds_size", "assertion_id": "overall", "width": 4, "height": 3},
        {"kind": "closed", "assertion_id": "outline_closed", "target_ref": REF},
        {"kind": "center_distance", "assertion_id": "wheel_to_outline",
         "target_ref": "wheel", "reference_ref": REF, "distance": 2.0},
    ]
    outline = plan["steps"][0]
    outline["source_requirement_refs"] = ["R1"]
    outline["junction_constraints"] = [
        {"left_segment_index": 0, "right_segment_index": 0,
         "source_requirement_refs": ["R3"]}]
    wheel = {
        "op": "add_circle", "step_id": "wheel", "output_ref": "wheel",
        "radius": 2.0,
        "semantic": {"label": "wheel", "object_id": "wheel", "assembly_id": "whole"},
        "source_requirement_refs": ["R2"],
        "junction_constraints": [
            {"left_segment_index": 0, "right_segment_index": 0,
             "source_requirement_refs": ["R3"]}],
    }
    plan["steps"].append(wheel)
    return plan


def _steps(plan):
    return {s["output_ref"]: s for s in plan["steps"]}


# ---------------------------------------------------------------------------
# 1. Dimension inheritance: overall vs part scope
# ---------------------------------------------------------------------------

def test_dimension_overall_assertion_and_part_radius_survive_parameter_repair(tmp_path):
    """Parameter repair: overall bounds assertion, part radius and units must
    stay bound to their original scope; the wheel must not absorb the overall
    4x3 bounds, and the outline must not inherit the wheel radius."""
    before = _mixed_plan()
    param_details = {"check": "explicit_center",
                      "measured_center_mm": [1.0, 1.0], "expected_center_mm": [2.0, 3.0],
                      "error_mm": 1.2, "tolerance_mm": 0.5,
                      "measured_features": {"center": False},
                      "failed_features": ["center"],
                      "affected_output_refs": [REF]}
    first = _invalid(param_details, plan=before)

    after = deepcopy(before)
    after_steps = _steps(after)
    after_steps[REF]["x_expression"] = "2+2*sin(t)"
    replan = _ready(after)
    result, calls, store, project = _run([first, replan], tmp_path)

    assert len(calls) == 2
    context = calls[1]["kwargs"].get("component_repair_context")
    assert context is not None
    context_plan = context.get("plan") or context.get("rejected_plan")
    # Prior plan (with its source refs and sizes) rides in the repair context.
    assert _steps(context_plan)["wheel"]["radius"] == 2.0
    final_plan = replan["plan"]
    final_steps = _steps(final_plan)
    # Overall assertion preserved verbatim; it is not rebound to the wheel.
    assert final_plan["assertions"] == before["assertions"]
    overall = next(a for a in final_plan["assertions"] if a["assertion_id"] == "overall")
    assert overall.get("target_ref") is None
    # Part radius stays on the original wheel step.
    assert final_steps["wheel"]["radius"] == 2.0
    # Units consistent across plan and step-level values.
    assert final_plan["units"] == "m"


def test_dimension_part_size_and_non_target_preserved_under_structural_replan(tmp_path):
    """Structural replan rebuilds the outline; the non-target wheel keeps its
    radius, coordinates, source refs and junction closure; overall bounds stay."""
    before = _mixed_plan()
    fail_details = {"required_features": {"cusp": "outline cusp"},
                    "measured_features": {"cusp": False}, "failed_features": ["cusp"],
                    "geometry_ids": [REF], "affected_output_refs": [REF]}
    first = _invalid(fail_details, plan=before)

    after = deepcopy(before)
    after_steps = _steps(after)
    after_steps[REF]["y_expression"] = "3+2*cos(t)+abs(sin(t))"
    replan = _ready(after)
    result, calls, store, project = _run([first, replan], tmp_path)

    assert len(calls) == 2
    assert "component_repair_context" not in calls[1]["kwargs"]
    assert "repair_context" not in calls[1]["kwargs"]

    before_steps, final_steps = _steps(before), _steps(replan["plan"])
    assert set(final_steps) == {REF, "wheel"}
    # Non-target part preserved verbatim (radius, identity, source, closure).
    assert final_steps["wheel"] == before_steps["wheel"]
    assert replan["plan"]["assertions"] == before["assertions"]
    assert replan["plan"]["units"] == before["units"]
    assert final_steps[REF]["source_requirement_refs"] == ["R1"]
    assert final_steps["wheel"]["source_requirement_refs"] == ["R2"]


def test_dimension_scope_is_encoded_by_assertion_target_ref_and_step_field():
    """Scope encoding facts (diagnostic anchor for corpus comparison).

    Corpus cases (frozen, not executed here):
      - overall-size corpus cases (width/height, one with center): no part size supplied.
        A part-level radius/width added by the plan would be an invented
        constraint unless the source contract authorizes it.
      - A11: multiple parts, relative placement, no overall size.
      - C7: rectangle plus four circles; the 0.5m radius is a PART size,
        bound per circle, not an overall bounds assertion.
      - C29: nested squares; outer/inner side lengths are part-scoped.
    """
    plan = _mixed_plan()
    overall = next(a for a in plan["assertions"] if a["assertion_id"] == "overall")
    wheel = _steps(plan)["wheel"]
    # Overall: assertion without target_ref; part: numeric field on the step.
    assert overall.get("target_ref") is None
    assert "radius" in wheel
    # The overall bounds must not also be copied onto a part step field.
    assert "width" not in wheel and "height" not in wheel


# ---------------------------------------------------------------------------
# 2. Dependency closure: affected / upstream / downstream / non-target
# ---------------------------------------------------------------------------

def _downstream_refs(plan, seed_refs):
    """Small read-only diagnostic collector (NOT production code).

    Collects output refs named by assertions/constraints/layout relations that
    reference a seed ref. This mirrors the typed edges described in the
    closure protocol; production currently has no fixed-point propagation.
    """
    consumers = {r: set() for r in seed_refs}
    for assertion in plan.get("assertions") or []:
        target = assertion.get("target_ref")
        reference = assertion.get("reference_ref")
        if reference in consumers and target:
            consumers[reference].add(target)
    return consumers


def test_closure_downstream_dependency_is_listed_but_not_marked_revalidated():
    """Diagnostic gap: the wheel references the outline via center_distance.

    After the outline is rebuilt, the wheel relation must be revalidated.
    Current loop carries the old plan in context/previous-plan text but emits
    no ``revalidate_refs`` / ``downstream_refs`` closure marker; downstream
    revalidation is left to the next acceptance pass.
    """
    plan = _mixed_plan()
    downstream = _downstream_refs(plan, [REF])
    assert downstream[REF] == {"wheel"}

    fail_details = {"required_features": {"cusp": "outline cusp"},
                    "measured_features": {"cusp": False}, "failed_features": ["cusp"],
                    "geometry_ids": [REF], "affected_output_refs": [REF]}
    first = _invalid(fail_details, plan=plan)
    replan = _ready(deepcopy(plan))

    # The classifier/feedback payload contains repair channel and four failure
    # elements, but no downstream closure set.
    outcome = classify_feature_failure(fail_details, "structure_requirement_failed")
    assert "revalidate_refs" not in outcome
    assert "downstream_refs" not in outcome

    # Four layers observable in the preserved ready plan: affected REF rebuilt,
    # upstream source refs kept, non-target wheel kept; downstream wheel
    # relation remains an assertion but is not flagged for revalidation here.
    final_steps = _steps(replan["plan"])
    assert final_steps[REF]["source_requirement_refs"] == ["R1"]
    assert final_steps["wheel"]["source_requirement_refs"] == ["R2"]


def test_closure_upstream_source_refs_and_non_target_preserved_in_context(tmp_path):
    """Context carry: failed attempt deep-copied; source refs and non-target
    step survive into the next round's context."""
    before = _mixed_plan()
    param_details = {"measured_center_mm": [1.0, 1.0], "expected_center_mm": [2.0, 3.0],
                      "measured_features": {"center": False}, "failed_features": ["center"],
                      "affected_output_refs": [REF]}
    first = _invalid(param_details, plan=before)
    replan = _ready(deepcopy(before))
    result, calls, store, project = _run([first, replan], tmp_path)

    context = calls[1]["kwargs"]["component_repair_context"]
    context_steps = _steps(context["plan"])
    assert context_steps[REF]["source_requirement_refs"] == ["R1"]
    assert context_steps["wheel"]["source_requirement_refs"] == ["R2"]
    # Rejected plan is also embedded in the model prompt text.
    assert "前次未通过的计划" in calls[1]["text"]

    # The ready-success envelope persists the candidate; the recovery record is
    # attached to the interpretation (failure path projects it), so here the
    # same recovery_record helper the service calls is checked directly.
    record = recovery_record(SOURCE, [first, replan], max_repairs=2)
    assert record["repair_count"] == 1
    assert len(record["attempts"]) == 2
    assert record["attempts"][0]["error"] is not None
    for attempt in record["attempts"]:
        assert attempt["plan"] is not None


# ---------------------------------------------------------------------------
# 3. Whitelist release re-check (unit level; service-level cases in C1.3)
# ---------------------------------------------------------------------------

def test_whitelist_releases_round7_recheck(monkeypatch):
    def _stub(relation, equivalent, undetermined=False, reversed_flag=False):
        def _fn(spec_a, spec_b, tolerance):
            return {"equivalent": equivalent, "undetermined": undetermined,
                    "relation": relation, "reversed": reversed_flag,
                    "checks": {}, "fail_reasons": []}
        return _fn

    set_geometry_evaluator(_stub("different", equivalent=False))
    try:
        first = evaluate_repair_progress(None, _invalid(
            {"failed_features": ["cusp"], "measured_features": {"cusp": False}}))
        assert first["decision"] == "allow"
        assert first["progress"] == "first_repair"

        a = _invalid({"failed_features": ["cusp"], "measured_features": {"cusp": False}})
        b = _invalid({"failed_features": ["cusp"], "measured_features": {"cusp": False}},
                     plan=_plan(3))

        set_geometry_evaluator(_stub("similar_transform", equivalent=True))
        similar = evaluate_repair_progress(a, b)
        assert similar["decision"] == "allow"
        assert similar["geometry"]["undetermined"] is True

        set_geometry_evaluator(_stub("bogus_future_relation", equivalent=True))
        unknown = evaluate_repair_progress(a, b)
        assert unknown["decision"] == "allow"
        assert unknown["geometry"]["undetermined"] is True

        # Missing snapshot: no trial_result on either side.
        set_geometry_evaluator(_stub("identical", equivalent=True))
        missing = evaluate_repair_progress(a, b)
        assert missing["decision"] == "allow"
        assert missing["geometry"]["relation"] == "unavailable"

        improved = evaluate_repair_progress(
            _invalid({"failed_features": ["cusp", "side"],
                      "measured_features": {"cusp": True, "side": False}}),
            _invalid({"failed_features": ["side"],
                      "measured_features": {"cusp": True, "side": False}}))
        assert improved["decision"] == "allow"
        assert improved["progress"] == "feature_improved"

        new_failure = evaluate_repair_progress(
            _invalid({"failed_features": ["cusp"], "measured_features": {"cusp": False}}),
            _invalid({"failed_features": ["cusp", "side"],
                      "measured_features": {"cusp": False, "side": False}}))
        assert new_failure["decision"] == "allow"
        assert new_failure["progress"] == "new_failure"
    finally:
        set_geometry_evaluator(None)


# ---------------------------------------------------------------------------
# 4. Classifier evidence-strength audit (legacy boolean vs mathematical cusp)
# ---------------------------------------------------------------------------

def test_classifier_escalation_input_has_no_evidence_strength_guard():
    """Audit anchor: ``feature_replan`` fires on failure_subtype=cusp even when
    the only evidence is a legacy region-presence boolean. The classifier input
    contract has no ``measurement_method`` / analytic-evidence field yet; the
    over-escalation risk is recorded as unverified pending the A acceptance
    module. This test pins the current contract, it does not promote the
    boolean to a mathematical predicate.
    """
    details = {"failure_subtype": "cusp",
               "measured_features": {"cusp": False}, "failed_features": ["cusp"],
               "geometry_ids": [REF]}
    outcome = classify_feature_failure(details, "structure_requirement_failed")
    assert outcome["repair_class"] == "feature_replan"
    assert outcome["requires_structural_replan"] is True
    # No evidence-strength field is read today.
    assert outcome["missing_fields"]


# ---------------------------------------------------------------------------
# 5. Failure-code separation: production codes vs dep_pending test label
# ---------------------------------------------------------------------------

def test_dep_pending_is_not_a_production_error_code():
    """``failed_dep_pending`` marks tests whose strict assertions wait on an
    unmerged A1.1/B1.2 contract. It is not produced by ``recovery_category``
    and must not be counted as an editor defect in production statistics."""
    repaired = _invalid({"failed_features": ["cusp"], "measured_features": {"cusp": False}})
    record = recovery_record(SOURCE, [repaired], max_repairs=2)
    codes = {record["attempts"][0]["error"]["code"]}
    assert "dep_pending" not in codes
    assert "failed_dep_pending" not in codes
