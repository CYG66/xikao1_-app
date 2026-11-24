from __future__ import annotations

from fastapi import APIRouter
import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from ..ros_adapter import ros_adapter
from ..security import principal_expired
from ..state import robot_state
from ..telemetry_contract import build_status_packet
from ..rosbridge_protocol import handle_rosbridge_payload

router = APIRouter()


@router.websocket("/ws/status")
async def websocket_status(websocket: WebSocket) -> None:
    await websocket.accept()
    robot_state.add_log("websocket client connected")
    try:
        while True:
            await websocket.send_json(build_status_packet(robot_state.snapshot()))
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        robot_state.add_log("websocket client disconnected")



@router.websocket("/")
@router.websocket("/ws/rosbridge")
async def websocket_rosbridge(websocket: WebSocket) -> None:
    await websocket.accept()
    robot_state.add_log("rosbridge-compatible client connected")
    principal = getattr(getattr(websocket, "state", None), "auth", None)
    # When authentication is enforced, the control lease belongs to the
    # authenticated token subject.  A client-supplied client_id is never
    # allowed to replace it.
    connection_client_id = principal.subject if principal is not None else ""

    async def close_if_session_expired() -> bool:
        """Expire an established WebSocket at its token lifetime.

        A handshake-only check is insufficient: a long-lived socket could keep
        renewing the lease after the signed token expired.  The check runs on
        every inbound control message and on the idle heartbeat path.  Lease
        release performs the adapter's fail-safe stop when this subject owns it.
        """
        if principal is None or not principal_expired(principal):
            return False
        if connection_client_id:
            ros_adapter.release_control(connection_client_id, "authentication token expired")
        robot_state.add_log("rosbridge authentication token expired; connection closed")
        try:
            await websocket.close(code=1008, reason="token expired")
        except RuntimeError:
            pass
        return True

    if await close_if_session_expired():
        return
    await websocket.send_json({
        "op": "status",
        "msg": build_status_packet(robot_state.snapshot()),
    })
    try:
        while True:
            try:
                payload = await asyncio.wait_for(websocket.receive_json(), timeout=1)
                if await close_if_session_expired():
                    return
                if principal is None and isinstance(payload.get("client_id"), str):
                    connection_client_id = str(payload["client_id"])
                result = handle_rosbridge_payload(
                    payload,
                    principal_subject=connection_client_id or None,
                    principal=principal,
                )
                is_drive_command = (
                    payload.get("op") == "publish"
                    and payload.get("topic") == "/tablet_cmd_vel"
                )
                # A joystick command is a 20-40 Hz real-time stream. Sending
                # a full status snapshot for every packet creates a queue of
                # stale responses and makes the next command arrive late.
                # Successful drive packets need no acknowledgement; errors
                # still go back immediately so the UI can report them.
                if not is_drive_command or result.get("ok") is not True:
                    await websocket.send_json(result)
                if not is_drive_command:
                    await websocket.send_json({
                        "op": "status",
                        "msg": build_status_packet(robot_state.snapshot()),
                    })
            except asyncio.TimeoutError:
                if await close_if_session_expired():
                    return
                await websocket.send_json({
                    "op": "status",
                    "msg": build_status_packet(robot_state.snapshot()),
                })
    except WebSocketDisconnect:
        robot_state.add_log("rosbridge-compatible client disconnected")
    finally:
        if connection_client_id:
            ros_adapter.release_control(connection_client_id, "control client disconnected")
        else:
            # A connection that never identified itself cannot own the control
            # lease. Motion safety is still enforced, but this path must run
            # only once; release_control performs the fail-safe for an owner.
            ros_adapter.fail_safe_stop("unidentified control websocket disconnected")

