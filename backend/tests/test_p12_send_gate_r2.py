"""RETEST-02-SEND-GATE-R2 offline counterexample matrix.

Every test drives one of the two real production streaming entries with a
fake, in-process response.  No socket is opened, no API key is read and no
provider request is sent.
"""

from __future__ import annotations

import importlib.util
import json
import urllib.request
from pathlib import Path

import pytest

from app.agent_service import RobotAgentService
from app.eval_request_guard import (
    EvalRequestBlocked,
    ModelAuthorizationError,
    begin_eval_request,
    configure_eval_guard,
    reset_eval_guard,
)
from app.model_providers import ModelProviderAdapter
from app.model_request_gateway import request_openai_responses_json
from tests.manual import eval_budget_store
from tests.manual.eval_budget_store import BudgetLedger, EvaluationBudgetStop
from tests.manual.p01_admission import install_baseline_admission
from tests.manual.retest_02_budget_admission import (
    profile_values,
    retest_02_budget_env,
)


ROUTE = {
    "name": "chat",
    "tool_family": "general",
    "decision_source": "rules",
    "clarification_required": False,
}


def eval_env(monkeypatch, tmp_path):
    monkeypatch.setenv("P12_EVAL_MODE", "1")
    monkeypatch.setenv("P12_EVAL_FORMAL_HTTP", "1")
    monkeypatch.setenv("P12_EXPECTED_PROVIDER", "deepseek")
    monkeypatch.setenv("P12_EXPECTED_MODEL", "deepseek-flash")
    monkeypatch.setenv("P12_MAX_REQUESTS", "32")
    monkeypatch.setenv("P12_MAX_INPUT_TOKENS", "1000000")
    monkeypatch.setenv("P12_MAX_OUTPUT_TOKENS", "100000")
    monkeypatch.setenv("P12_MAX_COST_USD", "100")
    monkeypatch.setenv("P12_REAL_MODEL_AUTHORIZED", "1")
    ledger = BudgetLedger(tmp_path / "budget.json")
    configure_eval_guard(ledger)
    return ledger


def body(model="deepseek-flash"):
    return {
        "model": model,
        "messages": [{"role": "user", "content": "x"}],
        "max_tokens": 10,
    }


def event_line(*, model="deepseek-flash", content="{}", finish="stop", usage=True, error=None):
    event = {
        "model": model,
        "choices": [{"delta": {"content": content}, "finish_reason": finish}],
    }
    if usage is True:
        event["usage"] = {"prompt_tokens": 2, "completion_tokens": 1}
    elif usage is not None:
        event["usage"] = usage
    if error is not None:
        event["error"] = error
    return ("data: " + json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")


DONE = b"data: [DONE]\n"


class FakeResponse:
    status = 200

    def __init__(self, reservation, lines, status=200, fail_at=None, failure=None):
        self._p12_eval_reservation = reservation
        self._lines = list(lines)
        self.status = status
        self._index = 0
        self._fail_at = fail_at
        self._failure = failure
        self._reads = 0

    def readline(self):
        if self._fail_at is not None and self._reads >= self._fail_at:
            raise self._failure
        self._reads += 1
        if self._index >= len(self._lines):
            return b""
        line = self._lines[self._index]
        self._index += 1
        return line

    def close(self):
        return None


class FakeTransport:
    def __init__(self, response, *, open_error=None, read_body_text="error body"):
        self._response = response
        self._open_error = open_error
        self._read_body_text = read_body_text

    def open(self, payload):
        reservation = begin_eval_request(
            provider="deepseek",
            model=str(payload.get("model") or ""),
            target_url="https://api.deepseek.com/chat/completions",
            payload=payload,
            max_output_tokens=int(payload.get("max_tokens") or 0),
        )
        if self._open_error is not None:
            from app.eval_request_guard import fail_eval_request

            fail_eval_request(reservation, self._open_error)
            raise self._open_error
        self._response._p12_eval_reservation = reservation
        return None, self._response

    def set_socket_timeout(self, *_args, **_kwargs):
        return None

    def read_body(self, *_args, **_kwargs):
        return self._read_body_text


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(RobotAgentService, "configured", property(lambda self: True))
    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "deepseek"
    service.base_model = "deepseek-flash"
    service.advanced_model = "deepseek-flash"
    service.model = "deepseek-flash"
    monkeypatch.setattr(service, "_mode_message", lambda message, mode: message)
    monkeypatch.setattr(service, "_system_context", lambda *a, **k: "system")
    monkeypatch.setattr(service, "_selected_deepseek_tools", lambda *a, **k: [])
    monkeypatch.setattr(service, "_stale_project_guard", lambda route: None)
    monkeypatch.setattr(service, "_pending_design_followup", lambda **k: None)
    monkeypatch.setattr(service, "_apply_design_requirement_followup", lambda *a, **k: None)
    return service


def install(service, response, **kwargs):
    transport = FakeTransport(response, **kwargs)
    service._deepseek_transport = lambda: transport
    return response


def run_structured(service):
    return service._deepseek_request(
        [{"role": "user", "content": "x"}],
        [],
        mode="base",
        stream_structured=True,
    )


def run_chat(service):
    return list(service._chat_stream_impl("hello", [], mode="chat", route=ROUTE))


def assert_stopped(ledger, event_name=None):
    snapshot = ledger.snapshot()
    assert snapshot["stopped"] is True
    assert snapshot["pending"] is None
    assert not any(item["event"] == "settled" for item in snapshot["events"])
    if event_name is not None:
        assert any(item["event"] == event_name for item in snapshot["events"]), snapshot["events"]
    return snapshot


@pytest.mark.parametrize("entry", ["structured", "chat"])
def test_r2_legal_complete_sse_settles(entry, service, monkeypatch, tmp_path):
    ledger = eval_env(monkeypatch, tmp_path)
    lines = [event_line(), DONE]
    install(service, FakeResponse(None, lines))
    if entry == "structured":
        result = run_structured(service)
        assert result["choices"][0]["finish_reason"] == "stop"
    else:
        assert run_chat(service)[0]["type"] == "delta"
    snapshot = ledger.snapshot()
    assert snapshot["stopped"] is False
    settled = next(item for item in snapshot["events"] if item["event"] == "settled")
    assert settled["cost_class"] == "authorized_model_estimate"
    assert settled["http_status"] == 200


@pytest.mark.parametrize("entry", ["structured", "chat"])
def test_r2_finish_without_done_fails_closed(entry, service, monkeypatch, tmp_path):
    ledger = eval_env(monkeypatch, tmp_path)
    install(service, FakeResponse(None, [event_line()]))
    with pytest.raises(EvalRequestBlocked):
        run_structured(service) if entry == "structured" else run_chat(service)
    assert_stopped(ledger, "settle_unknown_stop")


@pytest.mark.parametrize("entry", ["structured", "chat"])
def test_r2_done_without_finish_fails_closed(entry, service, monkeypatch, tmp_path):
    ledger = eval_env(monkeypatch, tmp_path)
    install(service, FakeResponse(None, [event_line(finish=None), DONE]))
    with pytest.raises(EvalRequestBlocked):
        run_structured(service) if entry == "structured" else run_chat(service)
    assert_stopped(ledger, "settle_unknown_stop")


@pytest.mark.parametrize("finish", ["length", "content_filter"])
@pytest.mark.parametrize("entry", ["structured", "chat"])
def test_r2_bad_finish_reason_fails_closed(finish, entry, service, monkeypatch, tmp_path):
    ledger = eval_env(monkeypatch, tmp_path)
    install(service, FakeResponse(None, [event_line(finish=finish), DONE]))
    with pytest.raises(EvalRequestBlocked):
        run_structured(service) if entry == "structured" else run_chat(service)
    assert_stopped(ledger, "settle_unknown_stop")


@pytest.mark.parametrize("entry", ["structured", "chat"])
def test_r2_data_after_done_fails_closed(entry, service, monkeypatch, tmp_path):
    ledger = eval_env(monkeypatch, tmp_path)
    install(service, FakeResponse(None, [event_line(), DONE, event_line(content="late")]))
    with pytest.raises(EvalRequestBlocked):
        run_structured(service) if entry == "structured" else run_chat(service)
    assert_stopped(ledger, "settle_unknown_stop")


@pytest.mark.parametrize("entry", ["structured", "chat"])
def test_r2_model_identity_change_fails_closed(entry, service, monkeypatch, tmp_path):
    ledger = eval_env(monkeypatch, tmp_path)
    install(
        service,
        FakeResponse(
            None,
            [event_line(model="deepseek-flash"), event_line(model="deepseek-chat"), DONE],
        ),
    )
    with pytest.raises(ModelAuthorizationError):
        run_structured(service) if entry == "structured" else run_chat(service)
    assert_stopped(ledger, "model_mismatch_stop")


@pytest.mark.parametrize("entry", ["structured", "chat"])
def test_r2_unauthorized_model_cannot_be_overwritten(entry, service, monkeypatch, tmp_path):
    ledger = eval_env(monkeypatch, tmp_path)
    install(
        service,
        FakeResponse(
            None,
            [event_line(model="deepseek-chat"), event_line(model="deepseek-flash"), DONE],
        ),
    )
    with pytest.raises(ModelAuthorizationError):
        run_structured(service) if entry == "structured" else run_chat(service)
    snapshot = assert_stopped(ledger, "model_mismatch_stop")
    event = next(item for item in snapshot["events"] if item["event"] == "model_mismatch_stop")
    assert event["actual_model"] == "deepseek-chat"


@pytest.mark.parametrize("entry", ["structured", "chat"])
def test_r2_sse_error_event_fails_closed(entry, service, monkeypatch, tmp_path):
    ledger = eval_env(monkeypatch, tmp_path)
    install(service, FakeResponse(None, [event_line(error={"message": "synthetic"}), DONE]))
    with pytest.raises(EvalRequestBlocked):
        run_structured(service) if entry == "structured" else run_chat(service)
    assert_stopped(ledger, "settle_unknown_stop")


@pytest.mark.parametrize("entry", ["structured", "chat"])
def test_r2_missing_usage_fails_closed(entry, service, monkeypatch, tmp_path):
    ledger = eval_env(monkeypatch, tmp_path)
    install(service, FakeResponse(None, [event_line(usage=False), DONE]))
    with pytest.raises(EvalRequestBlocked):
        run_structured(service) if entry == "structured" else run_chat(service)
    snapshot = assert_stopped(ledger, "settle_unknown_stop")
    event = next(item for item in snapshot["events"] if item["event"] == "settle_unknown_stop")
    assert event["unconfirmed_cost_upper_bound_usd"] > 0
    assert event["cost_class"] == "unconfirmed_upper_bound"


@pytest.mark.parametrize("entry", ["structured", "chat"])
def test_r2_invalid_usage_fails_closed(entry, service, monkeypatch, tmp_path):
    ledger = eval_env(monkeypatch, tmp_path)
    install(
        service,
        FakeResponse(
            None,
            [event_line(usage={"prompt_tokens": "bad", "completion_tokens": 1}), DONE],
        ),
    )
    with pytest.raises(EvalRequestBlocked):
        run_structured(service) if entry == "structured" else run_chat(service)
    snapshot = assert_stopped(ledger, "settle_unknown_stop")
    event = next(item for item in snapshot["events"] if item["event"] == "settle_unknown_stop")
    assert event["usage"] == {"prompt_tokens": "bad", "completion_tokens": 1}
    assert event["unconfirmed_cost_upper_bound_usd"] > 0


@pytest.mark.parametrize("status", [429, 500])
@pytest.mark.parametrize("entry", ["structured", "chat"])
def test_r2_known_http_error_preserves_status(status, entry, service, monkeypatch, tmp_path):
    ledger = eval_env(monkeypatch, tmp_path)
    install(service, FakeResponse(None, [], status=status))
    with pytest.raises(RuntimeError):
        run_structured(service) if entry == "structured" else run_chat(service)
    snapshot = assert_stopped(ledger, "settle_unknown_stop")
    event = next(item for item in snapshot["events"] if item["event"] == "settle_unknown_stop")
    assert event["http_status"] == status
    assert event["unconfirmed_cost_upper_bound_usd"] > 0


@pytest.mark.parametrize("entry", ["structured", "chat"])
def test_r2_timeout_after_status_preserves_status_and_usage(entry, service, monkeypatch, tmp_path):
    ledger = eval_env(monkeypatch, tmp_path)
    install(
        service,
        FakeResponse(None, [event_line(finish=None)], fail_at=1, failure=TimeoutError("synthetic")),
    )
    with pytest.raises(RuntimeError):
        run_structured(service) if entry == "structured" else run_chat(service)
    snapshot = assert_stopped(ledger, "settle_unknown_stop")
    event = next(item for item in snapshot["events"] if item["event"] == "settle_unknown_stop")
    assert event["http_status"] == 200
    assert event["usage"] == {"prompt_tokens": 2, "completion_tokens": 1}
    assert event["cost_class"] == "authorized_model_estimate"


@pytest.mark.parametrize("entry", ["structured", "chat"])
def test_r2_connection_failure_without_status_is_unknown(entry, service, monkeypatch, tmp_path):
    ledger = eval_env(monkeypatch, tmp_path)
    install(service, FakeResponse(None, []), open_error=OSError("connection refused"))
    with pytest.raises(OSError):
        run_structured(service) if entry == "structured" else run_chat(service)
    snapshot = assert_stopped(ledger, "settle_unknown_stop")
    event = next(item for item in snapshot["events"] if item["event"] == "settle_unknown_stop")
    assert event["http_status"] is None
    assert event["http_status_status"] == "unknown"
    assert event["unconfirmed_cost_upper_bound_usd"] > 0


@pytest.mark.parametrize("entry", ["structured", "chat"])
def test_r2_usage_then_eof_preserves_usage(entry, service, monkeypatch, tmp_path):
    ledger = eval_env(monkeypatch, tmp_path)
    install(service, FakeResponse(None, [event_line()]))
    with pytest.raises(EvalRequestBlocked):
        run_structured(service) if entry == "structured" else run_chat(service)
    snapshot = assert_stopped(ledger, "settle_unknown_stop")
    event = next(item for item in snapshot["events"] if item["event"] == "settle_unknown_stop")
    assert event["usage"] == {"prompt_tokens": 2, "completion_tokens": 1}
    assert event["cost_class"] == "authorized_model_estimate"


@pytest.mark.parametrize("entry", ["structured", "chat"])
def test_r2_raw_evidence_write_failure_never_settles(entry, service, monkeypatch, tmp_path):
    ledger = eval_env(monkeypatch, tmp_path)
    install(
        service,
        FakeResponse(None, [], fail_at=0, failure=OSError("raw_evidence_write_failed")),
    )
    with pytest.raises(OSError):
        run_structured(service) if entry == "structured" else run_chat(service)
    snapshot = assert_stopped(ledger, "settle_unknown_stop")
    event = next(item for item in snapshot["events"] if item["event"] == "settle_unknown_stop")
    assert "raw_evidence_write_failed" in event["error"]


def test_r2_restart_after_stream_failure_remains_blocked(service, monkeypatch, tmp_path):
    ledger = eval_env(monkeypatch, tmp_path)
    install(service, FakeResponse(None, [event_line()]))
    with pytest.raises(EvalRequestBlocked):
        run_structured(service)
    restarted = BudgetLedger(tmp_path / "budget.json")
    configure_eval_guard(restarted)
    with pytest.raises((EvaluationBudgetStop, EvalRequestBlocked)):
        begin_eval_request(
            provider="deepseek",
            model="deepseek-flash",
            target_url="https://api.deepseek.com/chat/completions",
            payload=body(),
            max_output_tokens=10,
        )


class _FakeHTTPResponse:
    status = 200

    def __init__(self, body: bytes = b"", failure: BaseException | None = None):
        self._body = body
        self._failure = failure

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        if self._failure is not None:
            raise self._failure
        return self._body


class _EchoProvider(ModelProviderAdapter):
    name = "deepseek"


@pytest.mark.parametrize(
    "failure",
    [
        b"not-json",
        UnicodeDecodeError("utf-8", b"x", 0, 1, "bad"),
        TimeoutError("read timed out"),
    ],
)
def test_r2_provider_body_failure_preserves_known_status(
    failure, service, monkeypatch, tmp_path
):
    ledger = eval_env(monkeypatch, tmp_path)
    if isinstance(failure, bytes):
        response = _FakeHTTPResponse(body=failure)
    else:
        response = _FakeHTTPResponse(failure=failure)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: response)
    request = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(body()).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(RuntimeError):
        _EchoProvider().send_json(request, timeout=1)
    snapshot = assert_stopped(ledger, "settle_unknown_stop")
    event = next(item for item in snapshot["events"] if item["event"] == "settle_unknown_stop")
    assert event["http_status"] == 200
    assert event["http_status_status"] == "known"
    assert event["unconfirmed_cost_upper_bound_usd"] > 0


def test_r2_gateway_json_error_preserves_known_status(service, monkeypatch, tmp_path):
    ledger = eval_env(monkeypatch, tmp_path)
    monkeypatch.setenv("P12_EXPECTED_PROVIDER", "openai")
    monkeypatch.setenv("P12_EXPECTED_MODEL", "gpt-5")
    from app import eval_request_guard

    monkeypatch.setitem(
        eval_request_guard.AUTHORIZED_TARGETS,
        "openai",
        "https://api.openai.com/v1/responses",
    )
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: _FakeHTTPResponse(body=b"not-json")
    )
    with pytest.raises(RuntimeError):
        request_openai_responses_json(
            api_key="test-key",
            payload={"model": "gpt-5", "max_output_tokens": 10},
            timeout=1,
        )
    snapshot = assert_stopped(ledger, "settle_unknown_stop")
    event = next(item for item in snapshot["events"] if item["event"] == "settle_unknown_stop")
    assert event["http_status"] == 200
    assert event["http_status_status"] == "known"
    assert event["unconfirmed_cost_upper_bound_usd"] > 0


@pytest.mark.parametrize("entry", ["structured", "chat"])
def test_r2_2_prior_usage_survives_unauthorized_model(entry, service, monkeypatch, tmp_path):
    ledger = eval_env(monkeypatch, tmp_path)
    install(
        service,
        FakeResponse(
            None,
            [
                event_line(usage={"prompt_tokens": 2, "completion_tokens": 1}),
                event_line(model="deepseek-chat", usage=None),
                DONE,
            ],
        ),
    )
    with pytest.raises(ModelAuthorizationError):
        run_structured(service) if entry == "structured" else run_chat(service)
    snapshot = assert_stopped(ledger, "model_mismatch_stop")
    event = next(item for item in snapshot["events"] if item["event"] == "model_mismatch_stop")
    assert event["actual_model"] == "deepseek-chat"
    assert event["usage"] == {"prompt_tokens": 2, "completion_tokens": 1}
    assert event["usage_events"] == [{"prompt_tokens": 2, "completion_tokens": 1}]
    assert event["usage_events_count"] == 1
    assert event["cost_class"] == "unauthorized_model_upper_bound"
    assert event["unconfirmed_cost_upper_bound_usd"] > 0


@pytest.mark.parametrize("entry", ["structured", "chat"])
def test_r2_2_unauthorized_event_usage_is_preserved(entry, service, monkeypatch, tmp_path):
    ledger = eval_env(monkeypatch, tmp_path)
    install(
        service,
        FakeResponse(
            None,
            [
                event_line(usage={"prompt_tokens": 2, "completion_tokens": 1}),
                event_line(
                    model="deepseek-chat",
                    usage={"prompt_tokens": 7, "completion_tokens": 3},
                ),
                DONE,
            ],
        ),
    )
    with pytest.raises(ModelAuthorizationError):
        run_structured(service) if entry == "structured" else run_chat(service)
    snapshot = assert_stopped(ledger, "model_mismatch_stop")
    event = next(item for item in snapshot["events"] if item["event"] == "model_mismatch_stop")
    assert event["usage"] == {"prompt_tokens": 7, "completion_tokens": 3}
    assert event["usage_events"] == [
        {"prompt_tokens": 2, "completion_tokens": 1},
        {"prompt_tokens": 7, "completion_tokens": 3},
    ]
    assert event["usage_events_count"] == 2
    assert event["cost_class"] == "unauthorized_model_upper_bound"


class _AuditLedger:
    def __init__(self):
        self.calls = []

    def stop_unknown(self, request_id, error, http_status=None, response=None):
        self.calls.append(
            {
                "request_id": request_id,
                "error": str(error),
                "http_status": http_status,
                "response": response,
            }
        )


class _AuditReservation:
    request_id = "req-audit-write"

    def __init__(self):
        self.ledger = _AuditLedger()
        self.settled = False


class _AuditResponse:
    status = 200

    def __init__(self, reservation):
        self._p12_eval_reservation = reservation
        self.closed = False

    def close(self):
        self.closed = True


class _AuditConnection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _load_raw_http_audit():
    path = Path(__file__).resolve().parent / "manual" / "raw_http_audit.py"
    spec = importlib.util.spec_from_file_location("raw_http_audit_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("phase", ["metadata", "index"])
def test_r2_2_audit_writer_failure_settles_and_closes(phase, tmp_path):
    audit = _load_raw_http_audit()
    raw_dir = tmp_path / "raw-http"
    raw_dir.mkdir()
    reservation = _AuditReservation()
    response = _AuditResponse(reservation)
    connection = _AuditConnection()
    if phase == "metadata":
        (raw_dir / f"{reservation.request_id}.meta.json").mkdir()
    else:
        (tmp_path / "model-http-index.jsonl").mkdir()
    original = lambda *args, **kwargs: (connection, response)
    wrapper = audit.build_audited_stream_response(
        original,
        raw_dir=raw_dir,
        root=tmp_path,
        request={"step": 1},
    )
    with pytest.raises(OSError):
        wrapper({"model": "deepseek-flash"})
    assert reservation.settled is True
    assert response.closed is True
    assert connection.closed is True
    assert len(reservation.ledger.calls) == 1
    call = reservation.ledger.calls[0]
    assert call["request_id"] == reservation.request_id
    assert call["http_status"] == 200
    assert call["response"] == {"model": "deepseek-flash"}
    assert call["error"]


def test_r2_2_audit_persistence_failure_stays_fail_closed(tmp_path):
    audit = _load_raw_http_audit()
    raw_dir = tmp_path / "raw-http"
    raw_dir.mkdir()
    reservation = _AuditReservation()
    response = _AuditResponse(reservation)
    connection = _AuditConnection()
    (raw_dir / f"{reservation.request_id}.meta.json").mkdir()

    def fail_eval(*args, **kwargs):
        reservation.settled = True
        raise RuntimeError("ledger_persist_failed")

    original = lambda *args, **kwargs: (connection, response)
    wrapper = audit.build_audited_stream_response(
        original,
        raw_dir=raw_dir,
        root=tmp_path,
        request={"step": 1},
        fail_eval=fail_eval,
    )
    with pytest.raises(RuntimeError, match="ledger_persist_failed"):
        wrapper({"model": "deepseek-flash"})
    assert reservation.settled is True
    assert response.closed is True
    assert connection.closed is True


def test_r2_2_production_truncation_still_fails(service, monkeypatch, tmp_path):
    for name in (
        "P12_EVAL_MODE",
        "P12_EVAL_FORMAL_HTTP",
        "P12_EXPECTED_PROVIDER",
        "P12_EXPECTED_MODEL",
        "P12_REAL_MODEL_AUTHORIZED",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "app.eval_request_guard.require_external_model_calls_permitted",
        lambda: None,
    )
    install(service, FakeResponse(None, [event_line(finish=None)]))
    with pytest.raises(RuntimeError, match="stream_missing_finish_reason"):
        run_structured(service)


def test_r2_2_production_chat_truncation_still_fails(service, monkeypatch, tmp_path):
    for name in (
        "P12_EVAL_MODE",
        "P12_EVAL_FORMAL_HTTP",
        "P12_EXPECTED_PROVIDER",
        "P12_EXPECTED_MODEL",
        "P12_REAL_MODEL_AUTHORIZED",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "app.eval_request_guard.require_external_model_calls_permitted",
        lambda: None,
    )
    install(service, FakeResponse(None, [event_line(finish=None)]))
    with pytest.raises(RuntimeError, match="stream_missing_finish_reason"):
        run_chat(service)


def _retest_ledger(monkeypatch, tmp_path, **limits):
    defaults = retest_02_budget_env()
    defaults.update({key: str(value) for key, value in limits.items()})
    for key, value in defaults.items():
        monkeypatch.setenv(key, str(value))
    return BudgetLedger(tmp_path / "budget.json")


def test_r2_2_retest_runner_profile_is_canonical():
    env = retest_02_budget_env()
    assert env["P12_MAX_INPUT_TOKENS"] == "600000"
    assert env["P12_BASELINE_REQUEST_INPUT_CAP"] == "1048576"
    assert env["P12_MAX_COST_USD"] == "0.55"
    assert env["P12_INPUT_PRICE_PER_M"] == "0.3"
    assert env["P12_OUTPUT_PRICE_PER_M"] == "1.2"
    values = profile_values()
    assert values["theoretical_worst_case_usd"] == pytest.approx(0.5215728)
    with pytest.raises(ValueError, match="retest_02_budget_profile_mismatch"):
        retest_02_budget_env(cost_usd=0.56)


def test_r2_2_retest_local_cumulative_input_600k_is_enforced(monkeypatch, tmp_path):
    budget = _retest_ledger(monkeypatch, tmp_path)
    assert budget._read()["limits"]["input_tokens"] == 600000
    data = budget._read()
    data["used"]["input_tokens"] = 600000
    budget._write(data)
    with pytest.raises(EvaluationBudgetStop, match="budget_would_be_exceeded"):
        budget.reserve(
            run_id="r2.2",
            case_id="Q04",
            request_id="req-over-local-input",
            payload={},
            max_output_tokens=100,
            input_token_upper_bound=1,
        )
    assert budget.snapshot()["events"][-1]["event"] == "reserve_rejected"


def test_r2_2_retest_single_request_cap_1048576_is_enforced(monkeypatch, tmp_path):
    budget = _retest_ledger(
        monkeypatch,
        tmp_path,
        P12_MAX_INPUT_TOKENS="2000000",
        P12_MAX_COST_USD="2.0",
    )
    guarded = install_baseline_admission(
        budget,
        actual_input_stop=0,
        request_input_cap=1048576,
    )
    with pytest.raises(
        EvaluationBudgetStop,
        match="baseline_request_input_reservation_exceeds_cap",
    ):
        guarded(
            run_id="r2.2",
            case_id="Q04",
            request_id="req-over-single-cap",
            payload={},
            max_output_tokens=100,
            input_token_upper_bound=1048577,
        )
    assert budget.snapshot()["events"][-1]["event"] == "run_stopped"


def test_r2_2_retest_cost_cap_055_is_enforced(monkeypatch, tmp_path):
    budget = _retest_ledger(
        monkeypatch,
        tmp_path,
        P12_MAX_INPUT_TOKENS="2000000",
        P12_MAX_COST_USD="0.55",
    )
    # Exercise the runner's official prices, not the ledger's conservative
    # defaults.  The single-request reservation is 0.3865728 USD; the already
    # consumed 0.20 USD pushes the cumulative estimate over the 0.55 cap.
    monkeypatch.setattr(eval_budget_store, "INPUT_PRICE_PER_M", 0.30)
    monkeypatch.setattr(eval_budget_store, "OUTPUT_PRICE_PER_M", 1.20)
    data = budget._read()
    data["used"]["cost_usd"] = 0.20
    budget._write(data)
    guarded = install_baseline_admission(
        budget,
        actual_input_stop=0,
        request_input_cap=0,
    )
    with pytest.raises(EvaluationBudgetStop, match="budget_would_be_exceeded"):
        guarded(
            run_id="r2.2",
            case_id="Q04",
            request_id="req-over-cost",
            payload={},
            max_output_tokens=60000,
            input_token_upper_bound=1048576,
        )
    event = budget.snapshot()["events"][-1]
    assert event["event"] == "reserve_rejected"
    assert event["requested"]["cost_usd"] == pytest.approx(0.3865728)
    assert event["used"]["cost_usd"] + event["requested"]["cost_usd"] > 0.55


def teardown_function():
    reset_eval_guard()
