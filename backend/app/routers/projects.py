from __future__ import annotations

import json

from fastapi import APIRouter

from ..agent_service import robot_agent
from ..agent_skills import check_drawing_feasibility, layer_drawing_paths
from ..creative_projects import get_creative_project_store
from ..cad_candidate_state import accepted_project_view, candidate_is_accepted
from ..cad_edit_session import binding_key, pending_binding, selection_binding
from ..conversation_memory import conversation_memory
from ..creative_workflow import (
    build_project_acceptance_report,
    ensure_project_plan_ready,
    exit_project_plan,
    mark_project_execution_pending,
    prepare_project_plan,
    prepare_project_recovery,
    project_recovery_assessment,
    refresh_project_execution,
    refresh_project_plan,
    resume_project_execution,
    stop_project_before_deletion,
)
from ..database import xline_database
from ..drawing_store import cad_directory as _cad_directory
from ..drawing_store import resolve_drawing
from ..drawing_versions import drawing_versions
from ..ros_adapter import ros_adapter
from ..schemas import (
    CreativeProjectCreateRequest,
    CreativeProjectInstanceGroupsRequest,
    CreativeProjectIterationRequest,
    CreativeProjectSaveDrawingRequest,
    CreativeProjectUpdateRequest,
    CreativeProjectVariantSelectRequest,
    RecoveryInspectionRequest,
)


router = APIRouter()


def _guard_project_endpoint_binding(
    *,
    project_id: str,
    variant_id: str,
    conversation_id: str | None,
    drawing_selection: object | None,
) -> dict[str, object] | None:
    """Reject a project action when it conflicts with a pending CAD command."""
    # Owned projects must never fall back to an unbound direct API call.  The
    # old guard returned early when conversation_id was omitted, which allowed
    # select/start/save to bypass the same project-version-selection context
    # enforced by the chat route.  Preserve compatibility only for genuinely
    # legacy, unowned projects that have no conversation context to validate.
    project = get_creative_project_store().get(project_id)
    owner = str((project or {}).get("owner_conversation_id") or "").strip()
    if not conversation_id:
        if owner:
            return {
                "ok": False,
                "error_code": "cad_context_binding_required",
                "message": "该项目属于已有会话，必须同时提供会话、版本和选区后才能继续。",
                "binding_trace": {
                    "project_id": project_id,
                    "variant_id": variant_id,
                    "conversation_bound": False,
                },
            }
        return None
    if owner and owner != conversation_id:
        conversation_memory.clear_pending_cad_edit(
            conversation_id, reason="project_owner_binding_mismatch"
        )
        return {
            "ok": False,
            "error_code": "cad_context_binding_mismatch",
            "message": "当前会话不是该项目的所属会话，无法继续操作。",
            "binding_trace": {
                "project_id": project_id,
                "variant_id": variant_id,
                "conversation_bound": True,
                "owner_match": False,
            },
        }
    memory = conversation_memory.context(conversation_id, [])
    pending = memory.get("pending_cad_edit") if isinstance(memory, dict) else None
    if not isinstance(pending, dict):
        return None
    selection = (
        drawing_selection.model_dump(exclude_none=True)
        if hasattr(drawing_selection, "model_dump")
        else drawing_selection if isinstance(drawing_selection, dict) else None
    )
    command = pending.get("command")
    expected_key = binding_key(pending_binding(pending))
    selection_key = binding_key(selection_binding(selection))
    command_key = (
        binding_key(command.get("binding")) if isinstance(command, dict) else None
    )
    matches = (
        expected_key is not None
        and selection_key == expected_key
        and command_key == expected_key
        and str(pending.get("project_id") or "") == project_id
        and str(pending.get("variant_id") or "") == variant_id
        and isinstance(command, dict)
        and bool(command.get("operation"))
        and str(command.get("project_id") or "") == project_id
        and str(command.get("variant_id") or "") == variant_id
        and isinstance(selection, dict)
        and str(selection.get("project_id") or "") == project_id
        and str(selection.get("variant_id") or "") == variant_id
    )
    if matches:
        return None
    conversation_memory.clear_pending_cad_edit(
        conversation_id, reason="project_endpoint_binding_mismatch"
    )
    return {
        "ok": False,
        "error_code": "cad_context_binding_mismatch",
        "message": "项目、版本、选区与待确认命令不一致，待确认命令已清除，请重新选择图形。",
        "binding_trace": {
            "project_id": project_id,
            "variant_id": variant_id,
            "selection_bound": selection_key is not None,
            "pending_command_bound": command_key is not None,
        },
    }


@router.get("/api/agent/projects")
def creative_project_list(limit: int = 50, status: str | None = None, summary: bool = False,
                          conversation_id: str | None = None, include_unowned: bool = False) -> dict[str, object]:
    if summary:
        projects=get_creative_project_store().list(limit, status, summary=True,
            conversation_id=conversation_id, include_unowned=include_unowned)
        return {"ok": True, "projects": [accepted_project_view(p) for p in projects]}
    robot_agent.reconcile_creative_projects()
    projects=get_creative_project_store().list(limit, status,
        conversation_id=conversation_id, include_unowned=include_unowned)
    return {"ok": True, "projects": [accepted_project_view(p) for p in projects]}


@router.post("/api/agent/projects")
def create_creative_project(command: CreativeProjectCreateRequest) -> dict[str, object]:
    source_drawing = command.source_drawing
    if command.source_file_name:
        target = resolve_drawing(command.source_file_name)
        if target is None:
            return {"ok": False, "message": "原图不存在，或不是 cad 目录中的 JSON 图纸。"}
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"ok": False, "message": "原图无法读取。"}
        if not isinstance(payload, dict) or not isinstance(payload.get("lines"), list):
            return {"ok": False, "message": "原图不包含可用的 CAD 图元。"}
        source_drawing = {
            "file_name": command.source_file_name,
            "geometries": payload["lines"],
            "source_format": payload.get("source_format", "xline_json"),
            "cad_analysis": payload.get("cad_analysis", {}),
            "logical_objects": payload.get("logical_objects", []),
            "topology": payload.get("topology", {}),
        }
    project = get_creative_project_store().create(
        command.name, command.original_prompt, command.requirements,
        command.constraints, command.missing_parameters, source_drawing,
        owner_conversation_id=command.owner_conversation_id,
    )
    return {"ok": True, "project": project}


@router.get("/api/agent/projects/{project_id}")
def creative_project_detail(project_id: str) -> dict[str, object]:
    robot_agent.reconcile_creative_projects(project_id)
    project_store = get_creative_project_store()
    project = project_store.get(project_id)
    return {
        "ok": project is not None,
        "project": accepted_project_view(project),
        "timeline": xline_database.project_timeline(project_id) if project else None,
    }


@router.get("/api/agent/projects/{project_id}/timeline")
def creative_project_timeline(project_id: str) -> dict[str, object]:
    project = get_creative_project_store().get(project_id)
    if project is None:
        return {"ok": False, "message": "创意项目不存在"}
    return {
        "ok": True,
        "project_id": project_id,
        "timeline": xline_database.project_timeline(project_id),
    }


@router.post("/api/agent/projects/{project_id}/generate-candidate")
def generate_creative_project_candidate(project_id: str) -> dict[str, object]:
    result=robot_agent.generate_project_candidate(project_id)
    if isinstance(result,dict) and isinstance(result.get('project'),dict):
        result={**result,'project':accepted_project_view(result['project'])}
    return result


@router.patch("/api/agent/projects/{project_id}")
def update_creative_project(project_id: str, command: CreativeProjectUpdateRequest) -> dict[str, object]:
    project = get_creative_project_store().update(project_id, **command.model_dump(exclude_none=True))
    return {"ok": project is not None, "project": project}


@router.delete("/api/agent/projects/{project_id}")
def delete_creative_project(project_id: str) -> dict[str, object]:
    project = get_creative_project_store().get(project_id)
    if project is None:
        return {"ok": False, "message": "项目不存在"}
    stopped = stop_project_before_deletion(project_id)
    if stopped.get("ok") is not True:
        return stopped
    deleted = get_creative_project_store().delete(project_id)
    return {"ok": deleted, "message": "项目已删除" if deleted else "项目不存在"}


@router.post("/api/agent/projects/{project_id}/variants/{variant_id}/save-drawing")
def save_candidate_drawing(
    project_id: str,
    variant_id: str,
    command: CreativeProjectSaveDrawingRequest,
) -> dict[str, object]:
    import hashlib
    from ..drawing_versions import DuplicateDrawingOperationError

    guard = _guard_project_endpoint_binding(
        project_id=project_id,
        variant_id=variant_id,
        conversation_id=command.conversation_id,
        drawing_selection=command.drawing_selection,
    )
    if guard is not None:
        return guard
    project_store = get_creative_project_store()
    project = project_store.get(project_id)
    variant = next((item for item in (project or {}).get("variants", []) if item.get("id") == variant_id), None)
    if variant is None:
        return {"ok": False, "message": "候选方案不存在"}
    if not candidate_is_accepted(variant):
        return {"ok": False, "message": "候选尚未通过统一几何验收，不能导出图纸。"}
    geometries = variant.get("geometries") or []
    feasibility = check_drawing_feasibility(geometries)
    if not feasibility.get("ok"):
        return {"ok": False, "message": "候选未通过保存检查", "feasibility": feasibility}
    digest = hashlib.sha256(json.dumps(geometries, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    operation_id = f"save-candidate:{project_id}:{variant_id}:{digest}"
    previous = drawing_versions.find_by_operation_id(operation_id)
    if previous:
        project_store.record_saved_drawing(project_id, variant_id, previous)
        return {"ok": True, "version": previous, "file_name": previous["file_name"], "reused": True}
    payload = {"schema_version": "1.0", "unit": "mm", **layer_drawing_paths(geometries, "center"),
               "creative_project_id": project_id, "source_variant_id": variant_id,
               "logical_objects": variant.get("logical_objects", []), "topology": variant.get("topology", {})}
    name = command.name.strip() or str(variant.get("name") or "候选图纸")
    try:
        version = drawing_versions.save_project_candidate(
            _cad_directory(), name, payload, "candidate_save", "保存候选方案",
            {"operation_id": operation_id, "source_variant_id": variant_id},
            project_store=project_store, project_id=project_id, variant_id=variant_id,
        )
    except DuplicateDrawingOperationError as exc:
        version = exc.item
        project_store.record_saved_drawing(project_id, variant_id, version)
    return {"ok": True, "version": version, "file_name": version["file_name"]}


@router.post("/api/agent/projects/{project_id}/select-variant")
def select_creative_project_variant(
    project_id: str, command: CreativeProjectVariantSelectRequest
) -> dict[str, object]:
    guard = _guard_project_endpoint_binding(
        project_id=project_id,
        variant_id=command.variant_id,
        conversation_id=command.conversation_id,
        drawing_selection=command.drawing_selection,
    )
    if guard is not None:
        return guard
    project = get_creative_project_store().select_variant(project_id, command.variant_id)
    return {"ok": project is not None, "project": project}


@router.post("/api/agent/projects/{project_id}/start-iteration")
def start_creative_project_iteration(
    project_id: str, command: CreativeProjectIterationRequest
) -> dict[str, object]:
    guard = _guard_project_endpoint_binding(
        project_id=project_id,
        variant_id=command.parent_variant_id,
        conversation_id=command.conversation_id,
        drawing_selection=command.drawing_selection,
    )
    if guard is not None:
        return guard
    project = get_creative_project_store().begin_design_iteration(
        project_id, command.parent_variant_id
    )
    return {
        "ok": project is not None,
        "project": project,
        "message": "已开始新一轮方案优化。" if project else "该方案当前不能继续优化。",
    }


@router.post("/api/agent/projects/{project_id}/confirm-instance-groups")
def confirm_creative_project_instance_groups(
    project_id: str, command: CreativeProjectInstanceGroupsRequest
) -> dict[str, object]:
    project = get_creative_project_store().confirm_source_instance_groups(
        project_id, [dict(group) for group in command.groups]
    )
    if project is None:
        return {
            "ok": False,
            "message": "实例分组无效：每个几何 ID 必须存在、只能出现一次，并覆盖整张导入图纸。",
        }
    return {
        "ok": True,
        "project": project,
        "message": "图纸实例分组已确认，现在可以按分组数量检查候选方案。",
    }


@router.post("/api/agent/projects/{project_id}/plan")
def plan_creative_project(project_id: str) -> dict[str, object]:
    return prepare_project_plan(project_id)


@router.get("/api/agent/projects/{project_id}/plan")
def creative_project_plan_status(project_id: str) -> dict[str, object]:
    return refresh_project_plan(project_id)


@router.post("/api/agent/projects/{project_id}/exit-plan")
def exit_creative_project_plan(project_id: str) -> dict[str, object]:
    return exit_project_plan(project_id)


@router.post("/api/agent/projects/{project_id}/request-execution")
def request_creative_project_execution(project_id: str) -> dict[str, object]:
    refreshed = ensure_project_plan_ready(project_id)
    planning = refreshed.get("planning")
    if not isinstance(planning, dict) or planning.get("ready_for_confirmation") is not True:
        if refreshed.get("code") == "project_plan_rechecking":
            return {**refreshed, "pending_action": None}
        return {
            **refreshed,
            "ok": False,
            "message": str(
                refreshed.get("message")
                or "项目规划尚未通过检查，不能请求执行"
            ),
            "pending_action": None,
        }
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


@router.get("/api/agent/projects/{project_id}/execution")
def creative_project_execution_status(project_id: str) -> dict[str, object]:
    return refresh_project_execution(project_id)


@router.get("/api/agent/projects/{project_id}/recovery")
def creative_project_recovery(project_id: str) -> dict[str, object]:
    return project_recovery_assessment(project_id)


@router.post("/api/agent/projects/{project_id}/recovery")
def create_creative_project_recovery(project_id: str) -> dict[str, object]:
    return prepare_project_recovery(project_id)


@router.post("/api/agent/projects/{project_id}/resume-execution")
def resume_creative_project_execution(project_id: str) -> dict[str, object]:
    return resume_project_execution(project_id)


@router.post("/api/agent/projects/{project_id}/recovery-inspection")
def confirm_creative_project_recovery_inspection(
    project_id: str, command: RecoveryInspectionRequest
) -> dict[str, object]:
    if command.confirmed is not True:
        return {"ok": False, "message": "必须明确确认已完成现场检查"}
    project = get_creative_project_store().confirm_recovery_inspection(project_id)
    return {
        "ok": project is not None,
        "message": "现场检查已记录，可以请求恢复执行。" if project else "当前项目不需要或不能确认恢复检查",
        "project": project,
    }


@router.post("/api/agent/projects/{project_id}/report")
def generate_creative_project_report(project_id: str) -> dict[str, object]:
    return build_project_acceptance_report(project_id)


@router.get("/api/agent/projects/{project_id}/report")
def creative_project_report(project_id: str) -> dict[str, object]:
    project = get_creative_project_store().get(project_id)
    report = project.get("acceptance_report") if project else None
    return {"ok": isinstance(report, dict), "report": report}


