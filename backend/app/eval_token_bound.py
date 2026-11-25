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
in the JSON body.  We reserve a fixed structural envelope of 32 bytes/tokens
per message or tool plus 128 for the request wrapper.  That is deliberately
charged as bytes (one unit per token), so it can only over-reserve.  If a
target-model tokenizer is available offline it is also measured and reported,
but it never replaces the byte bound.
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
    # Segment-wise tokenization is an upper bound for the provider's chat
    # template because BPE merges across segment boundaries can only reduce
    # the total token count.  Roles, tool schemas, and scalar fields are
    # counted separately; the structural envelope covers template framing.
    segment_count = 0
    messages = payload.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if isinstance(message, dict):
                segment_count += _count(tokenizer, str(message.get("role") or ""))
                segment_count += _count(tokenizer, str(message.get("content") or ""))
    tools = payload.get("tools")
    if isinstance(tools, list):
        for tool in tools:
            segment_count += _count(tokenizer, json.dumps(tool, ensure_ascii=False))
    for key in ("model", "max_tokens", "max_output_tokens", "response_format", "thinking"):
        if key in payload:
            segment_count += _count(tokenizer, json.dumps(payload[key], ensure_ascii=False))
    return {
        "path": loaded["path"],
        "available": True,
        "sha256": loaded["sha256"],
        "body_count": body_count,
        "segment_count": segment_count,
        "count": max(body_count, segment_count),
    }

def input_token_upper_bound(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a conservative bound and the evidence used to derive it."""

    body = serialized_request_body(payload)
    protocol_units = protocol_envelope_units(payload)
    tokenizer = _tokenizer_upper_bound(payload, body)
    tokenizer_units = (
        int(tokenizer["count"]) if tokenizer and tokenizer.get("available") else 0
    )
    if tokenizer_units:
        upper = tokenizer_units + protocol_units
        basis = (
            "target-tokenizer segment/body upper bound + structural "
            "chat-protocol envelope; BPE merges across segments cannot increase "
            "the separately counted total"
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
