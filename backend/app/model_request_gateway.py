"""Shared model-provider request boundary.

The gateway owns network admission and provider dispatch. Agent orchestration
builds prompts and interprets replies, but does not manage per-user leases or
know which concrete adapter sends a request.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any

from .agent_service_config import PROVIDERS
from .eval_request_guard import (
    begin_eval_request,
    fail_eval_request,
    settle_eval_response,
)
from .integration_profile import require_external_model_calls_permitted
from .model_providers import provider_adapter
from .request_context import current_agent_user_id
from .user_request_limits import user_request_limiter


def request_provider_tool_json(
    provider: str,
    *,
    model: str,
    api_key: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    """Send one tool-capable request under the current user's request lease."""
    require_external_model_calls_permitted()
    if provider not in PROVIDERS:
        raise ValueError(f"Unsupported model provider: {provider}")
    _provider_name, base_url = PROVIDERS[provider]
    lease = user_request_limiter.acquire(current_agent_user_id())
    lease.__enter__()
    try:
        return provider_adapter(provider).request_tool_json(
            base_url=base_url,
            model=model,
            api_key=api_key,
            payload=payload,
            timeout=timeout,
        )
    finally:
        lease.__exit__(None, None, None)


def request_openai_responses_json(
    *,
    api_key: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    """Send one OpenAI Responses request under the shared user limit."""
    require_external_model_calls_permitted()
    target_url = "https://api.openai.com/v1/responses"
    reservation = begin_eval_request(
        provider="openai",
        model=str(payload.get("model") or ""),
        target_url=target_url,
        payload=payload,
        max_output_tokens=int(payload.get("max_output_tokens", 0) or 0),
    )
    request = urllib.request.Request(
        target_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    lease = user_request_limiter.acquire(current_agent_user_id())
    lease.__enter__()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
            status = int(getattr(response, "status", 200))
        settle_eval_response(reservation, result, http_status=status)
        return result
    except urllib.error.HTTPError as error:
        fail_eval_request(reservation, error)
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"OpenAI API 请求失败 ({error.code}): {detail[:300]}"
        ) from error
    except (TimeoutError, socket.timeout) as error:
        fail_eval_request(reservation, error)
        raise RuntimeError("OpenAI API 请求超时，请稍后重试。") from error
    except urllib.error.URLError as error:
        fail_eval_request(reservation, error)
        raise RuntimeError(f"无法连接 OpenAI API: {error.reason}") from error
    except json.JSONDecodeError as error:
        fail_eval_request(reservation, error)
        raise RuntimeError("OpenAI API 返回了无效 JSON。") from error
    finally:
        lease.__exit__(None, None, None)
