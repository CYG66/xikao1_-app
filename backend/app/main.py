from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from math import cos, pi, sin
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .database import xline_database
from .agent_skills import check_drawing_feasibility, layer_drawing_paths, score_design_variant
from .agent_service import robot_agent
from .creative_projects import creative_projects
from .creative_workflow import (
    build_project_acceptance_report,
    creative_project_sync,
    mark_project_execution_pending,
    prepare_project_plan,
    prepare_project_recovery,
    project_recovery_assessment,
    refresh_project_execution,
    refresh_project_plan,
)
from .drawing_store import cad_directory as _cad_directory
from .drawing_store import preview_paths, resolve_drawing
from .ros_adapter import ros_adapter
from .schemas import (
    AgentChatRequest,
    AgentConfirmRequest,
    AgentDrawingPlanRequest,
    AgentConfigCommand,
    ApiResult,
    CreativeProjectCreateRequest,
    CreativeProjectUpdateRequest,
    CreativeProjectVariantRequest,
    CreativeProjectVariantSelectRequest,
    RecoveryInspectionRequest,
    DrawingGenerateRequest,
    DrawingJsonImportRequest,
    DrawingSaveRequest,
    DrawingVersionRollbackRequest,
    EmergencyStopCommand,
    Ln150Command,
    MissionCommand,
    PrinterActiveCommand,
    PrinterCommand,
    VelocityCommand,
)
from .state import robot_state
from .tooling import (
    authorize_emergency_stop,
    authorize_tool,
    tool_catalog,
    validate_tool_arguments,
)
from .task_store import agent_tasks
from .mission_ledger import mission_ledger
from .drawing_versions import drawing_versions

app = FastAPI(title="XLine Rover Backend", version="0.1.0")

BUILT_IN_DRAWINGS = {
    "test_pattern.json",
    "huanong_skeleton.json",
    "square_image.json",
}

BUILT_IN_PREVIEWS = {
    "test_pattern.json": [
        [[0.0, 0.0], [4.0, 0.0]],
        [[0.0, 0.6], [4.0, 0.6]],
        [[0.0, 1.2], [4.0, 1.2]],
    ],
    "huanong_skeleton.json": [
        [[0.0, 0.0], [1.5, 2.2], [3.0, 0.0]],
        [[0.75, 1.1], [2.25, 1.1]],
    ],
    "square_image.json": [
        [[0.0, 0.0], [3.0, 0.0], [3.0, 3.0], [0.0, 3.0], [0.0, 0.0]],
    ],
}


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
    creative_project_sync.start()


@app.on_event("shutdown")
def shutdown() -> None:
    creative_project_sync.stop()
    ros_adapter.stop()


@app.get("/health")
def health() -> dict[str, object]:
    return {"ok": True, "status": robot_state.snapshot()}


@app.get("/api/status")
def status() -> dict[str, object]:
    snapshot = robot_state.snapshot()
    xline_database.record_telemetry(snapshot)
    xline_database.upsert_device_capabilities(snapshot, ros_adapter.interface_snapshot())
    return snapshot


@app.get("/api/database/summary")
def database_summary() -> dict[str, object]:
    """Return persistence health; this never participates in safety decisions."""
    return xline_database.summary()


@app.get("/api/database/migrations")
def database_migrations() -> dict[str, object]:
    return {"ok": True, **xline_database.migration_status()}


@app.post("/api/database/backup")
def database_backup() -> dict[str, object]:
    """Create a timestamped backup beside the configured database."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destination = xline_database.path.with_name(
        f"{xline_database.path.stem}.{stamp}.backup.sqlite"
    )
    return xline_database.backup(destination)


@app.get("/api/agent/tools")
def agent_tools() -> dict[str, object]:
    return {"ok": True, "schema_version": "1.0", "tools": tool_catalog()}


@app.get("/api/logs")
def logs() -> dict[str, list[str]]:
    return {"logs": robot_state.logs}


@app.get("/api/agent/status")
def agent_status() -> dict[str, object]:
    return robot_agent.config()


@app.get("/api/agent/tasks")
def agent_task_list(limit: int = 50) -> dict[str, object]:
    return {"ok": True, "tasks": agent_tasks.list(limit)}


@app.get("/api/agent/tasks/{task_id}")
def agent_task_detail(task_id: str) -> dict[str, object]:
    task = agent_tasks.get(task_id)
    return {"ok": task is not None, "task": task}


@app.get("/api/agent/audit")
def agent_audit_list(
    limit: int = 100,
    event: str | None = None,
    tool: str | None = None,
    ok: bool | None = None,
) -> dict[str, object]:
    return {"ok": True, "events": xline_database.list_audit(limit, event, tool, ok)}


@app.get("/api/agent/cases")
def agent_case_list(project_id: str | None = None, limit: int = 50) -> dict[str, object]:
    return {"ok": True, "cases": xline_database.list_ai_cases(project_id, limit)}


@app.get("/api/agent/device-capabilities")
def device_capability_list(device_id: str | None = None) -> dict[str, object]:
    """Return the persisted device/ROS2 capability registry.

    Refreshing from the live adapter first keeps this endpoint useful after a
    ROS2 restart, while motion and safety endpoints still use live state.
    """
    snapshot = robot_state.snapshot()
    xline_database.upsert_device_capabilities(snapshot, ros_adapter.interface_snapshot())
    return {"ok": True, "devices": xline_database.list_device_capabilities(device_id)}


@app.get("/api/agent/device-capabilities/{device_id}")
def device_capability_detail(device_id: str) -> dict[str, object]:
    snapshot = robot_state.snapshot()
    xline_database.upsert_device_capabilities(snapshot, ros_adapter.interface_snapshot())
    devices = xline_database.list_device_capabilities(device_id)
    return {"ok": bool(devices), "device": devices[0] if devices else None}


@app.get("/api/missions/ledger")
def mission_ledger_list(limit: int = 50) -> dict[str, object]:
    return {"ok": True, "missions": mission_ledger.list(limit)}


@app.get("/api/missions/ledger/{mission_id}")
def mission_ledger_detail(mission_id: str) -> dict[str, object]:
    mission = mission_ledger.get(mission_id)
    return {"ok": mission is not None, "mission": mission}


@app.get("/api/missions/reports")
def mission_reports(limit: int = 50) -> dict[str, object]:
    return {"ok": True, "reports": mission_ledger.reports(limit)}


@app.get("/api/missions/reports/{mission_id}")
def mission_report_detail(mission_id: str) -> dict[str, object]:
    mission = mission_ledger.get(mission_id)
    report = mission.get("report") if mission else None
    return {"ok": isinstance(report, dict), "report": report}


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


@app.get("/api/agent/projects")
def creative_project_list(limit: int = 50, status: str | None = None) -> dict[str, object]:
    return {"ok": True, "projects": creative_projects.list(limit, status)}


@app.post("/api/agent/projects")
def create_creative_project(command: CreativeProjectCreateRequest) -> dict[str, object]:
    project = creative_projects.create(
        command.name, command.original_prompt, command.requirements,
        command.constraints, command.missing_parameters,
    )
    return {"ok": True, "project": project}


@app.get("/api/agent/projects/{project_id}")
def creative_project_detail(project_id: str) -> dict[str, object]:
    project = creative_projects.get(project_id)
    return {
        "ok": project is not None,
        "project": project,
        "timeline": xline_database.project_timeline(project_id) if project else None,
    }


@app.get("/api/agent/projects/{project_id}/timeline")
def creative_project_timeline(project_id: str) -> dict[str, object]:
    project = creative_projects.get(project_id)
    if project is None:
        return {"ok": False, "message": "创意项目不存在"}
    return {
        "ok": True,
        "project_id": project_id,
        "timeline": xline_database.project_timeline(project_id),
    }


@app.patch("/api/agent/projects/{project_id}")
def update_creative_project(project_id: str, command: CreativeProjectUpdateRequest) -> dict[str, object]:
    project = creative_projects.update(project_id, **command.model_dump(exclude_none=True))
    return {"ok": project is not None, "project": project}


@app.delete("/api/agent/projects/{project_id}")
def delete_creative_project(project_id: str) -> dict[str, object]:
    deleted = creative_projects.delete(project_id)
    return {"ok": deleted, "message": "项目已删除" if deleted else "项目不存在"}


@app.post("/api/agent/projects/{project_id}/variants")
def add_creative_project_variant(
    project_id: str, command: CreativeProjectVariantRequest
) -> dict[str, object]:
    arguments, error = validate_tool_arguments(
        "add_design_variant",
        {"project_id": project_id, **command.model_dump()},
    )
    if arguments is None:
        return {"ok": False, "message": error, "variant": None}
    geometries = list(arguments["geometries"])
    assessment = score_design_variant(geometries)
    paths = preview_paths({"lines": geometries})
    variant = creative_projects.add_variant(
        project_id, str(arguments["name"]), geometries,
        str(arguments["rationale"]), assessment, paths
    )
    return {"ok": variant is not None, "variant": variant}


@app.post("/api/agent/projects/{project_id}/select-variant")
def select_creative_project_variant(
    project_id: str, command: CreativeProjectVariantSelectRequest
) -> dict[str, object]:
    project = creative_projects.select_variant(project_id, command.variant_id)
    return {"ok": project is not None, "project": project}


@app.post("/api/agent/projects/{project_id}/plan")
def plan_creative_project(project_id: str) -> dict[str, object]:
    return prepare_project_plan(project_id)


@app.get("/api/agent/projects/{project_id}/plan")
def creative_project_plan_status(project_id: str) -> dict[str, object]:
    return refresh_project_plan(project_id)


@app.post("/api/agent/projects/{project_id}/request-execution")
def request_creative_project_execution(project_id: str) -> dict[str, object]:
    refreshed = refresh_project_plan(project_id)
    planning = refreshed.get("planning") if refreshed.get("ok") else None
    if not isinstance(planning, dict) or planning.get("ready_for_confirmation") is not True:
        return {"ok": False, "message": "项目规划尚未通过检查，不能请求执行", "pending_action": None}
    recovery = planning.get("recovery")
    if (
        isinstance(recovery, dict)
        and recovery.get("manual_inspection_required") is True
        and recovery.get("manual_inspection_confirmed") is not True
    ):
        return {
            "ok": False,
            "message": "恢复任务包含疑似部分喷墨段，请先现场检查并确认，避免重复喷墨。",
            "pending_action": None,
        }
    runtime_errors = ros_adapter.prepared_mission_validation_errors()
    if runtime_errors:
        return {
            "ok": False,
            "message": "实车执行条件未通过：" + "；".join(runtime_errors),
            "pending_action": None,
        }
    result = robot_agent.request_confirmation(
        "execute_prepared_mission", {"file_name": str(planning["file_name"])}
    )
    pending = result.get("pending_action")
    if isinstance(pending, dict) and isinstance(pending.get("id"), str):
        mark_project_execution_pending(project_id, str(pending["id"]))
    return result


@app.get("/api/agent/projects/{project_id}/execution")
def creative_project_execution_status(project_id: str) -> dict[str, object]:
    return refresh_project_execution(project_id)


@app.get("/api/agent/projects/{project_id}/recovery")
def creative_project_recovery(project_id: str) -> dict[str, object]:
    return project_recovery_assessment(project_id)


@app.post("/api/agent/projects/{project_id}/recovery")
def create_creative_project_recovery(project_id: str) -> dict[str, object]:
    return prepare_project_recovery(project_id)


@app.post("/api/agent/projects/{project_id}/recovery-inspection")
def confirm_creative_project_recovery_inspection(
    project_id: str, command: RecoveryInspectionRequest
) -> dict[str, object]:
    if command.confirmed is not True:
        return {"ok": False, "message": "必须明确确认已完成现场检查"}
    project = creative_projects.confirm_recovery_inspection(project_id)
    return {
        "ok": project is not None,
        "message": "现场检查已记录，可以请求恢复执行。" if project else "当前项目不需要或不能确认恢复检查",
        "project": project,
    }


@app.post("/api/agent/projects/{project_id}/report")
def generate_creative_project_report(project_id: str) -> dict[str, object]:
    return build_project_acceptance_report(project_id)


@app.get("/api/agent/projects/{project_id}/report")
def creative_project_report(project_id: str) -> dict[str, object]:
    project = creative_projects.get(project_id)
    report = project.get("acceptance_report") if project else None
    return {"ok": isinstance(report, dict), "report": report}


@app.get("/api/drawings")
def list_drawings() -> dict[str, object]:
    directory = _cad_directory()
    directory.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "files": sorted(path.name for path in directory.glob("*.json"))}


@app.get("/api/drawings/versions")
def list_drawing_versions() -> dict[str, object]:
    return {"ok": True, "versions": drawing_versions.list()}


@app.get("/api/drawings/versions/{drawing_id}")
def drawing_version_history(drawing_id: str) -> dict[str, object]:
    return {"ok": True, "versions": drawing_versions.list(drawing_id)}


@app.post("/api/drawings/versions/{file_name}/rollback")
def rollback_drawing_version(
    file_name: str, command: DrawingVersionRollbackRequest
) -> dict[str, object]:
    source = drawing_versions.find_by_file(file_name)
    if source is None:
        return {"ok": False, "message": "历史图纸版本不存在"}
    if command.project_id and source.get("project_id") not in {None, command.project_id}:
        return {"ok": False, "message": "图纸版本不属于当前项目"}
    version = drawing_versions.restore(
        file_name,
        _cad_directory(),
        command.project_id,
    )
    if version is None:
        return {"ok": False, "message": "图纸版本回退失败"}
    return {
        "ok": True,
        "message": f"已从 {file_name} 创建新的回退版本 {version['file_name']}",
        "source_version": source,
        "version": version,
    }


@app.get("/api/drawings/{file_name}")
def drawing_preview(file_name: str) -> dict[str, object]:
    """Return CAD geometry in the same metre-based format used by the map."""
    if Path(file_name).name != file_name or Path(file_name).suffix.lower() != ".json":
        return {"ok": False, "message": "Invalid drawing file name."}

    target = resolve_drawing(file_name)
    if target is not None:
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"ok": False, "message": "Drawing file cannot be read."}
        if not isinstance(payload, dict):
            return {"ok": False, "message": "Drawing data must be a JSON object."}
        paths = preview_paths(payload)
    else:
        paths = BUILT_IN_PREVIEWS.get(file_name, [])
        if not paths:
            return {"ok": False, "message": "Drawing file does not exist."}

    planned_paths = [
        {
            "namespace": "path_lines",
            "color": {"r": 0.1, "g": 0.8, "b": 1.0, "a": 1.0},
            "points": points,
        }
        for points in paths if len(points) >= 2
    ]
    return {"ok": True, "file_name": file_name, "planned_paths": planned_paths}


@app.delete("/api/drawings/{file_name}")
def delete_drawing(file_name: str) -> dict[str, object]:
    if Path(file_name).name != file_name or Path(file_name).suffix.lower() != ".json":
        return {"ok": False, "message": "图纸文件名无效。"}
    if file_name in BUILT_IN_DRAWINGS:
        return {"ok": False, "message": "内置任务不能删除。"}
    if robot_state.mission_running and robot_state.mission_file == file_name:
        return {"ok": False, "message": "任务正在执行，不能删除当前图纸。"}
    target = _cad_directory() / file_name
    if not target.is_file():
        return {"ok": False, "message": "图纸不存在或已经删除。"}
    target.unlink()
    robot_state.add_log(f"drawing deleted {file_name}")
    return {"ok": True, "message": "图纸已删除。", "file_name": file_name}


@app.post("/api/drawings/save")
def save_drawing(command: DrawingSaveRequest) -> dict[str, object]:
    directory = _cad_directory()
    directory.mkdir(parents=True, exist_ok=True)
    safe_stem = re.sub(r"[^\w\-\u4e00-\u9fff]", "_", command.name).strip("_")
    if not safe_stem:
        safe_stem = f"app_drawing_{datetime.now():%Y%m%d_%H%M%S}"
    file_name = f"{safe_stem}.json"
    lines = []
    for index, segment in enumerate(command.segments, start=1):
        if abs(segment.start_x - segment.end_x) + abs(segment.start_y - segment.end_y) < 0.001:
            continue
        lines.append(
            {
                "id": index,
                "type": "line",
                "layer_id": 1,
                "start": {"x": round(segment.start_x * 1000, 3), "y": round(segment.start_y * 1000, 3), "z": 0.0},
                "end": {"x": round(segment.end_x * 1000, 3), "y": round(segment.end_y * 1000, 3), "z": 0.0},
            }
        )
    if not lines:
        return {"ok": False, "message": "图纸中没有有效线段。"}
    feasibility = check_drawing_feasibility(lines)
    if feasibility["ok"] is not True:
        return {
            "ok": False,
            "message": "保存前检查未通过：" + "；".join(feasibility["errors"]),
            "feasibility": feasibility,
        }
    payload = {
        "schema_version": "1.0",
        "unit": "mm",
        **layer_drawing_paths(lines, "center"),
    }
    version = drawing_versions.save(directory, file_name, payload, "app", "画图工具保存")
    file_name = str(version["file_name"])
    robot_state.add_log(f"drawing saved {file_name} ({len(lines)} segments)")
    return {
        "ok": True,
        "file_name": file_name,
        "segments": len(lines),
        "feasibility": feasibility,
        "path_layers": payload["layers"],
        "version": version,
    }


@app.post("/api/drawings/import-json")
def import_drawing_json(command: DrawingJsonImportRequest) -> dict[str, object]:
    paths = preview_paths(command.payload)
    if not paths:
        return {
            "ok": False,
            "message": "JSON does not contain geometry supported by the path planner.",
        }

    directory = _cad_directory()
    directory.mkdir(parents=True, exist_ok=True)
    version = drawing_versions.save(directory, f"{command.name}.json", command.payload, "import", "JSON 导入")
    file_name = str(version["file_name"])
    robot_state.add_log(f"drawing JSON imported {file_name} ({len(paths)} paths)")
    return {"ok": True, "file_name": file_name, "paths": len(paths), "version": version}


@app.post("/api/drawings/generate")
def generate_drawing(command: DrawingGenerateRequest) -> dict[str, object]:
    prompt = command.prompt.lower().replace("×", "x").replace("米", "")
    numbers = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", prompt)]
    shapes: list[dict[str, object]] = []
    if any(word in prompt for word in ("矩形", "长方形", "rectangle")):
        width, height = (numbers + [5.0, 3.0])[:2]
        shapes.append({"type": "rectangle", "x": -width / 2, "y": -height / 2, "width": width, "height": height})
    elif any(word in prompt for word in ("圆", "circle")):
        value = numbers[0] if numbers else 2.0
        radius = value / 2 if "直径" in prompt else value
        points = [[round(radius * cos(index * 2 * pi / 48), 4), round(radius * sin(index * 2 * pi / 48), 4)] for index in range(49)]
        shapes.append({"type": "polyline", "closed": True, "points": points})
    elif any(word in prompt for word in ("平行线", "排线")):
        count = max(1, min(30, int(numbers[0] if numbers else 6)))
        length = numbers[1] if len(numbers) > 1 else 5.0
        spacing = numbers[2] if len(numbers) > 2 else 0.5
        for index in range(count):
            y = (index - (count - 1) / 2) * spacing
            shapes.append({"type": "line", "points": [[-length / 2, y], [length / 2, y]]})
    else:
        return {
            "ok": False,
            "message": "暂时支持矩形、圆和平行线，例如：画一个 5x3 米矩形。",
            "shapes": [],
        }
    return {"ok": True, "message": "草图已生成，请检查尺寸后保存。", "shapes": shapes}


@app.post("/api/agent/chat")
def agent_chat(command: AgentChatRequest) -> dict[str, object]:
    try:
        return robot_agent.chat(
            command.message,
            [message.model_dump() for message in command.history],
            mode=command.mode,
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


@app.post("/api/agent/chat/stream")
def agent_chat_stream(command: AgentChatRequest) -> StreamingResponse:
    def events():
        try:
            for event in robot_agent.chat_stream(
                command.message,
                [message.model_dump() for message in command.history[-4:]],
                mode=command.mode,
            ):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except RuntimeError as error:
            result = {
                "ok": False,
                "configured": robot_agent.configured,
                "message": str(error),
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "pending_action": None,
            }
            yield json.dumps({"type": "result", **result}, ensure_ascii=False) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.post("/api/agent/confirm")
def agent_confirm(command: AgentConfirmRequest) -> dict[str, object]:
    return robot_agent.confirm(command.action_id, command.approved, command.client_id)


@app.post("/api/agent/plan-preview")
def agent_plan_preview(command: AgentDrawingPlanRequest) -> dict[str, object]:
    if resolve_drawing(command.file_name) is None:
        return {"ok": False, "message": "图纸不存在，无法规划。"}
    ok = ros_adapter.prepare_mission(command.file_name)
    return {
        "ok": ok,
        "message": "已提交路径规划，等待真实规划结果。" if ok else robot_state.mission_error,
        "file_name": command.file_name,
        "mission_stage": robot_state.mission_stage,
    }


@app.post("/api/agent/request-execution")
def agent_request_execution(command: AgentDrawingPlanRequest) -> dict[str, object]:
    if robot_state.mission_stage != "ready" or robot_state.mission_file != command.file_name:
        return {
            "ok": False,
            "message": "该图纸尚未完成规划预览，不能请求执行。",
            "pending_action": None,
        }
    if robot_state.mission_validation.get("ok") is not True:
        errors = robot_state.mission_validation.get("errors", [])
        return {
            "ok": False,
            "message": "规划前检查未通过：" + "；".join(str(item) for item in errors),
            "pending_action": None,
            "mission_summary": robot_state.mission_summary,
            "mission_validation": robot_state.mission_validation,
        }
    runtime_errors = ros_adapter.prepared_mission_validation_errors()
    if runtime_errors:
        return {
            "ok": False,
            "message": "实车执行条件未通过：" + "；".join(runtime_errors),
            "pending_action": None,
            "mission_summary": robot_state.mission_summary,
            "mission_validation": {
                **robot_state.mission_validation,
                "ok": False,
                "runtime_errors": runtime_errors,
            },
        }
    return robot_agent.request_confirmation(
        "execute_prepared_mission", {"file_name": command.file_name}
    )


@app.post("/api/cmd_vel", response_model=ApiResult)
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


@app.post("/api/emergency-stop", response_model=ApiResult)
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


@app.post("/api/printer/quick_command", response_model=ApiResult)
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


@app.post("/api/ln150/command", response_model=ApiResult)
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


@app.post("/api/mission/control", response_model=ApiResult)
def mission(command: MissionCommand) -> ApiResult:
    action = command.action
    if command.running is not None:
        action = "start" if command.running else "cancel"
    decision = authorize_tool(
        "set_mission",
        {"running": action in {"start", "resume"}, "file_name": command.file_name},
        confirmed=True,
        client_id=command.client_id,
    )
    if action not in {"start", "resume"}:
        decision = authorize_tool(
            "set_mission",
            {"running": False, "file_name": command.file_name},
            confirmed=True,
            client_id=command.client_id,
        )
    if not decision.allowed:
        return ApiResult(ok=False, message=decision.message)
    ok = ros_adapter.control_mission_action(action, command.file_name)
    return ApiResult(ok=ok, message="mission request accepted" if ok else robot_state.mission_error or "mission request rejected")


@app.post("/api/printer/set_active", response_model=ApiResult)
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
    connection_client_id = ""
    try:
        while True:
            try:
                payload = await asyncio.wait_for(websocket.receive_json(), timeout=1)
                if isinstance(payload.get("client_id"), str):
                    connection_client_id = str(payload["client_id"])
                result = handle_rosbridge_payload(payload)
                await websocket.send_json(result)
                await websocket.send_json({"op": "status", "msg": robot_state.snapshot()})
            except asyncio.TimeoutError:
                await websocket.send_json({"op": "status", "msg": robot_state.snapshot()})
    except WebSocketDisconnect:
        ros_adapter.fail_safe_stop("control websocket disconnected")
        robot_state.add_log("rosbridge-compatible client disconnected")
    finally:
        if connection_client_id:
            ros_adapter.release_control(connection_client_id, "control client disconnected")


def handle_rosbridge_payload(payload: dict[str, object]) -> dict[str, object]:
    op = payload.get("op")
    topic = payload.get("topic")
    service = payload.get("service")
    client_id = str(payload.get("client_id", ""))

    if op == "claim_control":
        ok = ros_adapter.claim_control(client_id)
        return {
            "op": "control_response",
            "ok": ok,
            "owner": robot_state.control_owner,
            "message": "control lease granted" if ok else "control lease is held by another client",
        }

    if op == "control_heartbeat":
        ok = ros_adapter.touch_control(client_id)
        if not ok:
            ros_adapter.fail_safe_stop("control lease lost")
        return {"op": "control_heartbeat_response", "ok": ok}

    if op == "release_control":
        ros_adapter.release_control(client_id)
        return {"op": "control_response", "ok": True, "owner": None}

    if op == "stop_agent_motion":
        ok = ros_adapter.stop_agent_motion()
        return {"op": "agent_motion_response", "ok": ok, "active": False}

    if op == "subscribe":
        robot_state.add_log(f"subscribe {topic}")
        return {"op": "subscribed", "topic": topic, "ok": True}

    if op == "publish" and topic == "/tablet_cmd_vel":
        if not ros_adapter.owns_control(client_id):
            return {"op": "published", "topic": topic, "ok": False, "message": "control lease required"}
        message = payload.get("msg")
        if isinstance(message, dict):
            linear = _nested_number(message, "linear", "x")
            angular = _nested_number(message, "angular", "z")
            arguments, error = validate_tool_arguments(
                "drive_robot",
                {"linear": linear, "angular": angular, "duration_seconds": 0.1},
            )
            if arguments is None:
                return {"op": "published", "topic": topic, "ok": False, "message": error}
            decision = authorize_tool(
                "drive_robot", arguments, confirmed=True, client_id=client_id
            )
            if not decision.allowed and (linear != 0.0 or angular != 0.0):
                return {"op": "published", "topic": topic, "ok": False, "message": decision.message}
            if robot_state.agent_motion_active:
                ros_adapter.stop_agent_motion("manual App control takeover")
            ok = ros_adapter.publish_velocity(linear, angular)
            return {
                "op": "published",
                "topic": topic,
                "ok": ok,
                "message": "velocity command sent" if ok else "CAN interface or motor driver is not ready",
            }

    if op == "emergency_stop":
        active = payload.get("active") is not False
        decision = authorize_emergency_stop(active, client_id)
        if not decision.allowed:
            return {
                "op": "emergency_stop_response",
                "ok": False,
                "active": True,
                "message": decision.message,
            }
        ok = ros_adapter.set_emergency_stop(active)
        return {
            "op": "emergency_stop_response",
            "ok": ok,
            "active": active if ok else True,
            "message": "emergency stop updated" if ok else "hardware runtime or emergency reset service is not ready",
        }

    if op == "mission_control":
        if not ros_adapter.owns_control(client_id):
            return {"op": "mission_response", "ok": False, "message": "control lease required"}
        action = str(payload.get("action", ""))
        if not action:
            action = "start" if payload.get("running") is True else "cancel"
        file_name = str(payload.get("file_name", "test_pattern.json"))
        running = action in {"start", "resume"}
        arguments, error = validate_tool_arguments(
            "set_mission", {"running": running, "file_name": file_name}
        )
        if arguments is None:
            return {"op": "mission_response", "ok": False, "message": error}
        decision = authorize_tool(
            "set_mission", arguments, confirmed=True, client_id=client_id
        )
        if not decision.allowed:
            return {"op": "mission_response", "ok": False, "message": decision.message}
        if robot_state.bridge_mode == "virtual_ros2":
            if action == "start":
                robot_state.mission_running = True
                robot_state.mission_paused = False
                robot_state.mission_completed = 0
                robot_state.pose_trace = [[float(robot_state.robot_pose.get("x", 0)), float(robot_state.robot_pose.get("y", 0))]]
            elif action == "pause":
                robot_state.mission_running = True
                robot_state.mission_paused = True
            elif action == "resume":
                robot_state.mission_running = True
                robot_state.mission_paused = False
            else:
                robot_state.mission_running = False
                robot_state.mission_paused = False
            robot_state.mission_file = file_name
            robot_state.mission_stage = {"start": "executing", "pause": "paused", "resume": "executing", "cancel": "cancelled"}.get(action, "cancelled")
            robot_state.mission_current_id = 1 if robot_state.mission_running else None
            robot_state.mission_total = 8
            robot_state.mission_error = ""
            ros_adapter.publish_velocity(0.0, 0.0) if action in {"pause", "cancel"} else None
            robot_state.add_log(f"virtual mission {action}")
            return {"op": "mission_response", "ok": True, "message": "virtual mission updated"}
        ok = ros_adapter.control_mission_action(action, file_name)
        return {"op": "mission_response", "ok": ok, "message": robot_state.mission_error}

    if op == "call_service" and service == "/printer/quick_command":
        args = payload.get("args")
        if isinstance(args, dict):
            if robot_state.bridge_mode == "virtual_ros2":
                robot_state.add_log(f"virtual printer {args.get('action', 'beep')}")
                return {"op": "service_response", "service": service, "ok": True}
            tool_args, error = validate_tool_arguments(
                "control_printer",
                {
                    "printer_name": args.get("printer_name", "center"),
                    "action": args.get("action", "beep"),
                    "param": args.get("param", 0),
                },
            )
            if tool_args is None:
                return {"op": "service_response", "service": service, "ok": False, "message": error}
            decision = authorize_tool("control_printer", tool_args, confirmed=True, client_id=client_id)
            if not decision.allowed:
                return {"op": "service_response", "service": service, "ok": False, "message": decision.message}
            ok = ros_adapter.call_printer(
                str(tool_args["printer_name"]),
                str(tool_args["action"]),
                int(tool_args["param"]),
            )
            return {"op": "service_response", "service": service, "ok": ok}

    if op == "call_service" and service == "/printer/set_active":
        args = payload.get("args")
        if isinstance(args, dict):
            if robot_state.bridge_mode == "virtual_ros2":
                target = str(args.get("printer_name", "center"))
                status = robot_state.printer_status.get(f"printer_{target}")
                if isinstance(status, dict):
                    status["enabled"] = args.get("active") is True
                return {"op": "service_response", "service": service, "ok": True}
            printer_name = str(args.get("printer_name", "center"))
            decision = authorize_tool(
                "control_printer",
                {"printer_name": printer_name, "action": "beep", "param": 0},
                confirmed=True,
                client_id=client_id,
            )
            if not decision.allowed:
                return {"op": "service_response", "service": service, "ok": False, "message": decision.message}
            ok = ros_adapter.set_printer_active(printer_name, args.get("active") is True)
            return {"op": "service_response", "service": service, "ok": ok}

    if op == "call_service" and service == "/printer/set_enabled":
        args = payload.get("args")
        if isinstance(args, dict):
            printer_name = str(args.get("printer_name", "center"))
            if f"printer_{printer_name}" not in robot_state.printer_status:
                return {"op": "service_response", "service": service, "ok": False, "message": "喷码机未配置"}
            if not ros_adapter.owns_control(client_id):
                return {"op": "service_response", "service": service, "ok": False, "message": "control lease required"}
            enabled = args.get("enabled") is True
            if robot_state.bridge_mode == "virtual_ros2":
                robot_state.printer_status[f"printer_{printer_name}"]["auto_connect"] = enabled
                return {"op": "service_response", "service": service, "ok": True}
            ok = ros_adapter.set_printer_enabled(printer_name, enabled)
            return {"op": "service_response", "service": service, "ok": ok}

    if op == "call_service" and service == "/printer/send_command":
        args = payload.get("args")
        if isinstance(args, dict):
            printer_name = str(args.get("printer_name", "center"))
            json_data = str(args.get("json_data", ""))
            if f"printer_{printer_name}" not in robot_state.printer_status:
                return {"op": "service_response", "service": service, "ok": False, "message": "喷码机未配置"}
            if len(json_data.encode("utf-8")) > 8192:
                return {"op": "service_response", "service": service, "ok": False, "message": "JSON 命令过大"}
            if not ros_adapter.owns_control(client_id):
                return {"op": "service_response", "service": service, "ok": False, "message": "control lease required"}
            try:
                json.loads(json_data)
            except json.JSONDecodeError:
                return {"op": "service_response", "service": service, "ok": False, "message": "JSON 格式无效"}
            if robot_state.bridge_mode == "virtual_ros2":
                robot_state.add_log(f"virtual printer raw command {printer_name}")
                return {"op": "service_response", "service": service, "ok": True}
            ok = ros_adapter.send_printer_command(printer_name, json_data)
            return {"op": "service_response", "service": service, "ok": ok}

    if op == "call_service" and service == "/ln_driver/command_srv":
        args = payload.get("args")
        if isinstance(args, dict):
            if robot_state.bridge_mode == "virtual_ros2":
                robot_state.ln150_status = "tracking"
                robot_state.add_log(f"virtual LN150 command {args.get('command_type', 1)}")
                return {"op": "service_response", "service": service, "ok": True}
            tool_args, error = validate_tool_arguments(
                "control_ln150", {"command_type": args.get("command_type", 1)}
            )
            if tool_args is None:
                return {"op": "service_response", "service": service, "ok": False, "message": error}
            decision = authorize_tool("control_ln150", tool_args, confirmed=True, client_id=client_id)
            if not decision.allowed:
                return {"op": "service_response", "service": service, "ok": False, "message": decision.message}
            ok = ros_adapter.call_ln150(int(tool_args["command_type"]))
            return {"op": "service_response", "service": service, "ok": ok}

    if op == "call_service" and service == "/localization/calibrate_pose":
        if not ros_adapter.owns_control(client_id):
            return {"op": "service_response", "service": service, "ok": False, "message": "需要小车控制权"}
        if not robot_state.localization_calibration_available:
            return {"op": "service_response", "service": service, "ok": False, "message": "当前定位模式没有校准或原点重置服务"}
        ok = ros_adapter.calibrate_localization()
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
