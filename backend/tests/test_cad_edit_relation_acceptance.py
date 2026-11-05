from copy import deepcopy
import pytest

from app.cad_edit_contract import build_cad_edit_contract
from app.cad_edit_gate import build_cad_edit_preflight
from app.cad_edit_relation_acceptance import validate_edit_relations
from app.incremental_cad import edit_candidate_geometries


def sample():
    source = [{"id": 1, "type": "circle", "center": {"x": 0, "y": 0}, "radius": 10},
              {"id": 2, "type": "circle", "center": {"x": 100, "y": 0}, "radius": 20}]
    edit = {"operation": "translate", "geometry_ids": [1], "logical_object_id": "a",
            "dx_mm": 100, "dy_mm": 0, "constraints": [{"kind": "concentric",
            "moving_object_id": "a", "reference_object_id": "b", "reference_geometry_ids": [2]}]}
    return source, edit


def test_concentric_is_measured_and_reference_protected():
    source, edit = sample()
    target, error = edit_candidate_geometries(source, edit)
    assert error is None
    checked = build_cad_edit_preflight(source, target, build_cad_edit_contract(edit, source_text="同心"))
    assert checked["ready"]
    assert checked["relation_validation"]["checks"][0]["error_mm"] == 0


def test_correctly_executed_wrong_translation_cannot_pass_relation_gate():
    source, edit = sample()
    edit["dx_mm"] = 80
    target, _ = edit_candidate_geometries(source, edit)
    checked = build_cad_edit_preflight(source, target, build_cad_edit_contract(edit, source_text="同心"))
    assert checked["effect_validation"]["verified"]  # Executor obeyed the wrong compiled vector.
    assert not checked["relation_validation"]["verified"]
    assert not checked["ready"]


def test_equal_radius_cannot_pass_with_wrong_but_correctly_executed_size():
    source, edit = sample()
    edit.update(operation="resize", dimension="半径", value_mm=15)
    edit.pop("dx_mm"); edit.pop("dy_mm")
    edit["constraints"][0].update(kind="equal", dimension="半径")
    target, _ = edit_candidate_geometries(source, edit)
    contract = build_cad_edit_contract(edit, source_text="半径相等")
    checked = build_cad_edit_preflight(source, target, contract)
    assert checked["effect_validation"]["verified"]
    assert not checked["ready"]
    edit["value_mm"] = 20
    target, _ = edit_candidate_geometries(source, edit)
    assert build_cad_edit_preflight(source, target, build_cad_edit_contract(edit, source_text="半径相等"))["ready"]


def test_reference_mutation_missing_reference_and_unsupported_metric_fail_closed():
    source, edit = sample()
    contract = build_cad_edit_contract(edit, source_text="同心")
    target, _ = edit_candidate_geometries(source, edit)
    changed = deepcopy(target); changed[1]["radius"] = 99
    assert not validate_edit_relations(source, changed, contract)["verified"]
    assert not validate_edit_relations(source, target[:1], contract)["verified"]
    contract["constraints"][0].update(kind="equal", dimension="面积")
    assert not validate_edit_relations(source, target, contract)["verified"]


def test_unrelated_constraint_is_not_claimed_as_verified_relation():
    source, _ = sample()
    checked = validate_edit_relations(source, source, {"constraints": [{"kind": "symmetry"}]})
    assert checked["enforced"] is False and checked["checks"] == []


def test_already_satisfied_relation_is_success_without_geometry_change():
    source, edit = sample()
    source[0]["center"] = dict(source[1]["center"])
    edit["dx_mm"] = 0
    target, _ = edit_candidate_geometries(source, edit)
    checked = build_cad_edit_preflight(source, target, build_cad_edit_contract(edit, source_text="同心"))
    assert checked["ready"] and checked["already_satisfied"]
    assert checked["relation_validation"]["verified"]
    assert checked["diff"]["counts"]["modified"] == 0


def test_noop_with_wrong_relation_or_without_relation_still_fails():
    source, edit = sample()
    edit["dx_mm"] = 0
    contract = build_cad_edit_contract(edit, source_text="同心")
    checked = build_cad_edit_preflight(source, source, contract)
    assert not checked["ready"] and not checked["already_satisfied"]
    contract["constraints"] = []
    checked = build_cad_edit_preflight(source, source, contract)
    assert not checked["ready"] and not checked["already_satisfied"]


def test_satisfied_result_clears_pending_session_even_with_same_variant():
    from app.cad_edit_session import remember_edit
    route = {"operation": "modify", "drawing_selection": {"project_id": "p", "variant_id": "v", "geometry_ids": [1]}}
    result = {"ok": True, "cad_edit_outcome": "already_satisfied", "variant": {"id": "v"}}
    assert remember_edit({"question": "old clarification"}, "同心", result, route) is None


def test_concentric_cannot_silently_resize_correct_object():
    source, edit = sample()
    target, _ = edit_candidate_geometries(source, edit)
    target[0]["radius"] = 5
    result = validate_edit_relations(source, target, build_cad_edit_contract(edit, source_text="同心"))
    assert not result["verified"]
    assert result["checks"][0]["error_mm"] == 0  # Centers match; size preservation still fails.
    assert any(not c["verified"] for c in result["checks"][0]["preservation_checks"])


@pytest.mark.parametrize("drift", ["center", "height", "other_object", "extra_geometry"])
def test_equal_width_does_not_allow_other_correct_properties_to_drift(drift):
    source = [{"id": 1, "type": "polyline", "closed": True, "vertices": [
        {"x": -2, "y": -1}, {"x": 2, "y": -1}, {"x": 2, "y": 1}, {"x": -2, "y": 1}]},
        {"id": 2, "type": "circle", "center": {"x": 10, "y": 0}, "radius": 1},
        {"id": 3, "type": "circle", "center": {"x": 20, "y": 0}, "radius": 1}]
    edit = {"operation": "resize", "geometry_ids": [1], "logical_object_id": "a", "dimension": "宽度", "value_mm": 2,
            "constraints": [{"kind": "equal", "dimension": "宽度", "moving_object_id": "a", "reference_object_id": "b", "reference_geometry_ids": [2]}]}
    target, _ = edit_candidate_geometries(source, edit)
    contract = build_cad_edit_contract(edit, source_text="宽度相等")
    assert validate_edit_relations(source, target, contract)["verified"]
    if drift == "center":
        for p in target[0]["vertices"]: p["x"] += 5
    elif drift == "height":
        for p in target[0]["vertices"]: p["y"] *= 2
    elif drift == "other_object":
        target[2]["radius"] = 3
    else:
        target.append({"id": 99, "type": "circle", "center": {"x": 0, "y": 0}, "radius": 1})
    assert not validate_edit_relations(source, target, contract)["verified"]


def test_equal_radius_cannot_also_move_center():
    source, edit = sample()
    edit.update(operation="resize", dimension="半径", value_mm=20)
    edit.pop("dx_mm"); edit.pop("dy_mm")
    edit["constraints"][0].update(kind="equal", dimension="半径")
    target, _ = edit_candidate_geometries(source, edit)
    target[0]["center"]["x"] = 500
    result = validate_edit_relations(source, target, build_cad_edit_contract(edit, source_text="半径相等"))
    assert not result["verified"] and result["checks"][0]["error_mm"] == 0
