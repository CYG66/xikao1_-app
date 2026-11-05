from __future__ import annotations

from fastapi import APIRouter
from ..database import xline_database
from ..agent_service import robot_agent
from ..ros_adapter import ros_adapter
from ..schemas import ApiResult, DeviceDiagnosticRequest, EmergencyStopCommand, Ln150Command, PrinterActiveCommand, PrinterCommand, VelocityCommand
from ..state import robot_state
from ..tooling import authorize_emergency_stop, authorize_tool
from ..diagnostics import build_local_diagnosis, compare_api_with_local

router = APIRouter()


@router.get("/api/agent/device-capabilities")
def device_capability_list(device_id: str | None = None) -> dict[str, object]:
    """Return the persisted device/ROS2 capability registry.

    Refreshing from the live adapter first keeps this endpoint useful after a
    ROS2 restart, while motion and safety endpoints still use live state.
    """
    snapshot = robot_state.snapshot()
    xline_database.upsert_device_capabilities(snapshot, ros_adapter.interface_snapshot())
    return {"ok": True, "devices": xline_database.list_device_capabilities(device_id)}



@router.get("/api/agent/device-capabilities/{device_id}")
def device_capability_detail(device_id: str) -> dict[str, object]:
    snapshot = robot_state.snapshot()
    xline_database.upsert_device_capabilities(snapshot, ros_adapter.interface_snapshot())
    devices = xline_database.list_device_capabilities(device_id)
    return {"ok": bool(devices), "device": devices[0] if devices else None}



@router.post("/api/monitor/diagnose")
def monitor_diagnose(command: DeviceDiagnosticRequest) -> dict[str, object]:
    """API-first diagnosis; local rules enrich only after API assessment."""
    live_snapshot = robot_state.snapshot()
    api_attempted = True
    try:
        api_result = robot_agent.analyze_diagnostic_snapshot({
            "backend_live": live_snapshot,
            "app_observed": command.snapshot,
        })
    except RuntimeError as error:
        api_result = {
            "ok": False,
            "configured": robot_agent.configured,
            "message": str(error),
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "pending_action": None,
        }
    local_result = build_local_diagnosis(live_snapshot)
    comparison = compare_api_with_local(api_result, local_result)
    return {
        "ok": True,
        "api_attempted": api_attempted,
        "api_analysis": api_result,
        "local_diagnosis": local_result,
        "comparison": comparison,
        "diagnosis_source": "api_then_local_verification",
        "automatic_repair": False,
    }



@router.post("/api/cmd_vel", response_model=ApiResult)
def cmd_vel(command: VelocityCommand) -> ApiResult:
    decision = authorize_tool(
        "drive_robot",
        {
            "linear": command.linear,
            "angular": command.angular,
            "duration_seconds": 0.1,
        },
        confirmed=True,
        client_id=command.client_id,
    )
    if not decision.allowed and (command.linear != 0.0 or command.angular != 0.0):
        return ApiResult(ok=False, message=decision.message)
    if robot_state.agent_motion_active:
        ros_adapter.stop_agent_motion("manual REST control takeover")
    ok = ros_adapter.publish_velocity(command.linear, command.angular)
    return ApiResult(
        ok=ok,
        message="velocity command sent" if ok else "CAN interface or motor driver is not ready",
    )



@router.post("/api/emergency-stop", response_model=ApiResult)
def emergency_stop(command: EmergencyStopCommand) -> ApiResult:
    decision = authorize_emergency_stop(command.active, command.client_id)
    if not decision.allowed:
        return ApiResult(ok=False, message=decision.message)
    ok = ros_adapter.set_emergency_stop(command.active)
    if command.active:
        message = "emergency stop active"
    else:
        message = "emergency stop released" if ok else "hardware runtime failed to become ready; emergency stop remains active"
    return ApiResult(ok=ok, message=message)



@router.post("/api/printer/quick_command", response_model=ApiResult)
def printer(command: PrinterCommand) -> ApiResult:
    decision = authorize_tool(
        "control_printer",
        command.model_dump(exclude={"client_id"}),
        confirmed=True,
        client_id=command.client_id,
    )
    if not decision.allowed:
        return ApiResult(ok=False, message=decision.message)
    ok = ros_adapter.call_printer(command.printer_name, command.action, command.param)
    return ApiResult(ok=ok, message="printer command accepted" if ok else "printer service unavailable")



@router.post("/api/ln150/command", response_model=ApiResult)
def ln150(command: Ln150Command) -> ApiResult:
    decision = authorize_tool(
        "control_ln150",
        {"command_type": command.command_type},
        confirmed=True,
        client_id=command.client_id,
    )
    if not decision.allowed:
        return ApiResult(ok=False, message=decision.message)
    ok = ros_adapter.call_ln150(command.command_type)
    return ApiResult(ok=ok, message="ln150 command accepted" if ok else "ln150 service unavailable")



@router.post("/api/printer/set_active", response_model=ApiResult)
def printer_active(command: PrinterActiveCommand) -> ApiResult:
    decision = authorize_tool(
        "control_printer",
        {"printer_name": command.printer_name, "action": "beep", "param": 0},
        confirmed=True,
        client_id=command.client_id,
    )
    if not decision.allowed:
        return ApiResult(ok=False, message=decision.message)
    ok = ros_adapter.set_printer_active(command.printer_name, command.active)
    return ApiResult(ok=ok, message="printer active state submitted" if ok else "printer/set_active unavailable")

