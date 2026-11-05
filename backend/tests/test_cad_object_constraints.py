from copy import deepcopy

from app.cad_object_constraints import compile_concentric_edit, compile_object_constraint
from app.incremental_cad import edit_candidate_geometries
from app.cad_edit_contract import build_cad_edit_contract, cad_edit_contract_to_edit
from app.cad_edit_plan import build_cad_edit_plan


def fixture():
    geometries = [
        {"id": 7, "type": "circle", "center": {"x": 0, "y": 3000}, "radius": 1000},
        {"id": 12, "type": "polyline", "closed": True, "vertices": [
            {"x": -1000, "y": -1000}, {"x": 1000, "y": -1000},
            {"x": 1000, "y": 1000}, {"x": -1000, "y": 1000}]},
        {"id": 99, "type": "circle", "center": {"x": 9000, "y": 9000}, "radius": 50},
    ]
    objects = [{"object_id": "c", "label": "圆形", "geometry_refs": [7]},
               {"object_id": "r", "label": "矩形", "geometry_refs": [12]}]
    edit = {"operation": "constraint", "constraint_type": "concentric",
            "logical_object_ids": ["r", "c"], "geometry_ids": [12, 7]}
    return geometries, objects, edit


def test_compiled_concentric_uses_existing_contract_and_protects_reference():
    source, objects, edit = fixture()
    before = deepcopy(source)
    compiled, error = compile_concentric_edit(edit, objects, source, "以圆形为基准，移动矩形使两者同心")
    assert error is None
    contract = build_cad_edit_contract(compiled, source_text="以圆形为基准，移动矩形使两者同心")
    restored = cad_edit_contract_to_edit(contract)
    result, error = edit_candidate_geometries(source, restored)
    assert error is None
    assert result[0] == before[0] and result[2] == before[2]
    assert source == before
    assert result[1]["vertices"][0] == {"x": -1000.0, "y": 2000.0}
    plan = build_cad_edit_plan(source, result, contract)
    assert plan["expected_changes"]["modified_geometry_ids"] == [12]
    assert plan["expected_changes"]["protected_geometry_ids"] == [7, 99]


def test_unspecified_or_conflicting_reference_never_uses_selection_order():
    source, objects, edit = fixture()
    for text in ("让矩形和圆形同心", "固定圆形，固定矩形，使两者同心"):
        compiled, error = compile_concentric_edit(edit, objects, source, text)
        assert compiled is None and "固定哪个对象" in error


def test_other_reference_moves_only_circle():
    source, objects, edit = fixture()
    compiled, error = compile_concentric_edit(edit, objects, source, "以矩形为基准，使两者同心")
    assert error is None
    result, error = edit_candidate_geometries(source, compiled)
    assert error is None and result[0]["center"] == {"x": 0.0, "y": 0.0}
    assert result[1:] == source[1:]


def test_shared_or_stale_ownership_is_rejected():
    source, objects, edit = fixture()
    objects[1]["geometry_refs"] = [7]
    assert compile_concentric_edit(edit, objects, source, "固定圆形")[0] is None
    objects[1]["geometry_refs"] = [123]
    assert compile_concentric_edit(edit, objects, source, "固定圆形")[0] is None


def test_arbitrary_outline_does_not_claim_bbox_center_is_geometric_center():
    source, objects, edit = fixture()
    source[1]["vertices"][0]["x"] = -500
    compiled, error = compile_concentric_edit(edit, objects, source, "固定圆形，使两者同心")
    assert compiled is None and "中心尚不能独立确认" in error


def test_negated_reference_is_not_treated_as_permission_to_move_other_object():
    source, objects, edit = fixture()
    compiled, error = compile_concentric_edit(edit, objects, source, "不要固定圆形，让两者同心")
    assert compiled is None and "否定指令" in error


def test_equal_width_compiles_resize_and_preserves_other_dimension_and_reference():
    source, objects, edit = fixture()
    source[0]["radius"] = 2000
    edit.update(constraint_type="equal", dimension="宽度")
    compiled, error = compile_object_constraint(edit, objects, source, "以圆形为基准，让矩形宽度相等")
    assert error is None
    contract = build_cad_edit_contract(compiled, source_text="以圆形为基准，让矩形宽度相等")
    result, error = edit_candidate_geometries(source, cad_edit_contract_to_edit(contract))
    assert error is None
    vertices = result[1]["vertices"]
    assert max(p["x"] for p in vertices) - min(p["x"] for p in vertices) == 4000
    assert [p["y"] for p in vertices] == [p["y"] for p in source[1]["vertices"]]
    assert result[0] == source[0] and result[2] == source[2]
    assert contract["constraints"][0]["reference_object_id"] == "c"


def test_equal_radius_compiles_without_moving_circle_center():
    source, objects, edit = fixture()
    source[1] = {"id": 12, "type": "circle", "center": {"x": 4000, "y": 0}, "radius": 500}
    objects[1]["label"] = "小圆"
    edit.update(constraint_type="equal", dimension="半径")
    compiled, error = compile_object_constraint(edit, objects, source, "以圆形为基准，让小圆半径相等")
    assert error is None
    result, error = edit_candidate_geometries(source, compiled)
    assert error is None and result[1]["radius"] == 1000
    assert result[1]["center"] == source[1]["center"] and result[0] == source[0]


def test_equal_metric_and_reference_must_be_explicit():
    source, objects, edit = fixture()
    edit.update(constraint_type="equal")
    assert "一样大是指" in compile_object_constraint(edit, objects, source, "一样大")[1]
    edit["dimension"] = "面积"
    assert "尚不支持面积" in compile_object_constraint(edit, objects, source, "固定圆形")[1]
    edit["dimension"] = "宽度"
    assert "固定哪个对象" in compile_object_constraint(edit, objects, source, "宽度相等")[1]
    assert compile_object_constraint(edit, objects, source, "固定矩形")[0] is None  # No circle distortion.
    edit["dimension"] = "半径"
    assert "两个完整圆形" in compile_object_constraint(edit, objects, source, "固定圆形")[1]


def test_primitive_reference_does_not_depend_on_model_label_wording():
    source, objects, edit = fixture()
    objects[0]["label"] = "圆形主体"
    objects[1]["label"] = "矩形边界"
    compiled, error = compile_object_constraint(edit, objects, source, "以圆形为基准，使两者同心")
    assert error is None and compiled["logical_object_id"] == "r"


def test_two_circles_cannot_be_disambiguated_by_generic_primitive_name():
    source, objects, edit = fixture()
    source[1] = {"id": 12, "type": "circle", "center": {"x": 4000, "y": 0}, "radius": 500}
    objects[0]["label"] = "左圆主体"
    objects[1]["label"] = "右圆主体"
    compiled, error = compile_object_constraint(edit, objects, source, "以圆形为基准，使两者同心")
    assert compiled is None and "固定哪个对象" in error


def test_latest_explicit_reference_replaces_previous_turn_but_same_turn_conflicts_do_not():
    source, objects, edit = fixture()
    compiled, error = compile_object_constraint(edit, objects, source,
        "让矩形和圆形同心，以圆形为基准\n改为以矩形为基准，使两者同心")
    assert error is None and compiled["logical_object_id"] == "c"
    assert compiled["constraints"][-1]["reference_object_id"] == "r"
    assert compile_object_constraint(edit, objects, source, "固定圆形，固定矩形，使两者同心")[0] is None


def test_later_positive_reference_can_resolve_previous_negative_clarification():
    source, objects, edit = fixture()
    compiled, error = compile_object_constraint(edit, objects, source,
        "不要固定圆形，使两者同心\n以矩形为基准")
    assert error is None and compiled["logical_object_id"] == "c"
    assert compile_object_constraint(edit, objects, source, "以圆形为基准\n不要固定圆形")[0] is None
