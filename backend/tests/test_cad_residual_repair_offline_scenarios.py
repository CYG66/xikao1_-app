"""Offline repair-response simulations for P3 (no provider, no network)."""
from __future__ import annotations

from app.cad_generation_recovery import recovery_record
from app.cad_residual_repair import (
    DISCRETE,
    discrete_residual,
    evaluate_residual_progress,
    feedback_text,
    numeric_residual,
    repair_budget_state,
    repair_feedback,
    residual_vector,
)


def _plan():
    return {"steps": [
        {"step_id": "outer", "output_ref": "outer_ref"},
        {"step_id": "eye", "output_ref": "eye_ref"},
    ]}


def _radius(value, step="eye"):
    return numeric_residual(requirement_id="R-RADIUS", predicate="radius",
                            expected=500, measured=value, tolerance=1,
                            unit="mm", plan_step_ids=[step], mandatory=True)


def _curve(kind):
    return discrete_residual(requirement_id="R-CURVE", predicate="curve_type",
                             expected="cubic_bezier", measured=kind,
                             plan_step_ids=["eye"])


def test_simulated_effective_repair():
    before = residual_vector([_radius(250), _curve("cubic_bezier")])
    after = residual_vector([_radius(500), _curve("cubic_bezier")])
    result = evaluate_residual_progress(before, after)
    assert result["progress"] == "improved"
    assert result["score_after"] == 0
    assert result["regressions"] == []


def test_simulated_no_improvement():
    before = residual_vector([_radius(250)])
    after = residual_vector([_radius(250)])
    result = evaluate_residual_progress(before, after)
    assert result["progress"] == "no_improvement"
    assert result["effective_improvement"] is False


def test_simulated_partial_improvement_above_five_percent():
    before = residual_vector([_radius(250)])
    after = residual_vector([_radius(300)])
    result = evaluate_residual_progress(before, after)
    assert result["progress"] == "improved"
    assert result["score_after"] > 0
    assert result["relative_improvement"] >= 0.05


def test_simulated_new_error_is_not_effective_by_itself():
    before = residual_vector([_radius(250)])
    after = residual_vector([_radius(250), _curve("arc")])
    result = evaluate_residual_progress(before, after)
    assert result["progress"] == "no_improvement"
    assert result["new_failures"]


def test_simulated_repair_of_unrelated_object_is_hidden_from_scope():
    before = residual_vector([_radius(250, "eye")])
    feedback = repair_feedback(before, _plan())
    assert feedback["editable_step_ids"] == ["eye"]
    assert feedback["protected_step_ids"] == ["outer"]
    assert "outer_ref" in feedback["protected_output_refs"]


def test_simulated_curve_type_upgrade_dispatch():
    record = _curve("arc")
    assert record["residual_type"] == DISCRETE
    assert record["repair_scope"]["strategy"] == "component_replan"
    feedback = repair_feedback(residual_vector([record]), _plan())
    assert feedback["records"][0]["strategy"] == "component_replan"
    assert "按期望状态替换离散类型" in feedback["records"][0]["instruction"]


def test_simulated_component_replan_protects_other_components():
    vector = residual_vector([
        _curve("arc"),
        numeric_residual(requirement_id="R-W", predicate="width",
                         expected=4000, measured=4000, tolerance=1,
                         unit="mm", plan_step_ids=["outer"]),
    ])
    feedback = repair_feedback(vector, _plan())
    assert feedback["editable_step_ids"] == ["eye"]
    assert "outer" in feedback["protected_step_ids"]


def test_simulated_two_no_improvement_stops_without_third():
    decisions = ["improved", "no_improvement", "no_improvement"]
    assert repair_budget_state(decisions, 2)["repair_stalled"] is True
    assert repair_budget_state(decisions, 2)["third_repair_allowed"] is False
    assert repair_budget_state(decisions, 2)["allow_next_repair"] is False


def test_feedback_is_the_text_consumed_by_the_repair_prompt():
    feedback = repair_feedback(residual_vector([_radius(250)]), _plan())
    assert feedback["prompt_text"].startswith("结构化几何残差")
    assert "R-RADIUS" in feedback["prompt_text"]
    assert "500" in feedback["prompt_text"] and "250" in feedback["prompt_text"]
    assert "5%阈值只判断进展" in feedback["prompt_text"]
    combined = feedback_text("后端试算反馈：前一次计划未通过验证",
                             residual_vector([_radius(250)]), _plan())
    assert combined.startswith("后端试算反馈")
    assert "结构化几何残差" in combined
    assert "可编辑输出步骤" in combined
    assert "必须保持的输出步骤" in combined


def test_offline_simulation_is_not_recorded_as_real_model_success():
    vector = residual_vector([_radius(250)])
    assert vector["real_model_calls"] == 0
    assert vector["authority"] == "backend_measured_geometry"
    assert vector["source"] == "backend_measurement"


def test_recovery_record_persists_residual_evidence_and_progress():
    before = {"status": "invalid", "residual_vector": residual_vector([_radius(250)])}
    after = {"status": "invalid", "residual_vector": residual_vector([_radius(400)])}
    record = recovery_record("source", [before, after], max_repairs=2)
    assert record["attempts"][0]["residual_vector"]["record_count"] == 1
    assert record["attempts"][1]["residual_vector"]["records"][0]["measured"] == 400
    assert record["progress_log"][0]["progress"] == "residual_improved"
    assert record["final_residual_vector"]["records"][0]["measured"] == 400
    assert record["repair_stalled"] is False
    assert record["third_repair_allowed"] is False
    assert record["repair_budget"]["allow_next_repair"] is True


def test_recovery_record_marks_stalled_after_two_no_improvement_attempts():
    same = residual_vector([_radius(250)])
    record = recovery_record("source", [
        {"status": "invalid", "residual_vector": same},
        {"status": "invalid", "residual_vector": same},
        {"status": "invalid", "residual_vector": same},
    ], max_repairs=2)
    assert [item["progress"] for item in record["progress_log"]] == [
        "no_improvement", "no_improvement"]
    assert record["repair_stalled"] is True
    assert record["third_repair_allowed"] is False
    assert record["repair_budget"]["allow_next_repair"] is False


def test_recovery_record_blocks_mandatory_regression():
    before = {"status": "invalid", "residual_vector": residual_vector([
        numeric_residual(requirement_id="R-W", predicate="width", expected=4000,
                         measured=4000, tolerance=1, unit="mm", mandatory=True)] +
        [_radius(250)])}
    after = {"status": "invalid", "residual_vector": residual_vector([
        numeric_residual(requirement_id="R-W", predicate="width", expected=4000,
                         measured=4010, tolerance=1, unit="mm", mandatory=True)] +
        [_radius(500)])}
    record = recovery_record("source", [before, after], max_repairs=2)
    assert record["progress_log"][0]["decision"] == "block"
    assert record["progress_log"][0]["progress"] == "mandatory_regression"
