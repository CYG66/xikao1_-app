"""Synthetic, no-network boundary tests for the P01 admission patch."""
from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_budget_store import BudgetLedger, EvaluationBudgetStop  # noqa: E402
from p01_admission import install_baseline_admission  # noqa: E402


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("P01 boundary tests must never open a socket")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


def ledger(tmp_path, *, requests=30, input_tokens=1_348_576,
           output_tokens=60_000, cost_usd=1.0):
    item = BudgetLedger(tmp_path / "budget.json")
    item.limits.update({
        "requests": requests, "input_tokens": input_tokens,
        "output_tokens": output_tokens, "cost_usd": cost_usd,
    })
    data = item.snapshot()
    data["limits"] = dict(item.limits)
    item._write(data)
    return item


def test_stop_when_actual_input_reaches_threshold(tmp_path):
    budget = ledger(tmp_path)
    data = budget.snapshot()
    data["used"]["input_tokens"] = 300_000
    budget._write(data)
    calls = []
    budget.reserve = lambda **kwargs: calls.append(kwargs)
    wrapper = install_baseline_admission(
        budget, actual_input_stop=300_000, request_input_cap=1_048_576)
    with pytest.raises(EvaluationBudgetStop) as caught:
        wrapper(payload={"messages": []}, max_output_tokens=100)
    assert str(caught.value) == "baseline_actual_input_stop_reached"
    assert calls == []
    snapshot = budget.snapshot()
    assert snapshot["stopped"] is True
    assert snapshot["events"][-1]["event"] == "run_stopped"
    assert "300000>=300000" in snapshot["events"][-1]["reason"]


def test_reject_oversize_single_reservation_before_ledger(tmp_path):
    budget = ledger(tmp_path)
    calls = []
    budget.reserve = lambda **kwargs: calls.append(kwargs)
    wrapper = install_baseline_admission(
        budget, actual_input_stop=300_000, request_input_cap=1_048_576)
    with pytest.raises(EvaluationBudgetStop) as caught:
        wrapper(payload={"messages": []}, max_output_tokens=100,
                input_token_upper_bound=1_048_577)
    assert str(caught.value) == "baseline_request_input_reservation_exceeds_cap"
    assert calls == []
    assert budget.snapshot()["stopped"] is True


def test_oversize_payload_is_rejected_without_send(tmp_path):
    budget = ledger(tmp_path)
    calls = []
    budget.reserve = lambda **kwargs: calls.append(kwargs)
    wrapper = install_baseline_admission(
        budget, actual_input_stop=300_000, request_input_cap=1_048_576)
    payload = {"messages": [{"role": "user", "content": "x" * 1_200_000}]}
    with pytest.raises(EvaluationBudgetStop) as caught:
        wrapper(payload=payload, max_output_tokens=100)
    assert str(caught.value) == "baseline_request_input_reservation_exceeds_cap"
    assert calls == []


def test_normal_reservation_reaches_real_ledger(tmp_path):
    budget = ledger(tmp_path)
    wrapper = install_baseline_admission(
        budget, actual_input_stop=300_000, request_input_cap=1_048_576)
    reservation = wrapper(
        run_id="synthetic", case_id="P01", request_id="r1",
        payload={"messages": []}, max_output_tokens=100,
        input_token_upper_bound=73_797,
    )
    assert reservation["input_tokens"] == 73_797
    assert budget.snapshot()["pending"]["request_id"] == "r1"


def test_insufficient_ledger_budget_fails_closed(tmp_path):
    budget = ledger(tmp_path, requests=1, input_tokens=1_000,
                    output_tokens=100, cost_usd=1.0)
    wrapper = install_baseline_admission(
        budget, actual_input_stop=300_000, request_input_cap=1_048_576)
    wrapper(run_id="synthetic", case_id="P01", request_id="r1",
            payload={"messages": []}, max_output_tokens=40,
            input_token_upper_bound=900)
    budget.settle(response={"model": "deepseek-flash",
                            "usage": {"prompt_tokens": 900, "completion_tokens": 40}},
                  http_status=200)
    with pytest.raises(EvaluationBudgetStop) as caught:
        wrapper(run_id="synthetic", case_id="P01", request_id="r2",
                payload={"messages": []}, max_output_tokens=40,
                input_token_upper_bound=900)
    assert str(caught.value) == "budget_would_be_exceeded"
    assert budget.snapshot()["stopped"] is True


def test_remaining_cost_shortfall_fails_closed(tmp_path):
    budget = ledger(tmp_path, requests=30, input_tokens=1_348_576,
                    output_tokens=60_000, cost_usd=0.001)
    wrapper = install_baseline_admission(
        budget, actual_input_stop=300_000, request_input_cap=1_048_576)
    wrapper(run_id="synthetic", case_id="P01", request_id="r1",
            payload={"messages": []}, max_output_tokens=40,
            input_token_upper_bound=900)
    budget.settle(response={"model": "deepseek-flash",
                            "usage": {"prompt_tokens": 900, "completion_tokens": 40}},
                  http_status=200)
    used = budget.snapshot()["used"]
    assert used["requests"] == 1
    assert used["input_tokens"] == 900
    with pytest.raises(EvaluationBudgetStop) as caught:
        wrapper(run_id="synthetic", case_id="P01", request_id="r2",
                payload={"messages": []}, max_output_tokens=40,
                input_token_upper_bound=900)
    assert str(caught.value) == "budget_would_be_exceeded"
    event = budget.snapshot()["events"][-1]
    assert event["event"] == "reserve_rejected"
    assert event["requested"]["cost_usd"] > 0
    assert event["used"]["requests"] == 1


def test_guard_send_boundary_stops_before_transport(tmp_path, monkeypatch):
    from app.eval_request_guard import (
        begin_eval_request,
        configure_eval_guard,
        reset_eval_guard,
    )

    monkeypatch.setenv("P12_EVAL_MODE", "1")
    monkeypatch.setenv("P12_EVAL_FORMAL_HTTP", "1")
    monkeypatch.setenv("P12_EVAL_MOCK_PROVIDER", "1")
    monkeypatch.setenv("P12_EXPECTED_PROVIDER", "deepseek")
    monkeypatch.setenv("P12_EXPECTED_MODEL", "deepseek-flash")
    budget = ledger(tmp_path)
    data = budget.snapshot()
    data["used"]["input_tokens"] = 300_000
    budget._write(data)
    wrapper = install_baseline_admission(
        budget, actual_input_stop=300_000, request_input_cap=1_048_576)
    configure_eval_guard(budget)
    try:
        with pytest.raises(EvaluationBudgetStop) as caught:
            begin_eval_request(
                provider="deepseek",
                model="deepseek-flash",
                target_url="https://api.deepseek.com/chat/completions",
                payload={"model": "deepseek-flash", "messages": []},
                max_output_tokens=100,
                mock_transport=True,
            )
    finally:
        reset_eval_guard()
    assert str(caught.value) == "baseline_actual_input_stop_reached"
    snapshot = budget.snapshot()
    assert snapshot["stopped"] is True
    assert snapshot["events"][-1]["reason"] == (
        "baseline_actual_input_stop_reached:300000>=300000"
    )


def test_zero_threshold_and_cap_disable_checks(tmp_path):
    budget = ledger(tmp_path, input_tokens=3_000_000)
    wrapper = install_baseline_admission(
        budget, actual_input_stop=0, request_input_cap=0)
    reservation = wrapper(
        run_id="synthetic", case_id="P01", request_id="r1",
        payload={"messages": []}, max_output_tokens=100,
        input_token_upper_bound=1_500_000,
    )
    assert reservation["input_tokens"] == 1_500_000
