from __future__ import annotations

from copy import deepcopy

from app import agent_http_service, agent_service
from app.agent_http_service import agent_chat
from app.agent_service import RobotAgentService
from app.cad_candidate_state import candidate_is_accepted, geometry_evidence_hash
from app.cad_construction_interpreter import interpret_construction_request
from app.conversation_memory import ConversationMemoryStore
from app.creative_projects import CreativeProjectStore
from app.schemas import AgentChatRequest


def test_formal_http_entry_delivers_a2_first_candidate(tmp_path, monkeypatch):
    source = "新建图纸，画一个宽5米高3米的矩形"
    store = CreativeProjectStore(tmp_path / "projects.json")
    memory = ConversationMemoryStore(tmp_path / "memory.json")
    frozen = interpret_construction_request(source)
    assert frozen["status"] == "ready"
    state = {"turn": 0, "project_id": None}
    routes = []

    def route(_message, _mode, _history=None):
        turn = state["turn"]
        state["turn"] += 1
        if turn == 0:
            return {
                "name": "drawing_design",
                "tool_family": "cad",
                "operation": "create",
                "decision_source": "frozen_http_a2",
            }
        return {
            "name": "drawing_design",
            "tool_family": "cad",
            "operation": "create",
            "stage": "candidate_generation",
            "selected_project_id": state["project_id"],
            "decision_source": "frozen_http_a2_confirmation",
        }

    def frozen_plan(message, mode=None):
        # Turns 1-2 intentionally exercise the deterministic clarification
        # path.  Only the final confirmed generation uses the frozen result.
        if state["turn"] < 3:
            return interpret_construction_request(message)
        assert message
        return deepcopy(frozen)

    monkeypatch.setattr(agent_service.robot_agent, "mode", "local")
    monkeypatch.setattr(agent_service.robot_agent, "api_keys", {})
    monkeypatch.setattr(agent_service.robot_agent, "resolve_intent", route)
    monkeypatch.setattr(agent_service.robot_agent, "route_intent", route)
    monkeypatch.setattr(agent_service.robot_agent, "_interpret_cad_construction_plan", frozen_plan)
    monkeypatch.setattr(agent_service, "get_creative_project_store", lambda: store)
    monkeypatch.setattr(agent_service, "conversation_memory", memory)
    monkeypatch.setattr(agent_http_service, "get_creative_project_store", lambda: store)
    monkeypatch.setattr(agent_http_service, "conversation_memory", memory)

    conversation = "cad-final-close-http-a2"
    first = agent_chat(AgentChatRequest(
        message="新建图纸，画一个矩形",
        mode="advanced",
        conversation_id=conversation,
        client_id="final-close",
    ))
    routes.append(first)
    assert first.get("clarification"), first
    assert state["turn"] == 1, state
    project_id = str(first.get("project_id") or "")
    if not project_id:
        projects = store.list()
        project_id = str(projects[0]["id"])
    state["project_id"] = project_id
    assert store.get(project_id)["variants"] == []

    second = agent_chat(AgentChatRequest(
        message="宽5米高3米，坐标单位米，确认生成",
        mode="advanced",
        conversation_id=conversation,
        client_id="final-close",
        project_id=project_id,
    ))
    routes.append(second)
    assert second["ok"] is True, second
    assert store.get(project_id)["variants"] == []

    third = agent_chat(AgentChatRequest(
        message="确认生成",
        mode="advanced",
        conversation_id=conversation,
        client_id="final-close",
        project_id=project_id,
    ))
    assert third["ok"] is True, third
    variant = third.get("variant")
    assert isinstance(variant, dict), third
    assert third["candidate_visibility"]["status"] == "visible"
    binding = third["candidate_binding"]
    assert binding["project_id"] == project_id
    assert binding["variant_id"] == variant["id"]
    assert binding["run_id"] == third["agent_run_id"]
    assert candidate_is_accepted(variant) is True
    coverage = variant["construction_record"]["source_acceptance"]["coverage_evidence"]
    assert coverage["state"] == "complete"
    assert coverage["unresolved_fact_ids"] == []
    operation = next(
        item for item in coverage["clauses"] if item["requirement"] == "新建图纸"
    )
    assert operation["binding"]["drawing_write_proof"] == "first_candidate_write_in_commit"
    assert operation["binding"]["write_receipt"]["created"] is True

    saved = store.get(project_id)
    reloaded = next(item for item in saved["variants"] if item["id"] == variant["id"])
    assert geometry_evidence_hash(reloaded) == geometry_evidence_hash(variant)
    assert reloaded["acceptance_summary"]["status"] == "passed"


def test_formal_http_entry_keeps_draft_and_stale_candidates_non_deliverable(
    tmp_path, monkeypatch
):
    # A draft project with no variant may answer clarification, but it must not
    # expose a candidate before the first accepted write.
    store = CreativeProjectStore(tmp_path / "projects.json")
    memory = ConversationMemoryStore(tmp_path / "memory.json")
    monkeypatch.setattr(agent_service, "get_creative_project_store", lambda: store)
    monkeypatch.setattr(agent_http_service, "get_creative_project_store", lambda: store)
    monkeypatch.setattr(agent_http_service, "conversation_memory", memory)
    monkeypatch.setattr(agent_service, "conversation_memory", memory)
    monkeypatch.setattr(agent_service.robot_agent, "mode", "local")
    monkeypatch.setattr(agent_service.robot_agent, "api_keys", {})
    monkeypatch.setattr(
        agent_service.robot_agent,
        "resolve_intent",
        lambda *_args, **_kwargs: {
            "name": "drawing_design", "tool_family": "cad",
            "operation": "create", "decision_source": "frozen_http_draft",
        },
    )
    result = agent_chat(AgentChatRequest(
        message="新建图纸，画一个矩形",
        mode="advanced",
        conversation_id="cad-final-close-draft",
        client_id="final-close",
    ))
    assert result.get("clarification"), result
    assert result.get("candidate_visibility", {}).get("status") != "visible"
    assert result.get("variant") is None
    projects = store.list()
    assert projects and projects[0]["variants"] == []


def _patch_http(tmp_path, monkeypatch, frozen, route_factory):
    store = CreativeProjectStore(tmp_path / "projects.json")
    memory = ConversationMemoryStore(tmp_path / "memory.json")
    monkeypatch.setattr(agent_service, "get_creative_project_store", lambda: store)
    monkeypatch.setattr(agent_http_service, "get_creative_project_store", lambda: store)
    monkeypatch.setattr(agent_service, "conversation_memory", memory)
    monkeypatch.setattr(agent_http_service, "conversation_memory", memory)
    monkeypatch.setattr(agent_service.robot_agent, "mode", "local")
    monkeypatch.setattr(agent_service.robot_agent, "api_keys", {})
    monkeypatch.setattr(agent_service.robot_agent, "resolve_intent", route_factory)
    monkeypatch.setattr(agent_service.robot_agent, "route_intent", route_factory)
    monkeypatch.setattr(
        agent_service.robot_agent,
        "_interpret_cad_construction_plan",
        lambda _message, mode=None: deepcopy(frozen),
    )
    return store, memory


def test_formal_http_entry_does_not_expose_wrong_size_candidate(tmp_path, monkeypatch):
    source = "新建图纸，画一个宽5米高3米的矩形"
    frozen = interpret_construction_request(source)
    wrong = interpret_construction_request("新建图纸，画一个宽6米高3米的矩形")
    frozen["trial_result"] = deepcopy(wrong["trial_result"])
    frozen["plan"] = deepcopy(wrong.get("plan"))
    store, _memory = _patch_http(
        tmp_path, monkeypatch, frozen,
        lambda *_args, **_kwargs: {
            "name": "drawing_design", "tool_family": "cad",
            "operation": "create", "decision_source": "frozen_http_wrong_size",
        },
    )
    result = agent_chat(AgentChatRequest(
        message=source, mode="advanced",
        conversation_id="cad-final-close-wrong-size", client_id="final-close",
    ))
    variant = result.get("variant")
    assert variant is None
    assert result.get("candidate_visibility", {}).get("status") in {"hidden", "draft_review"}
    assert result.get("candidate_visibility", {}).get("status") != "visible"
    saved = store.get(str(result["project_id"]))
    assert saved["variants"][0]["acceptance_summary"]["status"] != "passed"


def test_formal_http_entry_cannot_reuse_existing_candidate_as_new_drawing(
    tmp_path, monkeypatch
):
    source = "新建图纸，画一个宽5米高3米的矩形"
    frozen = interpret_construction_request(source)
    state = {"project_id": None}

    def route(_message, _mode, _history=None):
        if state["project_id"]:
            return {
                "name": "drawing_design", "tool_family": "cad",
                "operation": "create", "stage": "candidate_generation",
                "selected_project_id": state["project_id"],
                "decision_source": "frozen_http_reused_candidate",
            }
        return {
            "name": "drawing_design", "tool_family": "cad",
            "operation": "create", "decision_source": "frozen_http_reused_candidate",
        }

    store, _memory = _patch_http(tmp_path, monkeypatch, frozen, route)
    logs = []
    monkeypatch.setattr(agent_http_service.robot_state, "add_log", lambda message: logs.append(message))
    first = agent_chat(AgentChatRequest(
        message=source, mode="advanced",
        conversation_id="cad-final-close-reuse", client_id="final-close",
    ))
    assert first["ok"] is True, (first, logs)
    assert first["candidate_visibility"]["status"] == "visible"
    state["project_id"] = str(first["project_id"])

    second = agent_chat(AgentChatRequest(
        message=source, mode="advanced",
        conversation_id="cad-final-close-reuse", client_id="final-close",
        project_id=state["project_id"],
    ))
    assert second["ok"] is not True, second
    assert second.get("candidate_visibility", {}).get("status") != "visible"
    assert "不能复用已有候选" in str(second.get("message") or "")
    assert len(store.get(state["project_id"])["variants"]) == 1
