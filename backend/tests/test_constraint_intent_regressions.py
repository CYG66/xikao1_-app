from copy import deepcopy

from app.cad_edit_intent import build_cad_edit_intent
from app.incremental_cad import edit_candidate_geometries
from app.incremental_cad import parse_incremental_edit
from app.cad_edit_intent import cad_edit_intent_clarification
from app.cad_edit_contract import build_cad_edit_contract, cad_edit_contract_to_edit
from app.cad_edit_session import continuation, remember_edit


def test_constraint_kind_survives_intent_normalization():
    intent = build_cad_edit_intent("让第1个与第2个同心", {
        "operation": "constraint", "instance": 1,
        "reference_instance": 2, "constraint_type": "concentric",
    })
    assert intent["parameters"]["constraint_type"] == "concentric"
    assert intent["parameters"]["reference_instance"] == 2


def test_equal_without_metric_never_defaults_to_height_or_mutates_source():
    source = [
        {"id": 1, "type": "circle", "template_instance": 1,
         "center": {"x": 0, "y": 0}, "radius": 500},
        {"id": 2, "type": "circle", "template_instance": 2,
         "center": {"x": 3000, "y": 0}, "radius": 700},
    ]
    before = deepcopy(source)
    result, error = edit_candidate_geometries(source, {
        "operation": "constraint", "instance": 1,
        "reference_instance": 2, "constraint_type": "equal",
    })
    assert result is None
    assert "不会默认按高度修改" in error
    assert source == before


def test_logical_object_roundtrip_never_invents_instance_ids():
    edit = {"operation": "translate", "logical_object_ids": ["circle", "rectangle"],
            "geometry_ids": [7, 12], "dx_mm": 100, "dy_mm": 0}
    restored = cad_edit_contract_to_edit(build_cad_edit_contract(edit, source_text="整体右移"))
    assert restored["geometry_ids"] == [7, 12]
    assert restored["logical_object_ids"] == ["circle", "rectangle"]
    assert "instance" not in restored
    assert "instances" not in restored


def test_equality_clarifies_then_resumes_with_explicit_metric_and_target():
    text = "让第1个图形与第2个图形一样大"
    intent = build_cad_edit_intent(text, parse_incremental_edit(text))
    assert "一样大是指" in cad_edit_intent_clarification(intent)
    selection = {"scope": "group", "project_id": "p", "variant_id": "v", "geometry_ids": [1, 2]}
    pending = remember_edit(None, text, {}, {"operation": "modify", "drawing_selection": selection})
    project = {"id": "p", "variants": [{"id": "v"}], "design_base_variant_id": "v"}
    resumed = continuation("半径相等", {"pending_cad_edit": pending}, "p", None, lambda _: project)
    parsed = parse_incremental_edit(resumed["message"])
    assert parsed["dimension"] == "半径"
    assert parsed["reference_instance"] == 2
    assert cad_edit_intent_clarification(build_cad_edit_intent(resumed["message"], parsed)) is None
    assert resumed["drawing_selection"] == selection


def test_area_answer_is_preserved_and_explicitly_unsupported():
    text = "让第1个图形与第2个图形面积相等"
    parsed = parse_incremental_edit(text)
    assert parsed["dimension"] == "面积"
    question = cad_edit_intent_clarification(build_cad_edit_intent(text, parsed))
    assert "尚不支持面积" in question
