"""CAD-E2E-LIVE-SAFETY-CLOSE-02 negative matrix.

All tests are offline.  No provider socket is opened.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from app import agent_http_service
from app.agent_service import RobotAgentService
from app.eval_request_guard import (
    EvalRequestBlocked,
    ModelAuthorizationError,
    begin_eval_request,
    configure_eval_guard,
    is_eval_fatal,
    require_eval_not_aborted,
    reset_eval_guard,
    settle_eval_response,
)
from app.eval_token_bound import input_token_upper_bound
from tests.manual.eval_budget_store import (
    BudgetLedger,
    EvaluationBudgetStop,
    EvaluationPersistenceError,
)
from tests.manual import run_user_cad_corpus


def eval_env(monkeypatch, tmp_path, *, requests=8):
    monkeypatch.setenv("P12_EVAL_MODE", "1")
    monkeypatch.setenv("P12_EVAL_FORMAL_HTTP", "1")
    monkeypatch.setenv("P12_EXPECTED_PROVIDER", "deepseek")
    monkeypatch.setenv("P12_EXPECTED_MODEL", "deepseek-flash")
    monkeypatch.setenv("P12_MAX_REQUESTS", str(requests))
    monkeypatch.setenv("P12_MAX_INPUT_TOKENS", "1000000")
    monkeypatch.setenv("P12_MAX_OUTPUT_TOKENS", "100000")
    monkeypatch.setenv("P12_MAX_COST_USD", "100")
    monkeypatch.setenv("P12_REAL_MODEL_AUTHORIZED", "1")
    ledger = BudgetLedger(tmp_path / "budget.json")
    configure_eval_guard(ledger)
    return ledger


def body(model="deepseek-flash", **extra):
    return {
        "model": model,
        "messages": [{"role": "user", "content": "x"}],
        "max_tokens": 10,
        **extra,
    }


def begin(ledger, **overrides):
    values = {
        "provider": "deepseek",
        "model": "deepseek-flash",
        "target_url": "https://api.deepseek.com/chat/completions",
        "payload": body(),
        "max_output_tokens": 10,
    }
    values.update(overrides)
    return begin_eval_request(**values)


def teardown_function():
    reset_eval_guard()


# T01/T02: fatal exceptions reach the caller instead of rules_fallback.
def test_t01_route_review_fatal_is_not_rules_fallback(monkeypatch):
    monkeypatch.setattr(RobotAgentService, "configured", property(lambda self: True))
    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "deepseek"
    monkeypatch.setattr(
        service,
        "_structured_review_text",
        lambda *a, **k: (_ for _ in ()).throw(EvaluationBudgetStop("model_not_authorized")),
    )
    with pytest.raises(EvaluationBudgetStop):
        service.resolve_intent("帮我处理一下那个东西", "advanced", [])


def test_t02_structured_cad_edit_fatal_is_not_local_failure(monkeypatch):
    monkeypatch.setattr(RobotAgentService, "configured", property(lambda self: True))
    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "deepseek"
    monkeypatch.setattr(
        service,
        "_structured_review_text",
        lambda *a, **k: (_ for _ in ()).throw(EvaluationBudgetStop("model_not_authorized")),
    )
    route = {
        "name": "drawing_design",
        "operation": "modify",
        "decision_source": "rules",
        "edit_domain": "candidate_variant",
    }
    with pytest.raises(EvaluationBudgetStop):
        service._structured_cad_edit_fallback("把矩形宽度改成5米", [], route, "advanced")


# T03/T04/T09: usage and cost evidence survives fatal settlement.
def test_t03_missing_usage_is_not_recorded_as_zero_cost(tmp_path, monkeypatch):
    ledger = eval_env(monkeypatch, tmp_path)
    reservation = begin(ledger)
    with pytest.raises(EvaluationBudgetStop):
        settle_eval_response(reservation, {"model": "deepseek-flash"})
    snapshot = ledger.snapshot()
    event = next(e for e in snapshot["events"] if e["event"] == "settle_unknown_stop")
    assert event["cost_usd"] is None
    assert event["cost_status"] == "unverifiable"
    assert event["usage"] is None


def test_t04_usage_over_reservation_accumulates_before_stop(tmp_path, monkeypatch):
    ledger = eval_env(monkeypatch, tmp_path)
    reservation = begin(ledger)
    with pytest.raises(EvaluationBudgetStop):
        settle_eval_response(
            reservation,
            {"model": "deepseek-flash", "usage": {"prompt_tokens": 1000, "completion_tokens": 10}},
        )
    snapshot = ledger.snapshot()
    assert snapshot["used"]["input_tokens"] == 1000
    assert snapshot["used"]["output_tokens"] == 10
    event = next(e for e in snapshot["events"] if e["event"] == "usage_exceeded_reservation")
    assert event["cost_usd"] is not None


def test_t09_model_mismatch_keeps_request_usage_and_cost(tmp_path, monkeypatch):
    ledger = eval_env(monkeypatch, tmp_path)
    reservation = begin(ledger)
    with pytest.raises(ModelAuthorizationError):
        settle_eval_response(
            reservation,
            {"model": "deepseek-chat", "usage": {"prompt_tokens": 100, "completion_tokens": 10}},
        )
    snapshot = ledger.snapshot()
    assert snapshot["used"]["requests"] == 1
    assert snapshot["used"]["input_tokens"] == 100
    assert snapshot["used"]["output_tokens"] == 10
    assert snapshot["used"]["cost_usd"] > 0
    event = next(e for e in snapshot["events"] if e["event"] == "model_mismatch_stop")
    assert event["cost_status"] == "settled"
    assert event["reservation"]["input_tokens"] > 0


# T05/T08: limit stop is immediate and survives restart.
def test_t05_request_limit_stops_immediately(tmp_path, monkeypatch):
    ledger = eval_env(monkeypatch, tmp_path, requests=1)
    first = begin(ledger)
    settle_eval_response(first, {"model": "deepseek-flash", "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
    with pytest.raises(EvaluationBudgetStop):
        begin(ledger)
    assert ledger.snapshot()["stopped"] is True


def test_t08_restart_after_fatal_is_still_blocked(tmp_path, monkeypatch):
    ledger = eval_env(monkeypatch, tmp_path)
    reservation = begin(ledger)
    with pytest.raises(EvaluationBudgetStop):
        settle_eval_response(reservation, {"model": "deepseek-flash"})
    restarted = BudgetLedger(tmp_path / "budget.json")
    configure_eval_guard(restarted)
    with pytest.raises((EvaluationBudgetStop, EvalRequestBlocked)):
        begin(restarted)


# T10: ledger persistence failure is fatal across restart.
def test_t10_persistence_failure_poisons_ledger(tmp_path, monkeypatch):
    ledger = eval_env(monkeypatch, tmp_path)
    reservation = begin(ledger)
    def fail_replace(*args, **kwargs):
        raise OSError("synthetic_replace_failure")
    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(EvaluationPersistenceError):
        ledger.settle(
            response={"model": "deepseek-flash", "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
            expected_model="deepseek-flash",
            reserved_input_tokens=reservation.input_upper_bound,
            reserved_output_tokens=reservation.output_tokens,
        )
    assert ledger.fail_closed_path.exists()
    restarted = BudgetLedger(tmp_path / "budget.json")
    with pytest.raises(EvaluationPersistenceError):
        restarted.reserve(
            run_id="r", case_id="c", request_id="x", payload=body(),
            max_output_tokens=10, expected_model="deepseek-flash",
            provider="deepseek", target_url="https://api.deepseek.com/chat/completions",
        )


# T06/T07: fatal marker crosses the subprocess boundary; abort stops later cases.
def test_t06_subprocess_fatal_marker_is_detected(tmp_path, monkeypatch):
    class Result:
        returncode = 1
        stdout = ""
        stderr = 'P12_EVAL_FATAL:{"type":"EvaluationBudgetStop","message":"model_not_authorized"}\n'
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Result())
    with pytest.raises(run_user_cad_corpus.EvaluationAborted):
        run_user_cad_corpus.call(tmp_path / "case", 1, {})


def test_t06_http_chat_preserves_machine_fatal_marker(monkeypatch):
    from fastapi.responses import JSONResponse
    from starlette.requests import Request
    from app.routers import agent as agent_router
    from app.schemas import AgentChatRequest

    def fatal_chat(command):
        raise ModelAuthorizationError("real_model_not_authorized")

    monkeypatch.setattr(agent_router.agent_http_service, "agent_chat", fatal_chat)
    request = Request({"type": "http", "method": "POST", "path": "/api/agent/chat", "headers": []})
    response = agent_router.agent_chat(AgentChatRequest(message="画一个矩形"), request)
    assert isinstance(response, JSONResponse)
    assert response.status_code == 503
    body = json.loads(response.body)
    assert body["fatal"] is True
    assert body["error_code"] == "evaluation_aborted"
    assert body["error_type"] == "ModelAuthorizationError"


# T11: production RuntimeError keeps the normal rules fallback.
def test_t11_production_runtime_error_still_falls_back(monkeypatch):
    monkeypatch.setattr(RobotAgentService, "configured", property(lambda self: True))
    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "deepseek"
    monkeypatch.setattr(
        service,
        "_structured_review_text",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("synthetic business failure")),
    )
    route = service.resolve_intent("帮我处理一下那个东西", "advanced", [])
    assert route["decision_source"] == "rules_fallback"
    assert is_eval_fatal(RuntimeError("synthetic business failure")) is False


# Layer A / E4 evidence.
def test_layer_a_hard_bound_is_body_plus_protocol(monkeypatch):
    bound = input_token_upper_bound(body())
    assert bound["upper_bound"] >= bound["body_bytes"]
    assert bound["upper_bound"] == bound["hard_upper_bound"]
    assert bound["basis"].startswith("utf8-byte")
    assert bound["upper_bound"] > bound["body_bytes"] // 4


def test_fatal_chain_is_visible_through_wrapper():
    original = EvaluationBudgetStop("model_not_authorized")
    wrapper = RuntimeError("wrapped")
    wrapper.__cause__ = original
    assert is_eval_fatal(wrapper) is True
    assert is_eval_fatal(ValueError("ordinary")) is False


def test_abort_guard_blocks_before_next_case(tmp_path, monkeypatch):
    ledger = eval_env(monkeypatch, tmp_path)
    ledger.reserve(
        run_id="r", case_id="c", request_id="x", payload=body(),
        max_output_tokens=10, expected_model="deepseek-flash",
        provider="deepseek", target_url="https://api.deepseek.com/chat/completions",
        input_token_upper_bound=100,
    )
    ledger.stop_unknown("x", "synthetic_failure")
    with pytest.raises(EvalRequestBlocked):
        require_eval_not_aborted()
