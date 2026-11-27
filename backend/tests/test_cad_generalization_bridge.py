from __future__ import annotations

import tempfile
from pathlib import Path

from app.cad_construction_interpreter import (
    clarify_construction_request,
    parse_rule_construction_plan,
)
from app.conversation_memory import ConversationMemoryStore, is_explicit_new_creation


def test_explicit_new_creation_is_not_treated_as_history_reference() -> None:
    for text in (
        "做一个边长850毫米的正方形检测平台外轮廓，左下角放在坐标原点，只要这一圈闭合轮廓。",
        "画一个圆形井盖基座，圆心放在(-2400,1600)，半径1275毫米，只画这个圆。",
    ):
        assert is_explicit_new_creation(text)
        with tempfile.TemporaryDirectory() as tmp:
            store = ConversationMemoryStore(Path(tmp) / "memory.json")
            result = store.resolve("fresh-conversation", text)
        assert result["required"] is False
        assert result["message"] == text


def test_historical_mirror_request_still_needs_target() -> None:
    text = "把刚才那个图形左右镜像一下，保留原来的标注。"
    assert is_explicit_new_creation(text) is False
    with tempfile.TemporaryDirectory() as tmp:
        store = ConversationMemoryStore(Path(tmp) / "memory.json")
        result = store.resolve("fresh-conversation", text)
    assert result["required"] is True
    assert "镜像轴" in result["question"]
    assert "标注" in result["question"]


def test_millimetre_coordinates_are_scaled_once_to_metres() -> None:
    plan = parse_rule_construction_plan(
        "画一条直线导轨中心线，从(-1200,800)到(3600,2200)，单位毫米，"
        "端点必须准确落在给定坐标。"
    )
    assert plan is not None
    step = plan.steps[0]
    assert step.op == "add_line"
    assert step.start.x == -1.2 and step.start.y == 0.8
    assert step.end.x == 3.6 and step.end.y == 2.2


def test_four_hole_plate_points_are_not_reinterpreted_as_kilometres() -> None:
    plan = parse_rule_construction_plan(
        "画一块5000毫米乘3000毫米的四孔钢板，左下角在(0,0)，"
        "四个半径200毫米的孔分别位于(500,500)、(4500,500)、"
        "(500,2500)、(4500,2500)，外轮廓和四个孔都闭合。"
    )
    assert plan is not None
    vertices = plan.steps[0].vertices
    assert max(point.x for point in vertices) == 4.5
    assert max(point.y for point in vertices) == 2.5


def test_layout_request_does_not_fabricate_ready_parameters() -> None:
    from app.agent_skills import clarify_requirements

    result = clarify_requirements("在车间里排两排设备，中间留一条检修通道。")
    assert result["ready_for_design"] is False
    assert result["next_question_key"] == "layout_scope"
    assert "车间尺寸" in result["next_question"]


def test_vague_position_clarification_asks_size_and_offset() -> None:
    result = clarify_construction_request(
        "帮我画一个圆形检修口，位置放在设备基础左上角附近。"
    )
    assert "直径或半径" in result["question"]
    assert "偏移" in result["question"]
