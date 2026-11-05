from copy import deepcopy
import pytest

from app.cad_composition_addition import parse_relative_additions, execute_relative_additions
from app.cad_edit_contract import build_cad_edit_contract
from app.cad_edit_plan import build_cad_edit_plan
from app.cad_edit_gate import build_cad_edit_preflight
from app.cad_edit_preview import build_cad_edit_preview
from app.cad_assertions import build_cad_machine_assertions


SOURCE = [{
    "id": 1, "type": "polyline", "closed": True,
    "vertices": [{"x": -4000, "y": -2000}, {"x": 4000, "y": -2000},
                 {"x": 4000, "y": 2000}, {"x": -4000, "y": 2000}],
}]


def test_relative_addition_uses_shared_plan_and_independent_geometry_measurement():
    text = "两个矩形宽2米、高1米，分别位于当前图形中心线上方5米和下方5米，关于中心线对称"
    contract = parse_relative_additions(text)
    assert contract is not None
    original = deepcopy(SOURCE)
    built = execute_relative_additions(SOURCE, contract)
    assert SOURCE == original
    assert [step["op"] for step in built["plan"]["steps"]] == ["add_centered_rectangle"] * 2
    assert [check["center_mm"] for check in built["acceptance"]["checks"]] == [(0, 5000), (0, -5000)]
    ids = [item["id"] for item in built["added"]]
    edit = build_cad_edit_contract({
        "operation": "add_geometry", "geometry_ids": [1], "created_geometry_ids": ids,
        "project_id": "project", "parent_variant_id": "parent", "addition_contract": contract,
    }, source_text=text)
    plan = build_cad_edit_plan(SOURCE, built["geometries"], edit)
    preview = build_cad_edit_preview(SOURCE, built["geometries"], edit)
    assertions = build_cad_machine_assertions(SOURCE, built["geometries"], edit, plan, preview)
    assert build_cad_edit_preflight(SOURCE, built["geometries"], edit)["ready"]
    assert plan["verification"]["verified"] and assertions["verified"]


def test_incomplete_or_conflicting_relative_addition_does_not_construct():
    assert parse_relative_additions("在图形中心线上下各加一个矩形") is None
    assert parse_relative_additions("两个矩形宽2米高1米，中心线上方5米下方4米，要求对称") is None
    assert parse_relative_additions("两个矩形宽2米高1米，中心线上方5米下方5米") is not None


def test_replay_rejects_changed_added_geometry():
    text = "两个矩形宽2米高1米，中心线上方5米下方5米"
    contract = parse_relative_additions(text)
    built = execute_relative_additions(SOURCE, contract)
    edit = build_cad_edit_contract({
        "operation": "add_geometry", "geometry_ids": [1],
        "created_geometry_ids": [item["id"] for item in built["added"]],
        "project_id": "project", "parent_variant_id": "parent", "addition_contract": contract,
    }, source_text=text)
    altered = deepcopy(built["geometries"])
    altered[-1]["vertices"][0]["x"] += 100
    assert not build_cad_edit_preflight(SOURCE, altered, edit)["ready"]


def test_tampered_addition_contract_is_rejected_before_execution():
    contract = parse_relative_additions("两个矩形宽2米高1米，中心线上方5米下方5米")
    contract["count"] = 3
    with pytest.raises(ValueError, match="invalid dimensions or placements"):
        execute_relative_additions(SOURCE, contract)
