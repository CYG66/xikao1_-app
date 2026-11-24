"""AUTH-FINAL-01: granular scopes and long-lived WebSocket expiry."""
from __future__ import annotations

import pytest
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.security as security
from app.ros_adapter import ros_adapter
from app.routers.rosbridge import websocket_rosbridge
from app.security import (
    AUTH_ADMIN_TOKEN_ENV,
    AUTH_MODE_ENV,
    AUTH_SECRET_ENV,
    AuthError,
    ControlAuthMiddleware,
    issue_token,
    principal_expired,
    required_scope,
    require_request_scope,
)
from app.state import robot_state

SECRET = "auth-final-01-test-secret-32-chars"


@pytest.fixture()
def enforced(monkeypatch):
    monkeypatch.setenv(AUTH_MODE_ENV, "enforced")
    monkeypatch.setenv(AUTH_SECRET_ENV, SECRET)
    monkeypatch.setenv("XLINE_DEPLOYMENT_PROFILE", "test")
    monkeypatch.delenv(AUTH_ADMIN_TOKEN_ENV, raising=False)


def _http_app() -> FastAPI:
    app = FastAPI()

    async def auth_error(_request: Request, error: AuthError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={"ok": False, "code": error.code, "detail": str(error)},
        )

    app.add_exception_handler(AuthError, auth_error)
    app.add_middleware(ControlAuthMiddleware)

    @app.post("/api/printer/quick_command")
    async def printer(request: Request):
        require_request_scope(request, "printer")
        return {"ok": True, "operation": "printer"}

    @app.post("/api/mission/control")
    async def mission(request: Request):
        require_request_scope(request, "mission")
        return {"ok": True, "operation": "mission"}

    @app.post("/api/ln150/command")
    async def ln150(request: Request):
        require_request_scope(request, "hardware")
        return {"ok": True, "operation": "ln150"}

    @app.post("/api/emergency-stop")
    async def emergency_stop():
        return {"ok": True, "operation": "stop"}

    @app.post("/api/control-probe")
    async def control_probe(request: Request):
        # The middleware only requires read for this probe path; the route's
        # own printer check must still reject a read+control principal.
        require_request_scope(request, "printer")
        return {"ok": True}

    return app


def _ws_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ControlAuthMiddleware)
    app.add_api_websocket_route("/ws/rosbridge", websocket_rosbridge)
    return app


def _headers(token: str, request_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-XLine-Request-Id": request_id,
    }


def _receive_op(socket, expected: str) -> dict:
    for _ in range(4):
        message = socket.receive_json()
        if message.get("op") == expected:
            return message
    raise AssertionError(f"did not receive {expected}")


def _reset_control_lease() -> None:
    if robot_state.control_owner:
        ros_adapter.release_control(robot_state.control_owner, "auth-final-01 test reset")


def test_required_scope_contract():
    assert required_scope("POST", "/api/printer/quick_command") == "printer"
    assert required_scope("POST", "/api/printer/set_active") == "printer"
    assert required_scope("POST", "/api/mission/control") == "mission"
    assert required_scope("POST", "/api/ln150/command") == "hardware"
    assert required_scope("POST", "/api/cmd_vel") == "control"
    assert required_scope("POST", "/api/emergency-stop") == "control"
    assert required_scope("GET", "/ws/rosbridge") == "control"


def test_http_control_only_token_cannot_use_printer_or_mission(enforced):
    control_only = issue_token(
        "control-only", secret=SECRET, role="operator", scopes={"control"}
    )
    printer_only = issue_token(
        "printer-only", secret=SECRET, role="operator", scopes={"printer"}
    )
    mission_only = issue_token(
        "mission-only", secret=SECRET, role="operator", scopes={"mission"}
    )
    hardware_only = issue_token(
        "hardware-only", secret=SECRET, role="operator", scopes={"hardware"}
    )
    client = TestClient(_http_app())

    assert client.post(
        "/api/printer/quick_command",
        headers=_headers(control_only, "req-auth-final-printer-denied"),
        json={"printer_name": "center"},
    ).status_code == 403
    assert client.post(
        "/api/printer/quick_command",
        headers=_headers(printer_only, "req-auth-final-printer-allowed"),
        json={"printer_name": "center"},
    ).status_code == 200
    assert client.post(
        "/api/mission/control",
        headers=_headers(control_only, "req-auth-final-mission-denied"),
        json={"action": "start"},
    ).status_code == 403
    assert client.post(
        "/api/mission/control",
        headers=_headers(mission_only, "req-auth-final-mission-allowed"),
        json={"action": "start"},
    ).status_code == 200
    assert client.post(
        "/api/ln150/command",
        headers=_headers(control_only, "req-auth-final-hardware-denied"),
        json={"command_type": 1},
    ).status_code == 403
    assert client.post(
        "/api/ln150/command",
        headers=_headers(hardware_only, "req-auth-final-hardware-allowed"),
        json={"command_type": 1},
    ).status_code == 200
    # Safety stop remains available to a control-only token.
    assert client.post(
        "/api/emergency-stop",
        headers=_headers(control_only, "req-auth-final-stop"),
        json={"active": True},
    ).status_code == 200
    # Route-level defense still rejects even when the path-level requirement
    # would have allowed the request.
    read_control = issue_token(
        "read-control", secret=SECRET, role="operator", scopes={"read", "control"}
    )
    assert client.post(
        "/api/control-probe",
        headers=_headers(read_control, "req-auth-final-probe"),
        json={},
    ).status_code == 403
    # The deployed operator role remains a superset and keeps all original paths.
    operator = issue_token("operator", secret=SECRET, role="operator")
    assert client.post(
        "/api/printer/quick_command",
        headers=_headers(operator, "req-auth-final-operator-printer"),
        json={"printer_name": "center"},
    ).status_code == 200
    assert client.post(
        "/api/mission/control",
        headers=_headers(operator, "req-auth-final-operator-mission"),
        json={"action": "start"},
    ).status_code == 200
    assert client.post(
        "/api/ln150/command",
        headers=_headers(operator, "req-auth-final-operator-hardware"),
        json={"command_type": 1},
    ).status_code == 200


def test_ws_control_lease_does_not_grant_printer_or_mission(enforced):
    _reset_control_lease()
    control_only = issue_token(
        "ws-control-only", secret=SECRET, role="operator", scopes={"control"}
    )
    client = TestClient(_ws_app())
    with client.websocket_connect("/ws/rosbridge", headers={"X-XLine-Token": control_only}) as socket:
        assert socket.receive_json()["op"] == "status"
        socket.send_json({"op": "claim_control"})
        assert _receive_op(socket, "control_response")["ok"] is True
        socket.send_json({
            "op": "call_service",
            "service": "/printer/quick_command",
            "args": {"printer_name": "center", "action": "beep", "param": 0},
        })
        printer_response = _receive_op(socket, "service_response")
        assert printer_response["ok"] is False
        assert "printer scope" in printer_response["message"]
        socket.send_json({"op": "mission_control", "action": "start", "file_name": "x.json"})
        mission_response = _receive_op(socket, "mission_response")
        assert mission_response["ok"] is False
        assert "mission scope" in mission_response["message"]


def test_ws_expired_token_is_closed_and_lease_released(enforced, monkeypatch):
    _reset_control_lease()
    clock = [100]
    monkeypatch.setattr(security, "auth_clock", lambda: clock[0])
    token = issue_token(
        "ws-expiry", secret=SECRET, role="operator", ttl_seconds=1, now=clock[0]
    )
    assert principal_expired(
        security.decode_token(token, secret=SECRET, now=100), now=100
    ) is False
    assert principal_expired(
        security.decode_token(token, secret=SECRET, now=100), now=101
    ) is True

    client = TestClient(_ws_app())
    with client.websocket_connect("/ws/rosbridge", headers={"X-XLine-Token": token}) as socket:
        assert socket.receive_json()["op"] == "status"
        socket.send_json({"op": "claim_control"})
        assert _receive_op(socket, "control_response")["ok"] is True
        assert robot_state.control_owner == "ws-expiry"
        clock[0] = 101
        socket.send_json({"op": "control_heartbeat"})
        with pytest.raises(WebSocketDisconnect) as caught:
            _receive_op(socket, "control_heartbeat_response")
        assert caught.value.code == 1008
    assert robot_state.control_owner is None
