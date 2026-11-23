"""Negative acceptance tests for the P0-04 control-plane authorization gate."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from app.security import (
    AUTH_ADMIN_TOKEN_ENV,
    AUTH_MODE_ENV,
    AUTH_SECRET_ENV,
    AuthError,
    AuthManager,
    ControlAuthMiddleware,
    decode_token,
    issue_token,
    required_scope,
)

SECRET = "release-blocker-01-test-secret-32-chars"


@pytest.fixture()
def enforced(monkeypatch):
    monkeypatch.setenv(AUTH_MODE_ENV, "enforced")
    monkeypatch.setenv(AUTH_SECRET_ENV, SECRET)
    monkeypatch.setenv("XLINE_DEPLOYMENT_PROFILE", "test")
    monkeypatch.delenv(AUTH_ADMIN_TOKEN_ENV, raising=False)


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ControlAuthMiddleware)

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/api/status")
    async def status():
        return {"ok": True}

    @app.post("/api/cmd_vel")
    async def cmd_vel(payload: dict):
        return {"client_id": payload.get("client_id"), "confirmed": payload.get("confirmed")}

    @app.get("/api/database/backup")
    async def database_backup():
        return {"ok": True}

    @app.websocket("/ws/rosbridge")
    async def ws(websocket: WebSocket):
        principal = websocket.state.auth
        await websocket.accept()
        await websocket.send_json({"subject": principal.subject})

    return app


def _headers(token: str, request_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if request_id:
        headers["X-XLine-Request-Id"] = request_id
    return headers


def test_anonymous_and_forged_tokens_are_rejected_before_side_effects(enforced):
    client = TestClient(_app())
    assert client.get("/health").status_code == 200
    assert client.get("/api/status").status_code == 401
    assert client.post("/api/cmd_vel", json={"client_id": "spoof", "confirmed": True}).status_code == 401
    assert client.get("/api/status", headers={"Authorization": "Bearer forged"}).status_code == 401
    assert client.get("/api/status", headers={"X-XLine-Token": "xla1.e30.bad"}).status_code == 401


def test_expired_and_scope_violations_are_rejected(enforced):
    expired = issue_token("operator-a", secret=SECRET, role="operator", ttl_seconds=1, now=10)
    client = TestClient(_app())
    assert client.get("/api/status", headers=_headers(expired)).status_code == 401

    readonly = issue_token("viewer", secret=SECRET, role="readonly")
    assert client.get("/api/status", headers=_headers(readonly)).status_code == 200
    assert client.post(
        "/api/cmd_vel",
        headers=_headers(readonly, "req-readonly-001"),
        json={"client_id": "viewer", "confirmed": True},
    ).status_code == 403
    assert client.get("/api/database/backup", headers=_headers(readonly)).status_code == 403


def test_request_id_is_required_and_replay_is_rejected(enforced):
    operator = issue_token("operator-b", secret=SECRET, role="operator")
    client = TestClient(_app())
    assert client.post(
        "/api/cmd_vel",
        headers=_headers(operator),
        json={"client_id": "operator-b", "confirmed": True},
    ).status_code == 401
    request_id = "req-operator-b-001"
    response = client.post(
        "/api/cmd_vel",
        headers=_headers(operator, request_id),
        json={"client_id": "operator-b", "confirmed": True},
    )
    assert response.status_code == 200
    assert client.post(
        "/api/cmd_vel",
        headers=_headers(operator, request_id),
        json={"client_id": "operator-b", "confirmed": True},
    ).status_code == 409


def test_body_client_id_is_rebound_to_authenticated_subject(enforced):
    operator = issue_token("operator-c", secret=SECRET, role="operator")
    client = TestClient(_app())
    response = client.post(
        "/api/cmd_vel",
        headers=_headers(operator, "req-operator-c-001"),
        json={"client_id": "spoofed-client", "confirmed": True, "linear_x": 0.1},
    )
    assert response.status_code == 200
    assert response.json()["client_id"] == "operator-c"


def test_websocket_without_token_is_closed_before_accept(enforced):
    client = TestClient(_app())
    with pytest.raises(Exception) as caught:
        with client.websocket_connect("/ws/rosbridge"):
            pass
    message = f"{caught.value!r} {caught.value}"
    code = getattr(caught.value, "code", None)
    assert code == 1008 or "1008" in message or "policy violation" in message.lower()


def test_websocket_authenticated_subject_is_bound(enforced):
    operator = issue_token("operator-ws", secret=SECRET, role="operator")
    client = TestClient(_app())
    with client.websocket_connect("/ws/rosbridge", headers={"X-XLine-Token": operator}) as socket:
        assert socket.receive_json() == {"subject": "operator-ws"}


def test_token_decode_contract_and_scope_table():
    token = issue_token("operator-d", secret=SECRET, role="operator", now=100)
    principal = decode_token(token, secret=SECRET, now=101)
    assert principal.subject == "operator-d"
    assert principal.has_scope("control")
    assert not principal.has_scope("database")
    with pytest.raises(Exception):
        decode_token(token, secret=SECRET, now=10_000)
    with pytest.raises(Exception):
        decode_token(token + "tampered", secret=SECRET, now=101)
    assert required_scope("POST", "/api/cmd_vel") == "control"
    assert required_scope("GET", "/api/status") == "read"
    assert required_scope("GET", "/health") is None
    assert required_scope("GET", "/api/database/backup") == "database"


def test_production_startup_refuses_missing_or_disabled_auth():
    with pytest.raises(AuthError):
        AuthManager({"XLINE_DEPLOYMENT_PROFILE": "production"}).assert_ready()
    with pytest.raises(AuthError):
        AuthManager({
            "XLINE_DEPLOYMENT_PROFILE": "production",
            AUTH_MODE_ENV: "disabled",
            AUTH_SECRET_ENV: SECRET,
        }).assert_ready()
    with pytest.raises(AuthError):
        AuthManager({
            "XLINE_DEPLOYMENT_PROFILE": "production",
            AUTH_MODE_ENV: "enforced",
            AUTH_SECRET_ENV: "short",
        }).assert_ready()

    token = issue_token("startup-operator", secret=SECRET, role="operator")
    AuthManager({
        "XLINE_DEPLOYMENT_PROFILE": "production",
        AUTH_MODE_ENV: "enforced",
        AUTH_SECRET_ENV: SECRET,
        "XLINE_CONTROL_AUTH_TOKEN": token,
    }).assert_ready()
