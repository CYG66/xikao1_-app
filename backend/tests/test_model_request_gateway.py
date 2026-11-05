from unittest.mock import MagicMock, patch

import pytest

from app.model_request_gateway import request_provider_tool_json
from app.model_request_gateway import request_openai_responses_json


def test_gateway_dispatches_under_current_user_lease() -> None:
    lease = MagicMock()
    adapter = MagicMock()
    adapter.request_tool_json.return_value = {"ok": True}
    with (
        patch(
            "app.model_request_gateway.current_agent_user_id",
            return_value="user-7",
        ),
        patch(
            "app.model_request_gateway.user_request_limiter.acquire",
            return_value=lease,
        ) as acquire,
        patch("app.model_request_gateway.provider_adapter", return_value=adapter),
    ):
        result = request_provider_tool_json(
            "gemini",
            model="gemini-test",
            api_key="secret",
            payload={"contents": []},
            timeout=12.0,
        )

    assert result == {"ok": True}
    acquire.assert_called_once_with("user-7")
    lease.__enter__.assert_called_once_with()
    lease.__exit__.assert_called_once_with(None, None, None)
    adapter.request_tool_json.assert_called_once()


def test_gateway_rejects_unknown_provider_before_acquiring_lease() -> None:
    with (
        patch("app.model_request_gateway.user_request_limiter.acquire") as acquire,
        pytest.raises(ValueError, match="Unsupported model provider"),
    ):
        request_provider_tool_json(
            "unknown",
            model="model",
            api_key="secret",
            payload={},
            timeout=1.0,
        )
    acquire.assert_not_called()


def test_openai_responses_uses_same_user_lease_and_timeout() -> None:
    lease = MagicMock()
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b'{"output": [], "usage": {}}'
    with (
        patch(
            "app.model_request_gateway.current_agent_user_id",
            return_value="user-8",
        ),
        patch(
            "app.model_request_gateway.user_request_limiter.acquire",
            return_value=lease,
        ) as acquire,
        patch(
            "app.model_request_gateway.urllib.request.urlopen",
            return_value=response,
        ) as urlopen,
    ):
        result = request_openai_responses_json(
            api_key="secret",
            payload={"model": "gpt-test", "input": []},
            timeout=19.0,
        )

    assert result == {"output": [], "usage": {}}
    acquire.assert_called_once_with("user-8")
    assert urlopen.call_args.kwargs["timeout"] == 19.0
    request = urlopen.call_args.args[0]
    assert request.full_url == "https://api.openai.com/v1/responses"
    assert b"secret" not in request.data
    lease.__exit__.assert_called_once_with(None, None, None)
