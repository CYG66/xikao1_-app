"""P3 residual contract, policy dispatch and progress gate tests (no network)."""
from __future__ import annotations

import math

import pytest

from app.cad_residual_repair import (
    DISCRETE,
    NUMERIC,
    SCHEMA,
    TOPOLOGY,
    UNVERIFIABLE,
    build_residual_vector,
    collect_construction_error_residuals,
    collect_source_acceptance_residuals,
    discrete_residual,
    evaluate_residual_progress,
    merge_records,
    normalized_numeric_residual,
    numeric_residual,
    repair_budget_state,
    repair_feedback,
    residual_vector,
    two_consecutive_no_improvement,
    unverifiable_residual,
)


# ---------------------------------------------------------------------------
# P3-A: residual record contract
# ---------------------------------------------------------------------------

def test_numeric_residual_uses_tolerance_normalisation():
    assert normalized_numeric_residual(5000, 5000, 10) == 0.0
    assert normalized_numeric_residual(5010, 5000, 10) == 0.0
    assert math.isclose(normalized_numeric_residual(5030, 5000, 10), 2.0)
    record = numeric_residual(
        requirement_id="R-RADIUS", predicate="radius", expected=500,
        measured=502.5, tolerance=2.0, unit="mm")
    assert record["residual_type"] == NUMERIC
    assert record["delta"] == 2.5
    assert record["passed"] is False
    assert math.isclose(record["normalized_residual"], 0.25)
    assert record["repair_scope"]["strategy"] == "parameter_repair"


def test_numeric_residual_with_zero_tolerance_is_absolute_not_invented():
    record = numeric_residual(
        requirement_id="R-A", predicate="width", expected=10, measured=12,
        tolerance=0, unit="mm")
    assert record["delta"] == 2
    assert record["normalized_residual"] == 2
    assert record["passed"] is False


def test_missing_measurement_is_unverifiable_without_numeric_residual():
    record = unverifiable_residual(
        requirement_id="R-OPEN", predicate="closure", reason="no_verifier")
    assert record["residual_type"] == UNVERIFIABLE
    assert record["verification_status"] == "not_checked"
    assert record["expected"] is None
    assert record["measured"] is None
    assert record["delta"] is None
    assert record["normalized_residual"] is None
    assert record["passed"] is None
    assert record["repair_scope"]["strategy"] == "diagnose_or_clarify"


def test_discrete_and_numeric_residuals_are_not_summed_in_native_units():
    numeric = numeric_residual(
        requirement_id="R-W", predicate="width", expected=4000, measured=4000,
        tolerance=1, unit="mm")
    discrete = discrete_residual(
        requirement_id="R-T", predicate="curve_type", expected="cubic_bezier",
        measured="arc", unit="identity")
    vector = residual_vector([numeric, discrete])
    assert vector["schema"] == SCHEMA
    assert vector["continuous_score"] == 0
    assert vector["failing_discrete_count"] == 1
    assert vector["discrete_failures"][0]["expected"] == "cubic_bezier"
    assert vector["discrete_failures"][0]["unit"] == "identity"


def test_record_requires_all_authority_fields():
    record = numeric_residual(
        requirement_id="R-1", predicate="height", expected=10, measured=11,
        tolerance=2, unit="mm", object_ids=["obj-1"],
        geometry_ids=[7], plan_step_ids=["step-2"], mandatory=True)
    for field in ("requirement_id", "predicate", "object_ids", "geometry_ids",
                  "plan_step_ids", "expected", "measured", "tolerance", "delta",
                  "unit", "residual_type", "verification_status", "repair_scope"):
        assert field in record
    assert record["mandatory"] is True
    assert record["plan_step_ids"] == ["step-2"]


def test_merge_records_deduplicates_by_requirement_predicate_axis():
    first = numeric_residual(requirement_id="R", predicate="width",
                             expected=1, measured=2, tolerance=1)
    second = numeric_residual(requirement_id="R", predicate="width",
                              expected=1, measured=3, tolerance=1)
    merged = merge_records([first, second])
    assert len(merged) == 1
    assert merged[0]["measured"] == 3


# ---------------------------------------------------------------------------
# Existing verifier evidence adapters
# ---------------------------------------------------------------------------

def _plan():
    return {
        "steps": [
            {"step_id": "outer", "output_ref": "outer_ref"},
            {"step_id": "inner", "output_ref": "inner_ref"},
        ],
        "assertions": [
            {"assertion_id": "a-bounds", "kind": "bounds_size",
             "target_ref": "outer_ref", "width": 2.0, "height": 2.0,
             "tolerance": 0.5},
        ],
    }


def test_construction_bounds_failure_becomes_mm_numeric_records():
    error = {
        "code": "assertion_failed",
        "details": {
            "failures": [{
                "assertion_id": "a-bounds",
                "expected_assertion": {
                    "assertion_id": "a-bounds", "kind": "bounds_size",
                    "target_ref": "outer_ref", "width": 2.0, "height": 2.0,
                    "tolerance": 0.5,
                },
                "measured_bounds_mm": {
                    "min_x": 0, "max_x": 3000, "min_y": 0, "max_y": 3000,
                },
                "geometry_ids": [1, 2],
            }],
        },
    }
    records = collect_construction_error_residuals(error, _plan())
    assert {r["predicate"] for r in records} == {"width", "height"}
    assert all(r["unit"] == "mm" for r in records)
    assert records[0]["expected"] == 2000
    assert records[0]["measured"] == 3000
    assert records[0]["tolerance"] == 500
    assert records[0]["plan_step_ids"] == ["outer"]
    assert records[0]["geometry_ids"] == [1, 2]


def test_entity_count_failure_is_topology_not_mm():
    error = {
        "details": {
            "failures": [{
                "assertion_id": "a-count",
                "expected_assertion": {"assertion_id": "a-count",
                                       "kind": "entity_count", "equals": 4,
                                       "target_ref": "outer_ref"},
                "geometry_ids": [1, 2, 3, 4, 5],
            }],
        },
    }
    records = collect_construction_error_residuals(error, _plan())
    assert len(records) == 1
    assert records[0]["residual_type"] == TOPOLOGY
    assert records[0]["expected"] == 4
    assert records[0]["measured"] == 5
    assert records[0]["unit"] == "count"
    assert records[0]["delta"] is None


def test_identity_conflict_is_a_measured_topology_record():
    error = {
        "code": "logical_graph_invalid",
        "details": {
            "validation_errors": [{"code": "invalid_object_ids",
                                   "message": "逻辑对象 ID 缺失或重复"}],
            "identity_conflicts": [{
                "object_id": "shared_id",
                "members": [
                    {"geometry_refs": [2],
                     "source_steps": [{"step_id": "upper",
                                       "output_ref": "upper_ref"}]},
                    {"geometry_refs": [3],
                     "source_steps": [{"step_id": "lower",
                                       "output_ref": "lower_ref"}]},
                ],
            }],
        },
    }
    records = collect_construction_error_residuals(error, _plan())
    assert {r["predicate"] for r in records} == {
        "object_identity", "object_id_uniqueness"}
    identity = next(r for r in records if r["predicate"] == "object_identity")
    assert identity["residual_type"] == TOPOLOGY
    assert identity["expected"] == "distinct_object_ids"
    assert identity["measured"] == "shared_object_id"
    assert identity["plan_step_ids"] == ["upper", "lower"]
    assert identity["repair_scope"]["strategy"] == "structure_replan"


def test_source_acceptance_failure_preserves_requirement_id():
    acceptance = {
        "checks": [{
            "status": "failed", "source_requirement_id": "R-RADIUS-2",
            "field": "radius", "expected_mm": 500, "actual_mm": 250,
            "tolerance_mm": 0.5, "target_ref": "inner_ref",
            "reason": "radius_mismatch",
        }],
    }
    records = collect_source_acceptance_residuals(acceptance, _plan())
    assert records[0]["requirement_id"] == "R-RADIUS-2"
    assert records[0]["mandatory"] is True
    assert records[0]["source"] == "source_acceptance"
    assert records[0]["plan_step_ids"] == ["inner"]
    assert records[0]["normalized_residual"] == 499.0


def test_source_unknown_requirements_are_unverifiable_not_zero():
    acceptance = {"unknown_requirements": [
        {"requirement_id": "R-LOBES", "reason": "verifier_unavailable"}]}
    records = collect_source_acceptance_residuals(acceptance, _plan())
    assert records[0]["residual_type"] == UNVERIFIABLE
    assert records[0]["measured"] is None
    assert records[0]["normalized_residual"] is None
    assert records[0]["requirement_id"] == "R-LOBES"


def test_build_vector_collects_error_and_source_evidence():
    error = {"details": {"expected_count": 4, "actual_count": 5}}
    acceptance = {"checks": [{
        "status": "failed", "source_requirement_id": "R-R",
        "field": "radius", "expected_mm": 500, "actual_mm": 250,
        "tolerance_mm": 0.5,
    }]}
    vector = build_residual_vector(construction_error=error,
                                   source_acceptance=acceptance, plan=_plan())
    assert vector["record_count"] == 2
    assert vector["failing_numeric_count"] == 1
    assert vector["failing_discrete_count"] == 1
    assert vector["authority"] == "backend_measured_geometry"
    assert vector["real_model_calls"] == 0


# ---------------------------------------------------------------------------
# P3-B: repair scope and feedback
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("predicate,strategy", [
    ("radius", "parameter_repair"),
    ("center", "object_placement"),
    ("continuity", "control_point_repair"),
    ("curve_type", "component_replan"),
    ("entity_count", "structure_replan"),
])
def test_strategy_dispatch_is_predicate_based(predicate, strategy):
    record = discrete_residual(requirement_id="R", predicate=predicate,
                               expected="a", measured="b")
    assert record["repair_scope"]["strategy"] == strategy


def test_repair_feedback_protects_unrelated_steps_and_forbids_bypass():
    vector = residual_vector([
        numeric_residual(requirement_id="R-R", predicate="radius",
                         expected=500, measured=250, tolerance=1,
                         plan_step_ids=["inner"]),
        discrete_residual(requirement_id="R-C", predicate="curve_type",
                          expected="cubic_bezier", measured="arc",
                          plan_step_ids=["divider"]),
        numeric_residual(requirement_id="R-W", predicate="width",
                         expected=4000, measured=4000, tolerance=1,
                         plan_step_ids=["outer"]),
    ])
    feedback = repair_feedback(vector, _plan())
    assert feedback["editable_output_refs"] == ["inner_ref"]
    assert feedback["protected_output_refs"] == ["outer_ref"]
    assert feedback["editable_step_ids"] == ["divider", "inner"]
    assert feedback["protected_step_ids"] == ["outer"]
    assert set(feedback["must_not"]) >= {
        "delete_constraints", "widen_tolerance", "change_user_requirement"}
    assert "radius" in feedback["prompt_text"]
    assert "cubic_bezier" in feedback["prompt_text"]


def test_repair_feedback_does_not_emit_unmeasured_numeric_rows_as_repairs():
    vector = residual_vector([unverifiable_residual(
        requirement_id="R-U", predicate="closure", reason="no_verifier")])
    feedback = repair_feedback(vector, _plan())
    assert feedback["records"][0]["strategy"] == "diagnose_or_clarify"
    assert "不得伪造" in feedback["prompt_text"]


# ---------------------------------------------------------------------------
# P3-C: progress, regression and stop conditions
# ---------------------------------------------------------------------------

def _vector(score_records):
    return residual_vector(score_records)


def test_five_percent_improvement_allows_next_repair():
    before = _vector([numeric_residual(requirement_id="R", predicate="radius",
                                       expected=500, measured=600, tolerance=10)])
    after = _vector([numeric_residual(requirement_id="R", predicate="radius",
                                      expected=500, measured=590, tolerance=10)])
    result = evaluate_residual_progress(before, after)
    assert result["decision"] == "allow"
    assert result["progress"] == "improved"
    assert result["relative_improvement"] >= 0.05
    assert result["threshold_scope"] == "continuous_excess_residual_only"


def test_less_than_five_percent_is_no_improvement():
    before = _vector([numeric_residual(requirement_id="R", predicate="radius",
                                       expected=500, measured=600, tolerance=10)])
    after = _vector([numeric_residual(requirement_id="R", predicate="radius",
                                      expected=500, measured=599.9, tolerance=10)])
    result = evaluate_residual_progress(before, after)
    assert result["progress"] == "no_improvement"
    assert result["effective_improvement"] is False


def test_discrete_failure_reduction_is_progress_without_mm_summing():
    before = _vector([
        discrete_residual(requirement_id="R-C", predicate="curve_type",
                          expected="cubic_bezier", measured="arc"),
        numeric_residual(requirement_id="R-R", predicate="radius",
                         expected=500, measured=500, tolerance=1),
    ])
    after = _vector([
        discrete_residual(requirement_id="R-C", predicate="curve_type",
                          expected="cubic_bezier", measured="cubic_bezier"),
        numeric_residual(requirement_id="R-R", predicate="radius",
                         expected=500, measured=500, tolerance=1),
    ])
    result = evaluate_residual_progress(before, after)
    assert result["progress"] == "improved"
    assert result["discrete_after"] == 0


def test_regression_blocks_even_if_numeric_residual_improves():
    before = _vector([
        numeric_residual(requirement_id="R-R", predicate="radius", expected=500,
                         measured=600, tolerance=10, mandatory=True),
        numeric_residual(requirement_id="R-W", predicate="width", expected=4000,
                         measured=4000, tolerance=1, mandatory=True),
    ])
    after = _vector([
        numeric_residual(requirement_id="R-R", predicate="radius", expected=500,
                         measured=500, tolerance=10, mandatory=True),
        numeric_residual(requirement_id="R-W", predicate="width", expected=4000,
                         measured=4010, tolerance=1, mandatory=True),
    ])
    result = evaluate_residual_progress(before, after)
    assert result["decision"] == "block"
    assert result["progress"] == "regression"
    assert result["regressions"][0]["requirement_id"] == "R-W"


def test_disappearing_failure_into_unverifiable_is_not_progress():
    from app.cad_residual_repair import unverifiable_residual
    failed = discrete_residual(requirement_id="R-TOP", predicate="object_identity",
                               expected="distinct", measured="shared", unit="identity",
                               residual_type="topology", mandatory=True)
    before = residual_vector([failed])
    after = residual_vector([
        unverifiable_residual(requirement_id=f"R-{i}",
                              predicate="source_requirement_verification",
                              reason="not_measured")
        for i in range(3)
    ])
    progress = evaluate_residual_progress(before, after)
    assert progress["progress"] == "no_improvement"
    assert progress["effective_improvement"] is False


def test_zero_to_zero_is_not_progress():
    progress = evaluate_residual_progress(residual_vector([]), residual_vector([]))
    assert progress["progress"] == "no_improvement"
    assert progress["relative_improvement"] == 0.0


def test_two_consecutive_no_improvement_marks_repair_stalled_and_no_third():
    assert two_consecutive_no_improvement(["improved", "no_improvement"]) is False
    assert two_consecutive_no_improvement(
        ["no_improvement", "no_improvement"]) is True
    state = repair_budget_state(["no_improvement", "no_improvement"], 2)
    assert state["repair_stalled"] is True
    assert state["allow_next_repair"] is False
    assert state["third_repair_allowed"] is False


def test_no_improvement_after_first_repair_still_allows_one_more():
    state = repair_budget_state(["no_improvement"], 1)
    assert state["repair_stalled"] is False
    assert state["allow_next_repair"] is True


def test_a_new_failure_alone_is_not_effective_progress():
    before = _vector([numeric_residual(requirement_id="R-R", predicate="radius",
                                       expected=500, measured=600, tolerance=10)])
    after = _vector([
        numeric_residual(requirement_id="R-R", predicate="radius",
                         expected=500, measured=600, tolerance=10),
        discrete_residual(requirement_id="R-NEW", predicate="curve_type",
                          expected="cubic_bezier", measured="arc"),
    ])
    result = evaluate_residual_progress(before, after)
    assert result["progress"] == "no_improvement"
    assert result["new_failures"]
