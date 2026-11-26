"""CAD-E2E-LIVE-PREFLIGHT-FINAL-03 directed gate tests.

All tests are offline.  No provider socket is opened, no real model is called.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import agent_http_service, agent_service
from app.agent_service import PendingAction, RobotAgentService
from app.eval_request_guard import (
    EvalRequestBlocked,
    begin_eval_request,
    configure_eval_guard,
    reset_eval_guard,
    settle_eval_response,
)
from app.schemas import AgentChatRequest
from tests.manual.eval_budget_store import (
    BudgetLedger,
    EvaluationBudgetStop,
)


def _calibration_payload(*, extra: dict | None = None, messages: list | None = None) -> dict:
    payload = {
        "model": "deepseek-flash",
        "messages": messages or [
            {"role": "system", "content": "CAD construction system prompt"},
            {"role": "user", "content": "画一个矩形宽4米高2米，在四个角各放一个半径0.5米的圆"},
        ],
        "thinking": {"type": "disabled"},
        "max_tokens": 8192,
    }
    if extra:
        payload.update(extra)
    return payload


def _payload_sha(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()


def calibration_env(monkeypatch, tmp_path, *, payload: dict | None = None, sha: str | None = None):
    payload = payload if payload is not None else _calibration_payload()
    monkeypatch.setenv("P12_EVAL_MODE", "1")
    monkeypatch.setenv("P12_EVAL_FORMAL_HTTP", "1")
    monkeypatch.setenv("P12_EXPECTED_PROVIDER", "deepseek")
    monkeypatch.setenv("P12_EXPECTED_MODEL", "deepseek-flash")
    monkeypatch.setenv("P12_EVAL_CASE_ID", "C7")
    monkeypatch.setenv("P12_EVAL_CALIBRATION_MODE", "1")
    monkeypatch.setenv("P12_EVAL_CALIBRATION_PAYLOAD_SHA256", sha or _payload_sha(payload))
    monkeypatch.setenv(
        "P12_EVAL_CALIBRATION_BODY_BYTES",
        str(len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))),
    )
    monkeypatch.setenv("P12_MAX_REQUESTS", "1")
    monkeypatch.setenv("P12_MAX_INPUT_TOKENS", "1000000")
    monkeypatch.setenv("P12_MAX_OUTPUT_TOKENS", "100000")
    monkeypatch.setenv("P12_MAX_COST_USD", "100")
    monkeypatch.setenv("P12_REAL_MODEL_AUTHORIZED", "1")
    ledger = BudgetLedger(tmp_path / "budget.json")
    configure_eval_guard(ledger)
    return ledger, payload


def begin(payload: dict, **overrides):
    values = {
        "provider": "deepseek",
        "model": "deepseek-flash",
        "target_url": "https://api.deepseek.com/chat/completions",
        "payload": payload,
        "max_output_tokens": int(payload.get("max_tokens") or 0),
    }
    values.update(overrides)
    return begin_eval_request(**values)


def teardown_function():
    reset_eval_guard()


# G2: C7 first request shape and fingerprint.
def test_calibration_first_request_is_admitted_and_then_stopped(tmp_path, monkeypatch):
    ledger, payload = calibration_env(monkeypatch, tmp_path)
    reservation = begin(payload)
    assert ledger.snapshot()["pending"]["request_id"] == reservation.request_id
    with pytest.raises(EvalRequestBlocked) as caught:
        settle_eval_response(
            reservation,
            {
                "model": "deepseek-flash",
                "usage": {"prompt_tokens": 100, "completion_tokens": 10},
            },
            http_status=200,
        )
    assert "calibration_request_completed_run_stopped" in str(caught.value)
    snapshot = ledger.snapshot()
    assert snapshot["stopped"] is True
    assert snapshot["pending"] is None
    assert snapshot["used"]["requests"] == 1
    assert any(event["event"] == "run_stopped" for event in snapshot["events"])
    with pytest.raises((EvaluationBudgetStop, EvalRequestBlocked)):
        begin(payload)


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (_calibration_payload(extra={"tools": [{"type": "function"}]}), "tools"),
        (
            _calibration_payload(
                messages=[
                    {"role": "system", "content": "system"},
                    {"role": "user", "content": "user"},
                    {"role": "assistant", "content": "extra"},
                ]
            ),
            "message_count",
        ),
        (
            _calibration_payload(
                messages=[
                    {"role": "user", "content": "user"},
                    {"role": "assistant", "content": "assistant"},
                ]
            ),
            "roles",
        ),
        (_calibration_payload(extra={"thinking": None}), "thinking"),
        (_calibration_payload(extra={"stream": True}), "stream"),
    ],
)
def test_calibration_shape_mismatch_is_rejected_before_network(
    tmp_path, monkeypatch, payload, reason
):
    ledger, expected = calibration_env(monkeypatch, tmp_path)
    # Give a matching fingerprint so the test isolates the shape predicate.
    monkeypatch.setenv("P12_EVAL_CALIBRATION_PAYLOAD_SHA256", _payload_sha(payload))
    monkeypatch.setenv(
        "P12_EVAL_CALIBRATION_BODY_BYTES",
        str(len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))),
    )
    with pytest.raises(EvalRequestBlocked) as caught:
        begin(payload)
    assert reason in str(caught.value)
    snapshot = ledger.snapshot()
    assert snapshot["used"]["requests"] == 0
    assert snapshot["pending"] is None


def test_calibration_payload_fingerprint_mismatch_is_rejected(tmp_path, monkeypatch):
    ledger, payload = calibration_env(monkeypatch, tmp_path, sha="0" * 64)
    with pytest.raises(EvalRequestBlocked) as caught:
        begin(payload)
    assert "fingerprint_mismatch" in str(caught.value)
    assert ledger.snapshot()["used"]["requests"] == 0


def test_calibration_rejects_second_request_after_failed_attempt(tmp_path, monkeypatch):
    ledger, payload = calibration_env(monkeypatch, tmp_path)
    reservation = begin(payload)
    from app.eval_request_guard import fail_eval_request
    fail_eval_request(reservation, OSError("synthetic network failure"))
    snapshot = ledger.snapshot()
    assert snapshot["stopped"] is True
    assert snapshot["used"]["requests"] == 1
    with pytest.raises((EvaluationBudgetStop, EvalRequestBlocked)):
        begin(payload)


def test_calibration_rejects_mock_transport(tmp_path, monkeypatch):
    ledger, payload = calibration_env(monkeypatch, tmp_path)
    monkeypatch.setenv("P12_EVAL_MOCK_PROVIDER", "1")
    with pytest.raises(EvalRequestBlocked) as caught:
        begin(payload, mock_transport=True)
    assert "calibration_requires_real_transport" in str(caught.value)


# G3: confirm path fatal propagation.
def _confirm_service(monkeypatch, exc: BaseException):
    monkeypatch.setattr(RobotAgentService, "configured", property(lambda self: True))
    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "deepseek"
    context = {"tool": "drive_robot", "arguments": {}}
    context["sha256"] = hashlib.sha256(
        json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    action = PendingAction(
        name="drive_robot",
        arguments={},
        expires_at=datetime.now() + timedelta(hours=1),
        mode="base",
        owner_id="local-default",
        execution_context=context,
    )
    service.pending["action-1"] = action
    monkeypatch.setattr(agent_service.agent_tasks, "get", lambda *a, **k: None)
    monkeypatch.setattr(agent_service.agent_tasks, "transition", lambda *a, **k: None)
    monkeypatch.setattr(agent_service, "agent_tool_policy", lambda *a, **k: {"allowed": True})
    monkeypatch.setattr(
        agent_service,
        "build_action_preflight",
        lambda *a, **k: {"ready": True, "checks": []},
    )
    monkeypatch.setattr(agent_service.robot_state, "snapshot", lambda *a, **k: {})
    monkeypatch.setattr(
        service,
        "_execute_confirmed",
        lambda *a, **k: (_ for _ in ()).throw(exc),
    )
    return service


def test_confirm_fatal_is_not_swallowed(monkeypatch):
    service = _confirm_service(monkeypatch, EvalRequestBlocked("evaluation_aborted"))
    with pytest.raises(EvalRequestBlocked):
        service._confirm_impl("action-1", True)


def test_confirm_ordinary_failure_still_returns_failure(monkeypatch):
    service = _confirm_service(monkeypatch, RuntimeError("synthetic tool failure"))
    result = service._confirm_impl("action-1", True)
    assert result["ok"] is False
    assert "Agent 工具执行异常" in result["message"]


# G4: streaming HTTP fatal marker then termination.
def test_streaming_http_emits_fatal_marker_before_raising(monkeypatch):
    command = AgentChatRequest(message="画一个矩形", mode="advanced", client_id="u")
    monkeypatch.setattr(
        agent_http_service.agent_runs,
        "create",
        lambda *a, **k: {"id": "run-1"},
    )
    monkeypatch.setattr(agent_http_service.agent_runs, "transition", lambda *a, **k: None)
    monkeypatch.setattr(
        agent_http_service,
        "_prepare_run_step",
        lambda *a, **k: {},
    )

    def fatal_events(*args, **kwargs):
        yield json.dumps({"type": "delta", "text": "partial"}) + "\n"
        raise EvalRequestBlocked("evaluation_aborted_by_ledger")

    monkeypatch.setattr(agent_http_service, "_agent_chat_stream_events", fatal_events)
    response = agent_http_service.agent_chat_stream(command)

    async def consume():
        chunks = []
        with pytest.raises(EvalRequestBlocked):
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
        return chunks

    chunks = asyncio.run(consume())
    marker = json.loads([line for line in "".join(chunks).splitlines() if line.strip()][-1])
    assert marker["type"] == "evaluation_aborted"
    assert marker["fatal"] is True
    assert marker["error_code"] == "evaluation_aborted"
    assert marker["error_type"] == "EvalRequestBlocked"
    assert marker["agent_run_id"] == "run-1"


def test_resume_rethrows_fatal_instead_of_failure_result(monkeypatch):
    context = {}
    context["sha256"] = hashlib.sha256(b"{}").hexdigest()
    run = {
        "id": "run-1",
        "state": "paused",
        "user_id": "u",
        "conversation_id": "c",
        "user_message": "画一个矩形",
        "mode": "advanced",
        "execution_context": context,
        "drawing_selection": None,
        "pending_command": None,
        "checkpoint": {"step_id": "result_generated", "result": {}},
    }
    monkeypatch.setattr(agent_http_service.agent_runs, "get", lambda *a, **k: run)
    monkeypatch.setattr(
        agent_http_service.agent_runs,
        "resume",
        lambda *a, **k: {**run, "state": "planning", "attempts": 0},
    )
    monkeypatch.setattr(agent_http_service.agent_runs, "transition", lambda *a, **k: None)
    monkeypatch.setattr(
        agent_http_service,
        "_finalize_run_result",
        lambda *a, **k: (_ for _ in ()).throw(EvalRequestBlocked("evaluation_aborted")),
    )
    with pytest.raises(EvalRequestBlocked):
        agent_http_service.resume_agent_run("run-1", "u")


# G4: structured review 6078 ValueError branch rethrows fatal.
def test_structured_review_value_error_branch_rethrows_fatal(monkeypatch):
    monkeypatch.setattr(RobotAgentService, "configured", property(lambda self: True))
    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "deepseek"

    class FatalValueError(ValueError):
        eval_fatal = True

    monkeypatch.setattr(
        service,
        "_structured_review_text",
        lambda *a, **k: (_ for _ in ()).throw(FatalValueError("fatal in 6078 branch")),
    )
    monkeypatch.setattr(
        agent_service,
        "get_creative_project_store",
        lambda *a, **k: type("Store", (), {"get": lambda self, *a, **k: None})(),
    )
    route = {
        "name": "drawing_design",
        "operation": "modify",
        "decision_source": "rules",
        "edit_domain": "candidate_variant",
    }
    with pytest.raises(FatalValueError):
        service._structured_cad_edit_fallback("把矩形宽度改成5米", [], route, "advanced")


# G4: worker process emits the machine-readable fatal marker.
def test_worker_emits_machine_fatal_marker_for_stream_abort(tmp_path):
    worker = Path(__file__).with_name("manual") / "cad_widget_live_worker.py"
    result = subprocess.run(
        [sys.executable, str(worker), "--output", str(tmp_path / "fatal-probe")],
        input=json.dumps({"operation": "fatal_probe"}),
        text=True,
        capture_output=True,
        timeout=120,
        encoding="utf-8",
    )
    assert result.returncode != 0
    marker_lines = [
        line for line in (result.stderr or "").splitlines()
        if line.startswith("P12_EVAL_FATAL:")
    ]
    assert marker_lines
    marker = json.loads(marker_lines[0].split(":", 1)[1])
    assert marker["type"] == "EvalRequestBlocked"
    assert "evaluation_aborted" in marker["message"]
