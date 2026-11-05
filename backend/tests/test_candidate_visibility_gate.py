from copy import deepcopy
import json
from unittest.mock import patch

from app.agent_http_service import (
    _agent_chat_stream_events,
    _bind_and_filter_candidate_visibility,
)
from app.schemas import AgentChatRequest


def _result(status: str = "passed") -> dict:
    variant = {
        "id": "variant-new",
        "parent_variant_id": "variant-source",
        "acceptance_summary": {
            "status": status,
            "review_required": status != "passed",
        },
    }
    return {
        "ok": True,
        "project_id": "project-1",
        "project": {"id": "project-1", "variants": [deepcopy(variant)]},
        "variants": [deepcopy(variant)],
        "variant": variant,
        "preview_paths": [[[0, 0], [1, 1]]],
        "drawing_json": {"geometries": [{"id": 1}]},
        "next_action": "select_design_variant",
    }


def test_candidate_is_visible_only_when_passed_and_bound_to_current_run() -> None:
    with patch(
        "app.agent_http_service.agent_runs.get",
        return_value={
            "id": "run-1",
            "project_id": "project-1",
            "source_variant_id": "variant-source",
        },
    ):
        result = _bind_and_filter_candidate_visibility("run-1", _result())

    assert result["candidate_visibility"]["status"] == "visible"
    assert result["candidate_binding"] == {
        "run_id": "run-1",
        "project_id": "project-1",
        "variant_id": "variant-new",
    }
    assert result["variant"]["id"] == "variant-new"
    assert result["preview_paths"]


def test_candidate_with_review_required_acceptance_is_hidden() -> None:
    with patch(
        "app.agent_http_service.agent_runs.get",
        return_value={"id": "run-1", "project_id": "project-1"},
    ):
        result = _bind_and_filter_candidate_visibility(
            "run-1", _result("review_required")
        )

    assert result["ok"] is False
    assert result["candidate_visibility"]["status"] == "hidden"
    assert "acceptance_summary.status_not_passed" in result["candidate_visibility"]["reason"]
    assert result["variant"] is None
    assert result["variants"] == []
    assert result["preview_paths"] == []
    assert result["drawing_json"] is None


def test_candidate_from_another_project_is_hidden() -> None:
    with patch(
        "app.agent_http_service.agent_runs.get",
        return_value={"id": "run-1", "project_id": "project-other"},
    ):
        result = _bind_and_filter_candidate_visibility("run-1", _result())

    assert result["candidate_visibility"]["status"] == "hidden"
    assert "candidate_not_bound_to_current_run" in result["candidate_visibility"]["reason"]


def test_candidate_with_wrong_parent_variant_is_hidden() -> None:
    with patch(
        "app.agent_http_service.agent_runs.get",
        return_value={
            "id": "run-1",
            "project_id": "project-1",
            "source_variant_id": "variant-other",
        },
    ):
        result = _bind_and_filter_candidate_visibility("run-1", _result())

    assert result["candidate_visibility"]["status"] == "hidden"
    assert "candidate_not_bound_to_current_run" in result["candidate_visibility"]["reason"]


def test_candidate_missing_from_current_project_snapshot_is_hidden() -> None:
    value = _result()
    value["project"]["variants"] = []
    with patch(
        "app.agent_http_service.agent_runs.get",
        return_value={"id": "run-1", "project_id": "project-1"},
    ):
        result = _bind_and_filter_candidate_visibility("run-1", value)

    assert result["candidate_visibility"]["status"] == "hidden"
    assert result["variant"] is None


def test_stream_failure_never_falls_back_to_local_template_cad() -> None:
    prepared = {
        "history": [],
        "memory_before": {},
        "navigation_result": None,
        "resolution": {"memory": {}, "retrieved": {}, "ambiguous": False},
        "model_message": "生成标准篮球场",
        "route": {
            "name": "drawing_design",
            "operation": "create",
            "decision_source": "test",
        },
        "knowledge": {},
        "stale_guide": None,
    }
    command = AgentChatRequest(message="生成标准篮球场", mode="advanced")
    with (
        patch("app.agent_http_service._prepare_agent_chat_context", return_value=prepared),
        patch("app.agent_http_service.robot_agent.knowledge_context", return_value={}),
        patch(
            "app.agent_http_service.robot_agent.chat_stream",
            side_effect=RuntimeError("provider stream disconnected"),
        ),
        patch(
            "app.agent_http_service.robot_agent._local_template_intent"
        ) as local_fallback,
        patch(
            "app.agent_http_service.robot_agent.enrich_result",
            side_effect=lambda result, route, knowledge: result,
        ),
        patch(
            "app.agent_http_service.conversation_memory.remember",
            return_value={},
        ),
    ):
        events = [json.loads(item) for item in _agent_chat_stream_events(command)]

    local_fallback.assert_not_called()
    result = events[-1]
    assert result["type"] == "result"
    assert result["ok"] is False
    assert result["failure_category"] == "model_stream_failure"
    assert result["retryable"] is True
    assert "variant" not in result
    assert "preview_paths" not in result
