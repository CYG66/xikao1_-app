from __future__ import annotations

import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .ros_adapter import ros_adapter
from .schemas import ApiResult, Ln150Command, MissionCommand, PrinterCommand, VelocityCommand
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


@app.post("/api/cmd_vel", response_model=ApiResult)
def cmd_vel(command: VelocityCommand) -> ApiResult:
    ros_adapter.publish_velocity(command.linear, command.angular)
    return ApiResult(ok=True, message="velocity command sent")


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
    ros_adapter.control_mission(command.running)
    return ApiResult(ok=True, message="mission state updated")


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

    if op == "publish" and topic == "/cmd_vel":
        message = payload.get("msg")
        if isinstance(message, dict):
            linear = _nested_number(message, "linear", "x")
            angular = _nested_number(message, "angular", "z")
            ros_adapter.publish_velocity(linear, angular)
            return {"op": "published", "topic": topic, "ok": True}

    if op == "publish" and topic == "/xline/mission_control":
        message = payload.get("msg")
        data = message.get("data") if isinstance(message, dict) else ""
        running = data == "start_line_task"
        ros_adapter.control_mission(running)
        return {"op": "published", "topic": topic, "ok": True}

    if op == "call_service" and service == "/printer/quick_command":
        args = payload.get("args")
        if isinstance(args, dict):
            ok = ros_adapter.call_printer(
                str(args.get("printer_name", "center")),
                str(args.get("action", "beep")),
                int(args.get("param", 0)),
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
