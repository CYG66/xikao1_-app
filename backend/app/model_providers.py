from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
import urllib.error
import urllib.request
from urllib.request import Request


@dataclass(frozen=True)
class ProviderReply:
    text: str
    input_tokens: int
    output_tokens: int

    @property
    def usage(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
        }


class ModelProviderAdapter:
    name: str

    def build_request(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> Request:
        raise NotImplementedError

    def parse_reply(self, payload: dict[str, Any]) -> ProviderReply:
        raise NotImplementedError

    def build_tool_request(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        payload: dict[str, Any],
    ) -> Request:
        raise NotImplementedError

    def request_tool_json(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        payload: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        """Send one native tool-agent request through the provider adapter."""
        request = self.build_tool_request(
            base_url=base_url,
            model=model,
            api_key=api_key,
            payload=payload,
        )
        return self.send_json(request, timeout=timeout)

    def send_json(self, request: Request, *, timeout: float) -> dict[str, Any]:
        """Send a previously built provider request and decode its JSON body."""
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(
                f"{self.name} API 请求失败（{error.code}）：{detail}"
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise RuntimeError(f"无法连接 {self.name}：{error}") from error
        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"{self.name} API 返回了无效 JSON。") from error


class OpenAICompatibleAdapter(ModelProviderAdapter):
    def __init__(self, name: str) -> None:
        self.name = name

    def build_request(self, *, base_url: str, model: str, api_key: str,
                      system: str, messages: list[dict[str, str]],
                      max_tokens: int) -> Request:
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system}, *messages],
            "max_tokens": max_tokens,
        }
        return Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

    def parse_reply(self, payload: dict[str, Any]) -> ProviderReply:
        choices = payload.get("choices") or []
        message = choices[0].get("message", {}) if choices else {}
        raw_usage = payload.get("usage") or {}
        return ProviderReply(
            text=str(message.get("content") or ""),
            input_tokens=int(raw_usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(raw_usage.get("completion_tokens", 0) or 0),
        )

    def build_tool_request(self, *, base_url: str, model: str, api_key: str,
                           payload: dict[str, Any]) -> Request:
        return Request(
            f"{base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Connection": "close",
            },
            method="POST",
        )


class AnthropicAdapter(ModelProviderAdapter):
    name = "anthropic"

    def build_request(self, *, base_url: str, model: str, api_key: str,
                      system: str, messages: list[dict[str, str]],
                      max_tokens: int) -> Request:
        payload = {
            "model": model,
            "system": system,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        return Request(
            f"{base_url}/messages",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            method="POST",
        )

    def parse_reply(self, payload: dict[str, Any]) -> ProviderReply:
        text = "".join(str(item.get("text") or "") for item in payload.get("content", []))
        usage = payload.get("usage") or {}
        return ProviderReply(
            text=text,
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
        )

    def build_tool_request(self, *, base_url: str, model: str, api_key: str,
                           payload: dict[str, Any]) -> Request:
        return Request(
            f"{base_url.rstrip('/')}/messages",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Connection": "close",
            },
            method="POST",
        )


class GeminiAdapter(ModelProviderAdapter):
    name = "gemini"

    def build_request(self, *, base_url: str, model: str, api_key: str,
                      system: str, messages: list[dict[str, str]],
                      max_tokens: int) -> Request:
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [
                {
                    "role": "model" if item["role"] == "assistant" else "user",
                    "parts": [{"text": item["content"]}],
                }
                for item in messages
            ],
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        return Request(
            f"{base_url.rstrip('/')}/models/{model}:generateContent",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )

    def build_tool_request(self, *, base_url: str, model: str, api_key: str,
                           payload: dict[str, Any]) -> Request:
        return Request(
            f"{base_url.rstrip('/')}/models/{model}:generateContent",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "x-goog-api-key": api_key,
                "Connection": "close",
            },
            method="POST",
        )

    def parse_reply(self, payload: dict[str, Any]) -> ProviderReply:
        candidates = payload.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        text = "".join(str(item.get("text") or "") for item in parts)
        usage = payload.get("usageMetadata") or {}
        return ProviderReply(
            text=text,
            input_tokens=int(usage.get("promptTokenCount", 0) or 0),
            output_tokens=int(usage.get("candidatesTokenCount", 0) or 0),
        )


def provider_adapter(name: str) -> ModelProviderAdapter:
    if name == "anthropic":
        return AnthropicAdapter()
    if name == "gemini":
        return GeminiAdapter()
    return OpenAICompatibleAdapter(name)
