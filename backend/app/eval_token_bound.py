"""Conservative input-token upper bound for evaluation requests.

The evaluation ledger must never reserve less than the provider can bill.  The
old ``len(json_bytes) // 4`` heuristic is removed: it is an estimate, not a
bound.  This module uses a strict byte bound for the complete serialized
request body plus a small, structurally derived protocol envelope.

Why the byte bound is valid
---------------------------
Every token produced by a byte-level BPE tokenizer consumes at least one UTF-8
byte.  Therefore ``len(body.encode("utf-8"))`` is an upper bound on the number
of tokens the tokenizer can emit for the body itself, regardless of vocabulary
or merge rules.  JSON syntax, system prompts, messages, tool schemas and
serialization escaping are all inside that body.

The chat protocol adds role separators and special tokens that are not present
in the JSON body.  The DeepSeek W5 chat template (shipped in
``tokenizer_config.json``) is applied verbatim to the message list and then
tokenized with the target tokenizer.  Tool definitions are not rendered by that
template, so their complete JSON is charged at one token per UTF-8 byte, which
is a strict upper bound for any byte-level tokenizer.  A fixed 128-token
wrapper covers the request-level special tokens and any provider-side wrapper
that is not represented in the published template.  If the template cannot be
applied (for example an unsupported assistant tool-call shape), the code falls
back to the complete-body UTF-8 byte bound rather than guessing.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

_TOKENIZER_CACHE: dict[str, Any] = {}
_TOKENIZER_LOCK = threading.Lock()


def serialized_request_body(payload: dict[str, Any]) -> bytes:
    """Return the largest serialization the supported senders may produce.

    DeepSeek sends ``ensure_ascii=False``; the OpenAI gateway sends the default
    ``ensure_ascii=True``.  Taking the larger byte representation makes the
    bound valid for both boundaries.
    """

    compact = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    escaped = json.dumps(payload).encode("utf-8")
    return compact if len(compact) >= len(escaped) else escaped


def protocol_envelope_units(payload: dict[str, Any]) -> int:
    """Structural allowance for chat-template special tokens and framing."""

    messages = payload.get("messages")
    tools = payload.get("tools")
    message_count = len(messages) if isinstance(messages, list) else 0
    tool_count = len(tools) if isinstance(tools, list) else 0
    return 32 * (message_count + tool_count + 2) + 128


def _deepseek_chat_text(payload: dict[str, Any]) -> str | None:
    """Render the published DeepSeek W5 chat template for its messages.

    Returns ``None`` when a message shape is outside the template's documented
    branches, so callers can use the byte bound instead of an approximation.
    """

    messages = payload.get("messages")
    if not isinstance(messages, list):
        return None
    system_parts: list[str] = []
    for message in messages:
        if isinstance(message, dict) and message.get("role") == "system":
            content = message.get("content")
            if content is not None and not isinstance(content, str):
                return None
            system_parts.append(str(content or ""))
    text = "<｜begin▁of▁sentence｜>" + "\n\n".join(system_parts)
    is_tool = False
    for message in messages:
        if not isinstance(message, dict):
            return None
        role = message.get("role")
        content = message.get("content")
        if role == "system":
            continue
        if content is not None and not isinstance(content, str):
            return None
        if role == "user":
            if content is None:
                return None
            is_tool = False
            text += "<｜User｜>" + str(content)
        elif role == "assistant":
            if content is None:
                # Tool-call assistant turns use a nested branch.  The body
                # contains the whole call; use the strict byte fallback rather
                # than trying to reconstruct provider-specific formatting.
                return None
            if is_tool:
                text += "<｜tool▁outputs▁end｜>" + str(content) + "<｜end▁of▁sentence｜>"
                is_tool = False
            else:
                text += "<｜Assistant｜>" + str(content) + "<｜end▁of▁sentence｜>"
        elif role == "tool":
            if content is None:
                return None
            is_tool = True
            text += "<｜tool▁outputs▁begin｜><｜tool▁output▁begin｜>" + str(content) + "<｜tool▁output▁end｜>"
        else:
            return None
    if is_tool:
        text += "<｜tool▁outputs▁end｜>"
    return text



def _tokenizer(path: Path) -> dict[str, Any] | None:
    key = str(path.resolve())
    with _TOKENIZER_LOCK:
        cached = _TOKENIZER_CACHE.get(key)
        if cached is not None:
            return cached
        if not path.is_file():
            return {
                "path": str(path),
                "available": False,
                "error": "tokenizer_file_missing",
            }
        try:
            from tokenizers import Tokenizer  # type: ignore

            tokenizer = Tokenizer.from_file(str(path))
        except Exception as error:  # noqa: BLE001 - evidence must survive any import
            return {
                "path": str(path),
                "available": False,
                "error": f"{type(error).__name__}: {error}",
            }
        value = {
            "path": str(path),
            "available": True,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "tokenizer": tokenizer,
        }
        _TOKENIZER_CACHE[key] = value
        return value


def _count(tokenizer: Any, text: str) -> int:
    return len(tokenizer.encode(text).ids)


def _tokenizer_upper_bound(payload: dict[str, Any], body: bytes) -> dict[str, Any] | None:
    path_text = os.getenv("P12_TOKENIZER_JSON", "").strip()
    if not path_text:
        return None
    loaded = _tokenizer(Path(path_text))
    if not loaded or not loaded.get("available"):
        return loaded
    tokenizer = loaded["tokenizer"]
    body_count = _count(tokenizer, body.decode("utf-8"))
    chat_text = _deepseek_chat_text(payload)
    if chat_text is None:
        return {
            "path": loaded["path"],
            "available": True,
            "sha256": loaded["sha256"],
            "body_count": body_count,
            "count": None,
            "fallback": "byte_bound_unsupported_message_shape",
        }
    chat_count = _count(tokenizer, chat_text)
    tools = payload.get("tools")
    tool_payload = tools if isinstance(tools, list) else []
    tools_compact = json.dumps(tool_payload, ensure_ascii=False).encode("utf-8")
    tools_escaped = json.dumps(tool_payload).encode("utf-8")
    tools_bytes = max(len(tools_compact), len(tools_escaped))
    return {
        "path": loaded["path"],
        "available": True,
        "sha256": loaded["sha256"],
        "body_count": body_count,
        "chat_count": chat_count,
        "tool_count": len(tool_payload),
        "tool_bytes_upper_bound": tools_bytes,
        "count": chat_count + tools_bytes + 128,
    }

def input_token_upper_bound(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a conservative bound and the evidence used to derive it."""

    body = serialized_request_body(payload)
    protocol_units = protocol_envelope_units(payload)
    tokenizer = _tokenizer_upper_bound(payload, body)
    tokenizer_units = (
        int(tokenizer["count"]) if tokenizer and tokenizer.get("available") and tokenizer.get("count") is not None else 0
    )
    if tokenizer_units:
        upper = tokenizer_units
        basis = (
            "published DeepSeek W5 chat template tokenized with the target "
            "tokenizer; tool JSON charged at one token per UTF-8 byte; fixed "
            "128-token request wrapper"
        )
    else:
        upper = len(body) + protocol_units
        basis = (
            "utf8-byte upper bound for the complete serialized body + "
            "structural chat-protocol envelope; tokenizer count, when present, "
            "is evidence only and never lowers the bound"
        )
    return {
        "schema": "p1.3-input-token-upper-bound.v1",
        "upper_bound": int(upper),
        "body_bytes": len(body),
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "protocol_envelope_units": int(protocol_units),
        "message_count": len(payload.get("messages") or [])
        if isinstance(payload.get("messages"), list)
        else 0,
        "tool_count": len(payload.get("tools") or [])
        if isinstance(payload.get("tools"), list)
        else 0,
        "tokenizer": tokenizer,
        "basis": basis,
    }
