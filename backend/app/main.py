from __future__ import annotations

import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .ros_adapter import ros_adapter
from .agent_service import robot_agent
from .schemas import (
    AgentChatRequest,
    AgentConfirmRequest,
    AgentConfigCommand,
    ApiResult,
    Ln150Command,
    MissionCommand,
    PrinterActiveCommand,
    PrinterCommand,
    VelocityCommand,
)
from .state import robot_state

app = FastAPI(title="XLine Rover Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    ros_adapter.start()


@app.on_event("shutdown")
def shutdown() -> None:
    ros_adapter.stop()


@app.get("/health")
def health() -> dict[str, object]:
    return {"ok": True, "status": robot_state.snapshot()}


@app.get("/api/status")
def status() -> dict[str, object]:
    return robot_state.snapshot()


@app.get("/api/logs")
def logs() -> dict[str, list[str]]:
    return {"logs": robot_state.logs}


@app.get("/api/agent/status")
def agent_status() -> dict[str, object]:
    return robot_agent.config()


@app.get("/api/agent/config")
def agent_config() -> dict[str, object]:
    return robot_agent.config()


@app.post("/api/agent/config")
def update_agent_config(command: AgentConfigCommand) -> dict[str, object]:
    return robot_agent.update_config(
        command.mode,
        command.model,
        command.api_key,
        command.clear_api_key,
    )


@app.post("/api/agent/test")
def test_agent_config() -> dict[str, object]:
    return robot_agent.test_connection()


@app.post("/api/agent/chat")
def agent_chat(command: AgentChatRequest) -> dict[str, object]:
    try:
        return robot_agent.chat(
            command.message,
            [message.model_dump() for message in command.history],
        )
    except RuntimeError as error:
        robot_state.add_log(f"agent error: {error}")
        return {
            "ok": False,
            "configured": robot_agent.configured,
            "message": str(error),
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "pending_action": None,
        }


@app.post("/api/agent/confirm")
def agent_confirm(command: AgentConfirmRequest) -> dict[str, object]:
    return robot_agent.confirm(command.action_id, command.approved)


@app.post("/api/cmd_vel", response_model=ApiResult)
def cmd_vel(command: VelocityCommand) -> ApiResult:
    ok = ros_adapter.publish_velocity(command.linear, command.angular)
    return ApiResult(
        ok=ok,
        message="velocity command sent" if ok else "USB2CAN motor driver is not ready",
    )


@app.post("/api/printer/quick_command", response_model=ApiResult)
def printer(command: PrinterCommand) -> ApiResult:
    ok = ros_adapter.call_printer(command.printer_name, command.action, command.param)
    return ApiResult(ok=ok, message="printer command accepted" if ok else "printer service unavailable")


@app.post("/api/ln150/command", response_model=ApiResult)
def ln150(command: Ln150Command) -> ApiResult:
    ok = ros_adapter.call_ln150(command.command_type)
    return ApiResult(ok=ok, message="ln150 command accepted" if ok else "ln150 service unavailable")


@app.post("/api/mission/control", response_model=ApiResult)
def mission(command: MissionCommand) -> ApiResult:
    ok = ros_adapter.control_mission(command.running, command.file_name)
    return ApiResult(ok=ok, message="mission request accepted" if ok else robot_state.mission_error or "mission request rejected")


@app.post("/api/printer/set_active", response_model=ApiResult)
def printer_active(command: PrinterActiveCommand) -> ApiResult:
    ok = ros_adapter.set_printer_active(command.printer_name, command.active)
    return ApiResult(ok=ok, message="printer active state submitted" if ok else "printer/set_active unavailable")


@app.websocket("/ws/status")
async def websocket_status(websocket: WebSocket) -> None:
    await websocket.accept()
    robot_state.add_log("websocket client connected")
    try:
        while True:
            await websocket.send_json(robot_state.snapshot())
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        robot_state.add_log("websocket client disconnected")


@app.websocket("/")
@app.websocket("/ws/rosbridge")
async def websocket_rosbridge(websocket: WebSocket) -> None:
    await websocket.accept()
    robot_state.add_log("rosbridge-compatible client connected")
    await websocket.send_json({"op": "status", "msg": robot_state.snapshot()})
    try:
        while True:
            try:
                payload = await asyncio.wait_for(websocket.receive_json(), timeout=1)
                result = handle_rosbridge_payload(payload)
                await websocket.send_json(result)
            except asyncio.TimeoutError:
                await websocket.send_json({"op": "status", "msg": robot_state.snapshot()})
    except WebSocketDisconnect:
        robot_state.add_log("rosbridge-compatible client disconnected")


def handle_rosbridge_payload(payload: dict[str, object]) -> dict[str, object]:
    op = payload.get("op")
    topic = payload.get("topic")
    service = payload.get("service")

    if op == "subscribe":
        robot_state.add_log(f"subscribe {topic}")
        return {"op": "subscribed", "topic": topic, "ok": True}

    if op == "publish" and topic == "/tablet_cmd_vel":
        message = payload.get("msg")
        if isinstance(message, dict):
            linear = _nested_number(message, "linear", "x")
            angular = _nested_number(message, "angular", "z")
            ok = ros_adapter.publish_velocity(linear, angular)
            return {
                "op": "published",
                "topic": topic,
                "ok": ok,
                "message": "velocity command sent" if ok else "USB2CAN motor driver is not ready",
            }

    if op == "mission_control":
        running = payload.get("running") is True
        file_name = str(payload.get("file_name", "test_pattern.json"))
        ok = ros_adapter.control_mission(running, file_name)
        return {"op": "mission_response", "ok": ok, "message": robot_state.mission_error}

    if op == "call_service" and service == "/printer/quick_command":
        args = payload.get("args")
        if isinstance(args, dict):
            ok = ros_adapter.call_printer(
                str(args.get("printer_name", "center")),
                str(args.get("action", "beep")),
                int(args.get("param", 0)),
            )
            return {"op": "service_response", "service": service, "ok": ok}

    if op == "call_service" and service == "/printer/set_active":
        args = payload.get("args")
        if isinstance(args, dict):
            ok = ros_adapter.set_printer_active(
                str(args.get("printer_name", "center")), args.get("active") is True
            )
            return {"op": "service_response", "service": service, "ok": ok}

    if op == "call_service" and service == "/ln_driver/command_srv":
        args = payload.get("args")
        if isinstance(args, dict):
            ok = ros_adapter.call_ln150(int(args.get("command_type", 1)))
            return {"op": "service_response", "service": service, "ok": ok}

    robot_state.add_log(f"unsupported payload {payload}")
    return {"op": "error", "ok": False, "message": "unsupported payload"}


def _nested_number(data: dict[str, object], group: str, key: str) -> float:
    value = data.get(group)
    if isinstance(value, dict):
        raw = value.get(key, 0)
        if isinstance(raw, int | float):
            return float(raw)
    return 0.0
