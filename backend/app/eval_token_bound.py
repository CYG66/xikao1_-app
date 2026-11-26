"""Two-layer input-token accounting for evaluation requests.

Layer A (hard admission cap) must be a bound, not an estimate: it decides
whether a request may be sent.  Layer B (tokenizer estimate) is used only for
analysis and budget utilisation, never to admit a request.  Provider ``usage``
is the settlement authority.

Why the hard byte bound is valid
--------------------------------
Every token emitted by a byte-level tokenizer consumes at least one UTF-8 byte.
Therefore the UTF-8 byte length of the exact prompt text is an upper bound on
the number of prompt tokens, independent of vocabulary and merge rules.  The
hard bound here starts from the complete serialized request body (which already
contains every message, tool definition, model parameter and serialization
escape), then adds only bytes that the published chat template introduces
around that content.  The template skeleton is rendered with the real template
and empty message contents, so its marker bytes are counted structurally rather
than by an unexplained constant.  Tools are charged using their pretty-printed
JSON when that is larger than the compact body form.

This is deliberately conservative.  If the hard bound does not fit the ledger,
the case is not executed; the bound is never relaxed to make a case run.
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


def _protocol_marker_bytes(payload: dict[str, Any]) -> int:
    """Count published-template marker bytes without counting message content.

    The skeleton is produced by the same renderer used for real messages, with
    every content replaced by the empty string.  Its byte length is therefore
    the structural framing overhead, not an empirical token allowance.
    """

    messages = payload.get("messages")
    if not isinstance(messages, list):
        return 0
    skeleton_messages: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            return 0
        role = message.get("role")
        content = message.get("content")
        skeleton_messages.append(
            {
                "role": role,
                "content": (
                    None
                    if content is None and message.get("tool_calls")
                    else ""
                ),
                "tool_calls": message.get("tool_calls"),
            }
        )
    skeleton = _deepseek_chat_text({"messages": skeleton_messages})
    if skeleton is not None:
        marker_bytes = len(skeleton.encode("utf-8"))
    else:
        # Fallback: sum every marker that the published template can emit.
        markers = [
            "<｜begin▁of▁sentence｜>",
            "<｜User｜>",
            "<｜Assistant｜>",
            "<｜end▁of▁sentence｜>",
            "<｜tool▁outputs▁begin｜>",
            "<｜tool▁outputs▁end｜>",
            "<｜tool▁output▁begin｜>",
            "<｜tool▁output▁end｜>",
        ]
        marker_bytes = sum(len(marker.encode("utf-8")) for marker in markers)
    tools = payload.get("tools")
    if isinstance(tools, list) and tools:
        marker_bytes += len("<｜tools▁begin｜><｜tools▁end｜>".encode("utf-8"))
    return marker_bytes


def protocol_envelope_units(payload: dict[str, Any]) -> int:
    """Compatibility name for the structural protocol marker byte count."""

    return _protocol_marker_bytes(payload)


def _extra_pretty_tool_bytes(payload: dict[str, Any]) -> int:
    """Additional bytes if the provider pretty-prints the tool definitions."""

    tools = payload.get("tools")
    if not isinstance(tools, list) or not tools:
        return 0
    compact = json.dumps(tools, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    pretty = json.dumps(tools, ensure_ascii=False, indent=2).encode("utf-8")
    return max(0, len(pretty) - len(compact))


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


def _tokenizer_evidence(payload: dict[str, Any], body: bytes) -> dict[str, Any] | None:
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
        "count": chat_count + tools_bytes,
    }


def _hard_bound_details(payload: dict[str, Any]) -> dict[str, Any]:
    body = serialized_request_body(payload)
    protocol_bytes = _protocol_marker_bytes(payload)
    extra_tools = _extra_pretty_tool_bytes(payload)
    byte_hard = len(body) + protocol_bytes + extra_tools
    tokenizer = _tokenizer_evidence(payload, body)
    estimate = (
        int(tokenizer["count"])
        if tokenizer
        and tokenizer.get("available")
        and tokenizer.get("count") is not None
        else None
    )
    # The tokenizer estimate is evidence, never the admission authority.  Max
    # keeps the admission bound valid even if a template branch makes the
    # published-tokenizer count exceed the byte calculation.
    hard = max(byte_hard, int(estimate or 0))
    return {
        "body": body,
        "body_bytes": len(body),
        "protocol_bytes": protocol_bytes,
        "extra_pretty_tool_bytes": extra_tools,
        "byte_hard": byte_hard,
        "estimate": estimate,
        "hard": hard,
        "tokenizer": tokenizer,
    }


def tokenizer_input_token_estimate(payload: dict[str, Any]) -> int:
    """Layer B: fine-grained tokenizer estimate for analysis and Mock runs.

    This value must never be used to admit a real evaluation request.
    """

    details = _hard_bound_details(payload)
    if details["estimate"] is not None:
        return int(details["estimate"])
    return int(details["byte_hard"])


def input_token_upper_bound(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the Layer-A hard bound and the Layer-B tokenizer estimate."""

    details = _hard_bound_details(payload)
    return {
        "schema": "p1.3-input-token-upper-bound.v2",
        "upper_bound": int(details["hard"]),
        "hard_upper_bound": int(details["hard"]),
        "estimate_upper_bound": (
            int(details["estimate"]) if details["estimate"] is not None else None
        ),
        "body_bytes": int(details["body_bytes"]),
        "body_sha256": hashlib.sha256(details["body"]).hexdigest(),
        "protocol_envelope_units": int(details["protocol_bytes"]),
        "extra_pretty_tool_bytes": int(details["extra_pretty_tool_bytes"]),
        "message_count": len(payload.get("messages") or [])
        if isinstance(payload.get("messages"), list)
        else 0,
        "tool_count": len(payload.get("tools") or [])
        if isinstance(payload.get("tools"), list)
        else 0,
        "tokenizer": details["tokenizer"],
        "basis": (
            "utf8-byte upper bound for the complete request body + published-"
            "template marker bytes + pretty-tool serialization delta; every "
            "token consumes at least one byte. Layer B tokenizer count is "
            "analysis-only."
        ),
    }
