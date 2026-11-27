"""Fail-closed admission guard at evaluation model network boundaries.

Production behavior is unchanged: outside ``P12_EVAL_MODE=1`` the guard only
calls the existing external-profile check.  In evaluation mode every actual
network send must be explicitly authorized, pinned to the frozen provider/model
and backed by a configured budget ledger.

The guard is deliberately configured only by the formal HTTP evaluation entry
(``cad_widget_live_worker.py``).  Legacy evaluation scripts do not configure it,
so any inherited ``P12_EVAL_BUDGET_PATH`` cannot accidentally open them.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .eval_token_bound import input_token_upper_bound, tokenizer_input_token_estimate
from .integration_profile import require_external_model_calls_permitted


DEFAULT_EXPECTED_PROVIDER = "deepseek"
DEFAULT_EXPECTED_MODEL = "deepseek-flash"
AUTHORIZED_TARGETS = {
    "deepseek": "https://api.deepseek.com/chat/completions",
}
RESPONSE_MODEL_ALLOWLIST = {
    "deepseek": frozenset({"deepseek-flash"}),
}
CALIBRATION_CASE_IDS = frozenset({"C7", "L02-C7"})
CALIBRATION_MESSAGE_ROLES = ("system", "user")
CALIBRATION_MAX_OUTPUT_TOKENS = 8192


class EvalRequestBlocked(RuntimeError):
    """Raised before any request bytes reach the network."""

    eval_fatal = True


class ModelAuthorizationError(EvalRequestBlocked):
    """Raised when a provider/model/target is not the frozen evaluation pair."""


def is_eval_fatal(error: BaseException | str | None) -> bool:
    """Return True when an exception must terminate the whole evaluation.

    The marker is an exception attribute, not inheritance from BaseException,
    so production business handlers keep working normally.  Cause/context are
    inspected as evidence in case a caller wrapped the original error.
    """

    seen: set[int] = set()
    current: BaseException | None = error if isinstance(error, BaseException) else None
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if bool(getattr(current, "eval_fatal", False)):
            return True
        current = current.__cause__ or current.__context__
    return False


@dataclass
class EvalReservation:
    request_id: str
    provider: str
    model: str
    target_url: str
    input_upper_bound: int
    output_tokens: int
    max_output_tokens: int
    ledger: Any
    settled: bool = False


_lock = threading.Lock()
_ledger: Any = None
_configured = False


def eval_mode_enabled() -> bool:
    return os.getenv("P12_EVAL_MODE") == "1"


def configure_eval_guard(ledger: Any) -> None:
    """Install the ledger used by all app-level network boundaries."""

    global _ledger, _configured
    with _lock:
        _ledger = ledger
        _configured = True


def reset_eval_guard() -> None:
    """Test helper; production never calls this."""

    global _ledger, _configured
    with _lock:
        _ledger = None
        _configured = False


def expected_provider() -> str:
    return os.getenv("P12_EXPECTED_PROVIDER", DEFAULT_EXPECTED_PROVIDER).strip()


def expected_model() -> str:
    return os.getenv("P12_EXPECTED_MODEL", DEFAULT_EXPECTED_MODEL).strip()


def require_eval_not_aborted() -> None:
    """Stop a case before it starts, or after a fatal transition."""

    if not eval_mode_enabled():
        return
    if not _configured or _ledger is None:
        raise EvalRequestBlocked("evaluation_budget_unavailable")
    snapshot = _ledger.snapshot()
    if snapshot.get("stopped") or snapshot.get("pending"):
        raise EvalRequestBlocked("evaluation_aborted_by_ledger")


def _authorized_target(provider: str) -> str:
    return AUTHORIZED_TARGETS.get(provider, "")


def _normalized_url(url: str) -> str:
    parsed = urlparse(url)
    return (
        f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if parsed.scheme and parsed.netloc
        else ""
    )


def _require_eval_context(
    provider: str,
    model: str,
    target_url: str,
    *,
    require_authorization: bool = True,
) -> None:
    if not eval_mode_enabled():
        return
    if os.getenv("P12_EVAL_FORMAL_HTTP") != "1":
        raise EvalRequestBlocked("evaluation_formal_entry_required")
    if require_authorization and os.getenv("P12_REAL_MODEL_AUTHORIZED") != "1":
        raise EvalRequestBlocked("real_model_not_authorized")
    if not _configured or _ledger is None:
        raise EvalRequestBlocked("evaluation_budget_unavailable")
    authorized_provider = expected_provider()
    if provider != authorized_provider:
        raise ModelAuthorizationError(
            f"provider_not_authorized:{provider}!={authorized_provider}"
        )
    authorized_model = expected_model()
    if model != authorized_model:
        raise ModelAuthorizationError(
            f"model_not_authorized:{model}!={authorized_model}"
        )
    allowed_url = _authorized_target(provider)
    if not allowed_url or _normalized_url(target_url) != allowed_url:
        raise ModelAuthorizationError(
            f"target_not_authorized:{_normalized_url(target_url)}!={allowed_url}"
        )


def _validate_model_parameters(payload: dict[str, Any], max_output_tokens: int) -> None:
    model = payload.get("model")
    if model != expected_model():
        raise ModelAuthorizationError(
            f"payload_model_not_authorized:{model}!={expected_model()}"
        )
    if max_output_tokens < 1:
        raise EvalRequestBlocked("invalid_output_reservation")
    if max_output_tokens > 32768:
        raise EvalRequestBlocked("output_reservation_above_protocol_cap")
    if payload.get("n") not in (None, 1):
        raise EvalRequestBlocked("multiple_choices_not_permitted")
    if payload.get("stream") not in (None, True, False):
        raise EvalRequestBlocked("invalid_stream_flag")


def calibration_mode_enabled() -> bool:
    return os.getenv("P12_EVAL_CALIBRATION_MODE") == "1"


def _payload_fingerprint(payload: dict[str, Any]) -> tuple[str, int]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(body).hexdigest(), len(body)


def _validate_calibration_request(payload: dict[str, Any], max_output_tokens: int) -> None:
    """Reject anything but the frozen C7 first request, before the network.

    Calibration is a one-request mode: it must be the C7 case, exactly one
    system message plus one user message, plain text, no tools/tool calls,
    thinking explicitly disabled, non-streaming and no larger than the frozen
    output reservation.  The payload fingerprint pins the actual bytes, so a
    reworded system prompt or a changed tool table cannot slip through.
    """

    case_id = os.getenv("P12_EVAL_CASE_ID", "").strip()
    if case_id not in CALIBRATION_CASE_IDS:
        raise EvalRequestBlocked(f"calibration_case_not_allowed:{case_id or '<missing>'}")

    messages = payload.get("messages")
    if not isinstance(messages, list) or len(messages) != len(CALIBRATION_MESSAGE_ROLES):
        raise EvalRequestBlocked("calibration_message_count_mismatch")
    if not all(isinstance(item, dict) for item in messages):
        raise EvalRequestBlocked("calibration_message_shape_not_permitted")
    actual_roles = tuple(str(item.get("role") or "") for item in messages)
    if actual_roles != CALIBRATION_MESSAGE_ROLES:
        raise EvalRequestBlocked(
            "calibration_message_roles_mismatch:" + ",".join(actual_roles)
        )
    for item in messages:
        if not isinstance(item, dict) or not isinstance(item.get("content"), str):
            raise EvalRequestBlocked("calibration_non_text_message_not_permitted")
        if item.get("tool_calls") or item.get("function_call") or item.get("tool_call_id"):
            raise EvalRequestBlocked("calibration_tool_call_not_permitted")

    if payload.get("tools") or payload.get("functions"):
        raise EvalRequestBlocked("calibration_tools_not_permitted")
    if payload.get("tool_choice") or payload.get("function_call"):
        raise EvalRequestBlocked("calibration_tool_choice_not_permitted")
    if payload.get("stream") not in (None, False):
        raise EvalRequestBlocked("calibration_stream_not_permitted")
    if payload.get("stream_options"):
        raise EvalRequestBlocked("calibration_stream_options_not_permitted")
    if payload.get("thinking") != {"type": "disabled"}:
        raise EvalRequestBlocked("calibration_thinking_must_be_disabled")
    if payload.get("reasoning_effort") is not None:
        raise EvalRequestBlocked("calibration_reasoning_effort_not_permitted")
    if max_output_tokens < 1 or max_output_tokens > CALIBRATION_MAX_OUTPUT_TOKENS:
        raise EvalRequestBlocked(
            f"calibration_output_reservation_out_of_range:{max_output_tokens}"
        )

    expected_sha = os.getenv("P12_EVAL_CALIBRATION_PAYLOAD_SHA256", "").strip().lower()
    if not expected_sha:
        raise EvalRequestBlocked("calibration_payload_fingerprint_missing")
    actual_sha, body_bytes = _payload_fingerprint(payload)
    if actual_sha != expected_sha:
        raise EvalRequestBlocked(
            f"calibration_payload_fingerprint_mismatch:{actual_sha}!={expected_sha}"
        )
    expected_bytes = os.getenv("P12_EVAL_CALIBRATION_BODY_BYTES", "").strip()
    if expected_bytes and str(body_bytes) != expected_bytes:
        raise EvalRequestBlocked(
            f"calibration_payload_size_mismatch:{body_bytes}!={expected_bytes}"
        )

    snapshot = _ledger.snapshot()
    if snapshot.get("stopped") or snapshot.get("pending"):
        raise EvalRequestBlocked("calibration_run_not_pristine")
    used = snapshot.get("used") or {}
    if int(used.get("requests") or 0) != 0:
        raise EvalRequestBlocked("calibration_requires_first_request")


def begin_eval_request(
    *,
    provider: str,
    model: str,
    target_url: str,
    payload: dict[str, Any],
    max_output_tokens: int | None = None,
    mock_transport: bool = False,
) -> EvalReservation | None:
    """Admit one network attempt and reserve its worst-case budget.

    The reservation is made once per actual send attempt.  A caller that retries
    must call this function again for every retry; if the first attempt is
    unresolved or failed, the ledger rejects the next reservation.

    ``mock_transport`` is only for the offline worker path that emits no
    network bytes.  It still goes through the same context, ledger and
    settlement checks, but uses the tokenizer estimate so the frozen five-case
    Mock regression can run inside the same conservative token budget.  Real
    transports never set this flag and always use the Layer-A hard bound.
    """

    if not eval_mode_enabled():
        require_external_model_calls_permitted()
        return None
    if mock_transport and os.getenv("P12_EVAL_MOCK_PROVIDER") != "1":
        raise EvalRequestBlocked("mock_transport_requires_mock_provider")
    if calibration_mode_enabled() and mock_transport:
        raise EvalRequestBlocked("calibration_requires_real_transport")
    _require_eval_context(
        provider,
        str(model),
        target_url,
        require_authorization=not mock_transport,
    )
    output_tokens = int(
        max_output_tokens
        if max_output_tokens is not None
        else payload.get("max_tokens", payload.get("max_output_tokens", 0)) or 0
    )
    _validate_model_parameters(payload, output_tokens)
    if calibration_mode_enabled():
        _validate_calibration_request(payload, output_tokens)
    bound = (
        {"upper_bound": tokenizer_input_token_estimate(payload)}
        if mock_transport
        else input_token_upper_bound(payload)
    )
    request_id = str(uuid.uuid4())
    reservation = _ledger.reserve(
        run_id=os.getenv("P12_EVAL_RUN_ID", "live-safety-01"),
        case_id=os.getenv("P12_EVAL_CASE_ID", "unknown"),
        request_id=request_id,
        payload=payload,
        max_output_tokens=output_tokens,
        expected_model=expected_model(),
        provider=provider,
        target_url=target_url,
        input_token_upper_bound=int(bound["upper_bound"]),
    )
    return EvalReservation(
        request_id=request_id,
        provider=provider,
        model=str(model),
        target_url=target_url,
        input_upper_bound=int(bound["upper_bound"]),
        output_tokens=output_tokens,
        max_output_tokens=output_tokens,
        ledger=_ledger,
    )


def _response_model(response: dict[str, Any] | None) -> str:
    return str((response or {}).get("model") or "")


def validate_response_model(
    reservation: EvalReservation | None,
    response: dict[str, Any] | None,
    *,
    http_status: int | None = None,
) -> None:
    if reservation is None:
        return
    actual = _response_model(response)
    allowed = RESPONSE_MODEL_ALLOWLIST.get(reservation.provider, frozenset())
    if actual not in allowed:
        try:
            # Let the ledger record the mismatch transition itself so the
            # evidence event, actual usage, cost and request count stay in one
            # atomic write.
            reservation.ledger.settle(
                response=response,
                http_status=http_status,
                expected_model=reservation.model,
                reserved_input_tokens=reservation.input_upper_bound,
                reserved_output_tokens=reservation.output_tokens,
            )
        except Exception as error:
            # A model mismatch is the expected ledger stop.  Persistence and
            # other fatal settlement failures must propagate unchanged; never
            # mark the reservation settled when the ledger did not commit.
            if (
                getattr(error, "eval_fatal", False)
                and str(error) == "model_not_authorized"
            ):
                reservation.settled = True
                raise ModelAuthorizationError(
                    f"response_model_not_authorized:{actual or '<missing>'}"
                ) from error
            raise
        reservation.settled = True
        raise ModelAuthorizationError(
            f"response_model_not_authorized:{actual or '<missing>'}"
        )


def settle_eval_response(
    reservation: EvalReservation | None,
    response: dict[str, Any] | None,
    *,
    http_status: int | None = None,
    error: str | None = None,
    retry: bool = False,
) -> None:
    if reservation is None:
        return
    if reservation.settled:
        reservation.ledger.stop_unknown(
            reservation.request_id, "duplicate_settlement_attempt"
        )
        raise EvalRequestBlocked("duplicate_settlement_attempt")
    validate_response_model(reservation, response, http_status=http_status)
    reservation.ledger.settle(
        response=response if error is None else None,
        http_status=http_status,
        error=error,
        retry=retry,
        expected_model=reservation.model,
        reserved_input_tokens=reservation.input_upper_bound,
        reserved_output_tokens=reservation.output_tokens,
    )
    reservation.settled = True
    if calibration_mode_enabled():
        reservation.ledger.stop_run("calibration_single_request_completed")
        # Calibration is a measurement, not a C7 completion run.  Settlement is
        # already durable; raise now so no later C7 step or second send starts.
        raise EvalRequestBlocked("calibration_request_completed_run_stopped")


def fail_eval_request(
    reservation: EvalReservation | None,
    error: BaseException | str,
    *,
    http_status: int | None = None,
) -> None:
    if reservation is None or reservation.settled:
        return
    reservation.ledger.stop_unknown(
        reservation.request_id, str(error), http_status=http_status
    )
    reservation.settled = True
    if calibration_mode_enabled():
        reservation.ledger.stop_run("calibration_request_failed")


def deny_eval_get(target_url: str) -> None:
    """Block non-billed GET endpoints in evaluation, keep production unchanged."""

    if eval_mode_enabled():
        raise EvalRequestBlocked(f"evaluation_get_not_permitted:{target_url}")
    require_external_model_calls_permitted()
