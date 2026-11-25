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

import os
import threading
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .eval_token_bound import input_token_upper_bound
from .integration_profile import require_external_model_calls_permitted


DEFAULT_EXPECTED_PROVIDER = "deepseek"
DEFAULT_EXPECTED_MODEL = "deepseek-flash"
AUTHORIZED_TARGETS = {
    "deepseek": "https://api.deepseek.com/chat/completions",
}
RESPONSE_MODEL_ALLOWLIST = {
    "deepseek": frozenset({"deepseek-flash"}),
}


class EvalRequestBlocked(RuntimeError):
    """Raised before any request bytes reach the network."""


class ModelAuthorizationError(EvalRequestBlocked):
    """Raised when a provider/model/target is not the frozen evaluation pair."""


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


def _authorized_target(provider: str) -> str:
    return AUTHORIZED_TARGETS.get(provider, "")


def _normalized_url(url: str) -> str:
    parsed = urlparse(url)
    return (
        f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if parsed.scheme and parsed.netloc
        else ""
    )


def _require_eval_context(provider: str, model: str, target_url: str) -> None:
    if not eval_mode_enabled():
        return
    if os.getenv("P12_EVAL_FORMAL_HTTP") != "1":
        raise EvalRequestBlocked("evaluation_formal_entry_required")
    if os.getenv("P12_REAL_MODEL_AUTHORIZED") != "1":
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


def begin_eval_request(
    *,
    provider: str,
    model: str,
    target_url: str,
    payload: dict[str, Any],
    max_output_tokens: int | None = None,
) -> EvalReservation | None:
    """Admit one network attempt and reserve its worst-case budget.

    The reservation is made once per actual send attempt.  A caller that retries
    must call this function again for every retry; if the first attempt is
    unresolved or failed, the ledger rejects the next reservation.
    """

    if not eval_mode_enabled():
        require_external_model_calls_permitted()
        return None
    _require_eval_context(provider, str(model), target_url)
    output_tokens = int(
        max_output_tokens
        if max_output_tokens is not None
        else payload.get("max_tokens", payload.get("max_output_tokens", 0)) or 0
    )
    _validate_model_parameters(payload, output_tokens)
    bound = input_token_upper_bound(payload)
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
    reservation: EvalReservation | None, response: dict[str, Any] | None
) -> None:
    if reservation is None:
        return
    actual = _response_model(response)
    allowed = RESPONSE_MODEL_ALLOWLIST.get(reservation.provider, frozenset())
    if actual not in allowed:
        try:
            # Let the ledger record the mismatch transition itself so the
            # evidence event and the request count stay in one atomic write.
            reservation.ledger.settle(
                response=response,
                expected_model=reservation.model,
                reserved_input_tokens=reservation.input_upper_bound,
                reserved_output_tokens=reservation.output_tokens,
            )
        except Exception:
            pass
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
    validate_response_model(reservation, response)
    try:
        reservation.ledger.settle(
            response=response if error is None else None,
            http_status=http_status,
            error=error,
            retry=retry,
            expected_model=reservation.model,
            reserved_input_tokens=reservation.input_upper_bound,
            reserved_output_tokens=reservation.output_tokens,
        )
    finally:
        reservation.settled = True


def fail_eval_request(
    reservation: EvalReservation | None, error: BaseException | str
) -> None:
    if reservation is None or reservation.settled:
        return
    reservation.ledger.stop_unknown(reservation.request_id, str(error))
    reservation.settled = True


def deny_eval_get(target_url: str) -> None:
    """Block non-billed GET endpoints in evaluation, keep production unchanged."""

    if eval_mode_enabled():
        raise EvalRequestBlocked(f"evaluation_get_not_permitted:{target_url}")
    require_external_model_calls_permitted()
