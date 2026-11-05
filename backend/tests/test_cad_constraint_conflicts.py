from copy import deepcopy
import pytest
from app.incremental_cad import parse_incremental_edit, edit_candidate_geometries
from app.cad_edit_intent import build_cad_edit_intent, cad_edit_intent_clarification
from app.cad_object_constraints import compile_object_constraint


@pytest.mark.parametrize("message", [
    "让圆形和矩形同心并且宽度相等",
    "让圆形和矩形宽度相等，高度也相等",
    "让两个图形不要同心",
    "让两个图形平行且垂直",
])
def test_multiple_or_negated_relations_do_not_silently_execute_first(message):
    parsed = parse_incremental_edit(message)
    assert parsed["constraint_conflict"]
    assert "多个约束" in cad_edit_intent_clarification(build_cad_edit_intent(message, parsed))
    assert compile_object_constraint(parsed, [], [], message)[0] is None
    source = [{"id": 1, "type": "circle", "center": {"x": 0, "y": 0}, "radius": 1}]
    before = deepcopy(source)
    assert edit_candidate_geometries(source, parsed)[0] is None
    assert source == before


@pytest.mark.parametrize("message,kind,metric", [
    ("让圆形和矩形同心，改为宽度相等", "equal", "宽度"),
    ("让圆形和矩形宽度相等，改成高度相等", "equal", "高度"),
    ("让圆形和矩形不要同心，只要宽度相等", "equal", "宽度"),
    ("让圆形和矩形宽度相等\n改为同心", "concentric", None),
])
def test_explicit_replacement_keeps_only_latest_required_relation(message, kind, metric):
    parsed = parse_incremental_edit(message)
    assert not parsed.get("constraint_conflict")
    assert parsed["constraint_type"] == kind
    assert parsed.get("dimension") == metric


def test_concentric_synonyms_are_not_multiple_relations():
    parsed = parse_incremental_edit("让圆形和矩形同心，圆心重合")
    assert parsed["constraint_type"] == "concentric" and not parsed.get("constraint_conflict")
