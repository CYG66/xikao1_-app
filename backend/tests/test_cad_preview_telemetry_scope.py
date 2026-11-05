import pytest

from app.agent_service import RobotAgentService


@pytest.mark.parametrize("text", [
    "圆形半径1米，圆心(0,3)；矩形宽4米、高3米，中心(5,0)，坐标单位米。",
    "新建CAD图纸，圆形在坐标(0,0)，矩形位置在右侧，只预览。",
    "将图形位置向右移动2米，图纸坐标单位米",
])
def test_drawing_coordinates_do_not_request_live_localization(text):
    route = RobotAgentService.route_intent(text, mode="advanced")
    assert route["tool_family"] == "cad"
    assert "localization" not in route["requested_data_domains"]
    result = RobotAgentService.enrich_result({"ok": True, "message": "图纸参数已记录，请确认生成。"}, route)
    assert "无法确认当前定位状态" not in result["message"]


@pytest.mark.parametrize("text", [
    "查询小车当前定位状态",
    "查看机器人当前坐标是否有效",
    "新建CAD图纸，同时查询全站仪定位状态",
])
def test_explicit_live_localization_still_requires_freshness(text):
    route = RobotAgentService.route_intent(text, mode="advanced")
    assert "localization" in route["requested_data_domains"]


def test_execution_readiness_retains_localization_requirement():
    route = RobotAgentService.route_intent("开始任务", mode="advanced")
    assert "localization_valid" in route["context_requirements"]


def test_late_promoted_cad_followup_does_not_retain_coordinate_telemetry_domain():
    route = {"name": "drawing_design", "tool_family": "cad", "operation": "create",
             "requested_data_domains": ["localization"], "context_requirements": ["mission_stage"],
             "user_message": "字母A总高3米，斜笔端点(0,0)(1,3)(2,0)，坐标单位米"}
    result = RobotAgentService.enrich_result({"ok": True, "message": "参数已合并，请确认生成。"}, route)
    assert "localization" not in result["agent_context"]["quality"]["requested_domains"]
    assert "无法确认当前定位状态" not in result["message"]
    route["user_message"] += "，同时查询小车定位状态"
    assert "localization" in RobotAgentService.runtime_context(route)["quality"]["requested_domains"]
