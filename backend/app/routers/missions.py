from __future__ import annotations

from fastapi import APIRouter
import json
import re
from ..agent_service import robot_agent
from ..creative_projects import get_creative_project_store
from ..drawing_store import cad_directory as _cad_directory
from ..drawing_store import drawing_execution_ready, resolve_drawing
from ..ros_adapter import ros_adapter
from ..schemas import AgentDrawingPlanRequest, ApiResult, MissionCommand
from ..state import robot_state
from ..tooling import authorize_tool
from ..mission_ledger import mission_ledger

router = APIRouter()


@router.get("/api/missions/ledger")
def mission_ledger_list(limit: int = 50) -> dict[str, object]:
    return {"ok": True, "missions": mission_ledger.list(limit)}



@router.get("/api/missions/ledger/{mission_id}")
def mission_ledger_detail(mission_id: str) -> dict[str, object]:
    mission = mission_ledger.get(mission_id)
    return {"ok": mission is not None, "mission": mission}



@router.get("/api/missions/reports")
def mission_reports(limit: int = 50) -> dict[str, object]:
    return {"ok": True, "reports": mission_ledger.reports(limit)}



@router.get("/api/missions/reports/{mission_id}")
def mission_report_detail(mission_id: str) -> dict[str, object]:
    mission = mission_ledger.get(mission_id)
    report = mission.get("report") if mission else None
    return {"ok": isinstance(report, dict), "report": report}



@router.post("/api/agent/plan-preview")
def agent_plan_preview(command: AgentDrawingPlanRequest) -> dict[str, object]:
    if resolve_drawing(command.file_name) is None:
        return {"ok": False, "message": "图纸不存在，无法规划。"}
    ready, reason = drawing_execution_ready(command.file_name)
    if not ready:
        return {"ok": False, "message": reason}
    ok = ros_adapter.prepare_mission(command.file_name)
    return {
        "ok": ok,
        "message": "已提交路径规划，等待真实规划结果。" if ok else robot_state.mission_error,
        "file_name": command.file_name,
        "mission_stage": robot_state.mission_stage,
        "plan_generation": robot_state.mission_plan_generation,
    }



@router.post("/api/agent/projects/{project_id}/variants/{variant_id}/plan-preview")
def agent_variant_plan_preview(project_id: str, variant_id: str) -> dict[str, object]:
    """Plan the currently displayed AI candidate without using the home map.

    This endpoint is preview-only: it prepares the planner input and never
    creates an execution confirmation. The generated file is deterministic
    for the project/variant pair, so repeated opening of the route viewer
    refreshes the same candidate instead of inheriting an older mission.
    """
    project = get_creative_project_store().get(project_id)
    if project is None:
        return {"ok": False, "message": "当前 AI 项目不存在，请刷新候选方案。"}
    variants = project.get("variants")
    variant = next(
        (
            item for item in variants or []
            if isinstance(item, dict) and str(item.get("id") or "") == variant_id
        ),
        None,
    )
    if variant is None:
        return {"ok": False, "message": "当前 AI 候选方案不存在，请重新打开图纸预览。"}
    geometries = variant.get("geometries")
    if not isinstance(geometries, list) or not geometries:
        return {"ok": False, "message": "当前候选方案没有可规划的图形。"}
    safe_project = re.sub(r"[^A-Za-z0-9_-]", "", project_id)[:24] or "project"
    safe_variant = re.sub(r"[^A-Za-z0-9_-]", "", variant_id)[:24] or "variant"
    file_name = f"agent_preview_{safe_project}_{safe_variant}.json"
    target = _cad_directory() / file_name
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "unit": "mm",
        "lines": geometries,
        "editor_path_metadata": [],
        "source": "ai_variant_preview",
        "project_id": project_id,
        "variant_id": variant_id,
    }
    try:
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError as error:
        return {"ok": False, "message": f"当前候选方案无法准备路径预览：{error}"}
    ready, reason = drawing_execution_ready(file_name)
    if not ready:
        return {"ok": False, "message": reason, "file_name": file_name}
    ok = ros_adapter.prepare_mission(file_name)
    return {
        "ok": ok,
        "message": "已根据当前 AI 候选方案生成路径预览。"
        if ok else robot_state.mission_error,
        "file_name": file_name,
        "project_id": project_id,
        "variant_id": variant_id,
        "mission_stage": robot_state.mission_stage,
        "plan_generation": robot_state.mission_plan_generation,
    }



@router.post("/api/agent/request-execution")
def agent_request_execution(command: AgentDrawingPlanRequest) -> dict[str, object]:
    ready, reason = drawing_execution_ready(command.file_name)
    if not ready:
        return {"ok": False, "message": reason, "pending_action": None}
    if (
        robot_state.mission_stage != "ready"
        or robot_state.mission_file != command.file_name
        or robot_state.mission_prepared_file != command.file_name
        or robot_state.mission_prepared_generation
        != robot_state.mission_plan_generation
    ):
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



@router.post("/api/mission/control", response_model=ApiResult)
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

