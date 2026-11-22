"""FINAL-01: integration profile must override every user model path."""
from __future__ import annotations

import json

import pytest
from urllib.request import Request

from app.agent_service import RobotAgentService
from app.deepseek_transport import DeepSeekTransport
from app.integration_profile import (
    ISOLATION_ROOT_ENV,
    IntegrationProfileError,
    require_external_model_calls_permitted,
)
from app.model_providers import provider_adapter
from app.request_context import agent_user_scope
from app.user_model_config import UserModelConfigStore


OWNER = "final01-owner"
FAKE_KEY = "sk-final01-fake-key"


def _enable_profile(tmp_path, monkeypatch):
    root = tmp_path / "iso"
    root.mkdir()
    monkeypatch.setenv("XLINE_INTEGRATION_PROFILE", "1")
    monkeypatch.setenv(ISOLATION_ROOT_ENV, str(root))
    return root


def _history_store(tmp_path):
    path = tmp_path / "history-users.json"
    path.write_text(
        json.dumps(
            {
                "profiles": {
                    OWNER: {
                        "mode": "deepseek",
                        "model": "deepseek-chat",
                        "base_model": "deepseek-chat",
                        "advanced_model": "deepseek-reasoner",
                        "cad_planning_model": "deepseek-reasoner",
                        "api_keys": {"deepseek": FAKE_KEY},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return UserModelConfigStore(path)


def _service(tmp_path, monkeypatch):
    _enable_profile(tmp_path, monkeypatch)
    store = _history_store(tmp_path)
    with pytest.MonkeyPatch.context() as patch_scope:
        patch_scope.setattr("app.agent_service.user_model_config", store)
        with agent_user_scope(OWNER):
            service = RobotAgentService(restore_pending_actions=False)
    return service, store


def test_user_level_configuration_cannot_override_effective_local_mode(
    tmp_path, monkeypatch
):
    service, store = _service(tmp_path, monkeypatch)
    with agent_user_scope(OWNER):
        assert store.get(OWNER)["mode"] == "deepseek"
        assert service._active_user_profile is None
        assert service.mode == "local"
        assert service.model == "local"
        assert service.base_model == "local"
        assert service.advanced_model == "local"
        assert service.cad_planning_model == "local"
        assert service.api_keys == {}
        assert service.api_key == ""
        assert service.configured is True


def test_production_user_store_is_not_read_under_profile(tmp_path, monkeypatch):
    root = _enable_profile(tmp_path, monkeypatch)
    production = tmp_path / "production-users.json"
    production.write_text(
        json.dumps({"profiles": {OWNER: {"mode": "deepseek", "api_keys": {"deepseek": FAKE_KEY}}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("XLINE_AGENT_USER_CONFIG_PATH", str(production))
    store = UserModelConfigStore()
    assert store.path == root / "xline-agent-users.json"
    assert store.get(OWNER) is None


def test_test_connection_does_not_touch_network(tmp_path, monkeypatch):
    service, _ = _service(tmp_path, monkeypatch)
    calls: list[str] = []

    def network(*args, **kwargs):
        calls.append("urlopen")
        raise AssertionError("network must not be reached")

    monkeypatch.setattr("app.agent_service.urllib.request.urlopen", network)
    with agent_user_scope(OWNER):
        result = service.test_connection()
    assert result["ok"] is True
    assert result["message"].startswith("集成验证 profile")
    assert calls == []


def test_deepseek_transport_and_service_block_before_socket(tmp_path, monkeypatch):
    service, _ = _service(tmp_path, monkeypatch)
    calls: list[str] = []

    def network(*args, **kwargs):
        calls.append("HTTPSConnection")
        raise AssertionError("network must not be reached")

    monkeypatch.setattr("app.deepseek_transport.http.client.HTTPSConnection", network)
    transport = DeepSeekTransport(api_key=FAKE_KEY, timeout_for=lambda _kind, default: default)
    with pytest.raises(IntegrationProfileError, match="禁止外部模型请求"):
        transport.open({"model": "deepseek-chat", "messages": []})
    with agent_user_scope(OWNER):
        with pytest.raises(IntegrationProfileError, match="禁止外部模型请求"):
            service._deepseek_request([{"role": "user", "content": "hi"}], tools=[])
    assert calls == []


def test_provider_adapter_compatible_and_structured_paths_block_before_send(
    tmp_path, monkeypatch
):
    service, _ = _service(tmp_path, monkeypatch)
    calls: list[str] = []

    def network(*args, **kwargs):
        calls.append("urlopen")
        raise AssertionError("network must not be reached")

    monkeypatch.setattr("app.model_providers.urllib.request.urlopen", network)
    monkeypatch.setattr("app.agent_service.urllib.request.urlopen", network)
    with pytest.raises(IntegrationProfileError, match="禁止外部模型请求"):
        provider_adapter("deepseek").send_json(
            Request("https://api.deepseek.com/chat/completions"), timeout=1.0
        )
    with agent_user_scope(OWNER):
        with pytest.raises(IntegrationProfileError, match="禁止外部模型请求"):
            service._compatible_chat("hi", [], mode="base")
        with pytest.raises(IntegrationProfileError, match="禁止外部模型请求"):
            service._structured_review_text([], mode="base")
    assert calls == []


def test_gateway_and_credential_update_fail_closed(tmp_path, monkeypatch):
    service, store = _service(tmp_path, monkeypatch)
    from app import model_request_gateway as gateway

    calls: list[str] = []

    def network(*args, **kwargs):
        calls.append("urlopen")
        raise AssertionError("network must not be reached")

    monkeypatch.setattr("app.model_request_gateway.urllib.request.urlopen", network)
    with pytest.raises(IntegrationProfileError, match="禁止外部模型请求"):
        gateway.request_provider_tool_json(
            "deepseek",
            model="deepseek-chat",
            api_key=FAKE_KEY,
            payload={},
            timeout=1.0,
        )
    with pytest.raises(IntegrationProfileError, match="禁止外部模型请求"):
        gateway.request_openai_responses_json(
            api_key=FAKE_KEY,
            payload={},
            timeout=1.0,
        )
    with pytest.raises(IntegrationProfileError, match="禁止修改或启用外部模型配置"):
        service.update_config("deepseek", "deepseek-chat", api_key=FAKE_KEY)
    with pytest.raises(IntegrationProfileError, match="用户级模型配置"):
        with agent_user_scope(OWNER):
            store.update(OWNER, mode="deepseek", model="deepseek-chat", api_key=FAKE_KEY)
    assert calls == []


def test_profile_off_preserves_multi_user_behavior(tmp_path, monkeypatch):
    monkeypatch.delenv("XLINE_INTEGRATION_PROFILE", raising=False)
    store = _history_store(tmp_path)
    with pytest.MonkeyPatch.context() as patch_scope:
        patch_scope.setattr("app.agent_service.user_model_config", store)
        patch_scope.setattr(RobotAgentService, "_load_config", lambda self: None)
        with agent_user_scope(OWNER):
            service = RobotAgentService(restore_pending_actions=False)
            assert service.mode == "deepseek"
            assert service.model == "deepseek-chat"
            assert service.advanced_model == "deepseek-chat"
            assert service.cad_planning_model == "deepseek-reasoner"
            assert service.api_keys == {"deepseek": FAKE_KEY}
            assert service.api_key == FAKE_KEY


def test_require_external_model_calls_is_a_noop_when_profile_is_off(monkeypatch):
    monkeypatch.delenv("XLINE_INTEGRATION_PROFILE", raising=False)
    require_external_model_calls_permitted()
