import pytest

from app.cad_construction_interpreter import ground_size_clarification, interpret_construction_request


SOURCE = "新建CAD图纸，画一个圆形和一个矩形，分别作为两个完整对象，只预览，不执行小车。"
QUESTION = "圆形的直径（或半径）和矩形的宽×高分别是多少？两个对象左右排列时中间间距要预留多少？"


def test_size_question_does_not_presuppose_unrequested_arrangement():
    question, removed = ground_size_clarification(QUESTION, SOURCE)
    assert question == "圆形的直径（或半径）和矩形的宽×高分别是多少？"
    assert len(removed) == 1


@pytest.mark.parametrize("requirement", ["圆形在矩形左侧", "两个对象左右排列", "两个对象间距待确定", "圆形与矩形相切"])
def test_explicit_layout_or_relation_is_never_removed(requirement):
    assert ground_size_clarification(QUESTION, SOURCE + requirement) == (QUESTION, [])


def test_combined_question_falls_back_to_size_without_invented_layout():
    question, removed = ground_size_clarification("请给出尺寸并说明两个对象左右排列的间距？", SOURCE)
    assert question == "请补充各对象的实际尺寸及单位。" and removed


def test_production_interpretation_uses_grounded_question_consistently():
    payload = {"schema_version": "cad.construction-interpretation.v1", "is_construction_request": True,
               "plan": None, "evidence_text": [SOURCE], "assumptions": [], "confidence": .35,
               "clarification": {"question_key": "size", "question": QUESTION, "recognized_shape": "圆形和一个矩形"}}
    result = interpret_construction_request(SOURCE, model_callback=lambda *_: payload, force_structured_model=True)
    assert result["status"] == "clarification_required"
    assert "左右" not in result["error"]["message"]
    assert result["error"]["message"] == result["clarification"]["question"] == result["clarification"]["suggested_prompt"]
    assert result["clarification_grounding"]["removed_unsupported_layout_questions"]


def test_grounded_multi_object_clarification_outranks_assumption_based_plan():
    source = "生成一个爱心和一个五角星，爱心在左，五角星在右"
    payload = {
        "schema_version": "cad.construction-interpretation.v1",
        "is_construction_request": True,
        "evidence_text": [source],
        "assumptions": ["临时假设尺寸"],
        "confidence": .5,
        "clarification": {
            "question_key": "size",
            "question": "爱心和五角星各自的尺寸及单位是多少？",
            "recognized_shape": "爱心、五角星",
        },
        "plan": {
            "units": "m",
            "steps": [{
                "op": "add_circle", "step_id": "assumed", "output_ref": "assumed",
                "semantic": {"label": "假设轮廓"},
                "center": {"x": 0, "y": 0}, "radius": 10,
            }],
        },
    }

    result = interpret_construction_request(
        source, model_callback=lambda *_: payload, force_structured_model=True,
    )

    assert result["status"] == "clarification_required"
    assert result["error"]["code"] == "missing_component_dimensions"
    assert "尺寸" in result["clarification"]["question"]


def test_compound_request_without_component_sizes_is_blocked_before_model_guessing():
    source="生成一个爱心和一个五角星，爱心在左，五角星在右"
    calls=[]

    result=interpret_construction_request(
        source,model_callback=lambda *_: calls.append(True) or {},force_structured_model=True,
    )

    assert result["status"]=="clarification_required"
    assert result["error"]["code"]=="missing_component_dimensions"
    assert result["provider_attempted"] is False
    assert calls==[]
    assert "爱心" in result["clarification"]["question"]
    assert "五角星" in result["clarification"]["question"]
