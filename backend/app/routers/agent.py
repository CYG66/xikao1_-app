from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from .. import agent_http_service
from ..schemas import AgentChatRequest
from fastapi import File, UploadFile
from ..database import xline_database
from ..agent_evaluation import run_policy_evaluation
from ..agent_service import robot_agent
from ..agent_attachments import MAX_IMAGE_BYTES, agent_attachments
from ..conversation_memory import conversation_memory
from ..creative_projects import get_creative_project_store
from ..schemas import AgentRequirementDecisionRequest, AgentConfigCommand
from ..tooling import tool_catalog
from ..task_store import agent_tasks, utc_now
from ..drawing_versions import drawing_versions
from ..request_context import agent_user_scope

router = APIRouter()


@router.get("/api/agent/tools")
def agent_tools() -> dict[str, object]:
    return {"ok": True, "schema_version": "1.0", "tools": tool_catalog()}


@router.get("/api/agent/evaluation")
def agent_policy_evaluation() -> dict[str, object]:
    """Run the real-user acceptance corpus without API or hardware calls."""
    return run_policy_evaluation(
        robot_agent.route_intent,
        robot_agent._selected_deepseek_tools,
        robot_agent.resolve_intent,
    )


@router.get("/api/agent/knowledge/search")
def agent_knowledge_search(q: str, limit: int = 4) -> dict[str, object]:
    """Search trusted local project files without calling an external model."""
    query = q.strip()
    if not query:
        return {"ok": False, "message": "检索问题不能为空。", "matches": []}
    result = robot_agent.knowledge_context(
        query, {"tool_family": "conversation"}
    )
    result["matches"] = result.get("matches", [])[:max(1, min(limit, 8))]
    return {"ok": True, **result}


@router.get("/api/agent/status")
def agent_status() -> dict[str, object]:
    return robot_agent.config()


@router.get("/api/agent/tasks")
def agent_task_list(limit: int = 50) -> dict[str, object]:
    robot_agent.reconcile_verification_tasks()
    return {"ok": True, "tasks": agent_tasks.list(limit)}


@router.delete("/api/agent/memory/{conversation_id}")
def delete_agent_conversation_memory(conversation_id: str) -> dict[str, object]:
    removed = conversation_memory.delete(conversation_id)
    return {
        "ok": True,
        "removed": removed,
        "message": "会话对象记忆已删除。" if removed else "该会话没有服务器对象记忆。",
    }


@router.get("/api/agent/lifecycle/recycle")
def project_recycle() -> dict[str, object]:
    from ..conversation_archive import archived_chats
    return {"ok": True, "projects": get_creative_project_store().lifecycle_items(deleted=True), "conversations": archived_chats()}


@router.post("/api/agent/lifecycle/conversations")
def conversation_lifecycle(command: dict[str, object]) -> dict[str, object]:
    from ..conversation_archive import archived_chats
    from copy import deepcopy
    ids = list(command.get("conversation_ids") or [])
    action = str(command.get("action") or "preflight")
    if not ids or action not in {"preflight", "trash", "restore", "purge"}:
        return {"ok": False, "message": "无效的对话操作"}
    with get_creative_project_store()._lock:
        projects = [item for item in get_creative_project_store().lifecycle_items(deleted=action in {"restore", "purge"})
                    if item.get("owner_conversation_id") in ids
                    and (action not in {"restore", "purge"} or item.get("deleted_with_conversation") in ids)]
        keys = [item["id"] for item in projects]
        result = get_creative_project_store().lifecycle("preflight", keys)
        saved = [item for item in drawing_versions.list() if item.get("project_id") in keys]
        result.update(project_count=len(keys), saved_drawing_count=len(saved), project_ids=keys)
        if action == "trash" and command.get("expected_project_ids") is not None and set(command["expected_project_ids"]) != set(keys):
            return {"ok": False, "message": "对话下的项目已变化，请重新确认删除范围"}
        if not result["ok"] or action == "preflight":
            return result
        archives = archived_chats()
        snapshots = command.get("snapshots") or {}
        if action == "trash" and (not isinstance(snapshots, dict) or any(not isinstance(snapshots.get(key), dict) for key in ids)):
            return {"ok": False, "message": "缺少对话快照，无法安全移入回收站"}
        if action in {"restore", "purge"} and any(key not in archives for key in ids):
            return {"ok": False, "message": "回收站对话不存在，请刷新"}
        before = deepcopy(get_creative_project_store()._projects)
        try:
            result = get_creative_project_store().lifecycle(action, keys, "__batch__", persist=False)
            if not result["ok"]:
                return result
            detached = []
            if action == "purge":
                # Independently trashed projects remain recoverable as unowned.
                for item in get_creative_project_store()._projects.values():
                    changed = False
                    if item.get("owner_conversation_id") in ids:
                        item["owner_conversation_id"] = None
                        changed = True
                    references = item.get("referenced_conversation_ids") or []
                    if any(key in ids for key in references):
                        item["referenced_conversation_ids"] = [key for key in references if key not in ids]
                        changed = True
                    if changed:
                        item["updated_at"] = utc_now()
                        detached.append(item)
            xline_database.save_project_lifecycle(
                [get_creative_project_store()._projects[key] for key in keys if key in get_creative_project_store()._projects] + detached,
                {key: snapshots[key] for key in ids} if action == "trash" else {},
                remove_archives=ids if action != "trash" else [],
                remove_projects=keys if action == "purge" else [],
            )
            if not get_creative_project_store()._database_enabled:
                get_creative_project_store()._save()
        except Exception:
            get_creative_project_store()._projects = before
            raise
        if action != "trash":
            result["snapshots"] = {key: archives[key] for key in ids}
        if action == "purge":
            for key in ids:
                conversation_memory.delete(key)
        return result


@router.post("/api/agent/lifecycle/projects/{project_id}")
def project_lifecycle(project_id: str, command: dict[str, str]) -> dict[str, object]:
    action = command.get("action", "preflight")
    if action not in {"copy", "preflight", "trash", "restore", "purge", "claim", "reference"}:
        return {"ok": False, "message": "不支持的项目操作"}
    if action == "copy":
        source = get_creative_project_store().get(project_id)
        owner = command.get("conversation_id")
        if not source or not owner:
            return {"ok": False, "message": "请指定项目和目标对话"}
        copied = get_creative_project_store().create(source["name"] + " · 副本", source["original_prompt"],
            source["requirements"], source.get("constraints"), source.get("missing_parameters"),
            source.get("source_drawing"), owner_conversation_id=owner)
        # Clone design data only; execution/planning bindings must never transfer.
        try:
            for variant in source.get("variants") or []:
                added = get_creative_project_store().add_variant(copied["id"], variant["name"], variant["geometries"],
                    variant.get("rationale", ""), variant.get("assessment", {}), variant.get("preview_paths", []))
                if added is None:
                    raise ValueError("候选复制失败")
        except Exception:
            get_creative_project_store().delete(copied["id"])
            raise
        return {"ok": True, "project": get_creative_project_store().get(copied["id"])}
    return get_creative_project_store().lifecycle(action, [project_id], command.get("conversation_id"))


@router.get("/api/agent/memory/{conversation_id}")
def get_agent_conversation_memory(conversation_id: str) -> dict[str, object]:
    memory = conversation_memory.context(conversation_id)
    return {"ok": memory.get("enabled") is True, "memory": memory}


@router.post("/api/agent/memory/{conversation_id}/requirements")
def decide_agent_requirements(
    conversation_id: str, command: AgentRequirementDecisionRequest
) -> dict[str, object]:
    return conversation_memory.decide_requirements(conversation_id, command.accepted)


@router.get("/api/agent/tasks/{task_id}")
def agent_task_detail(task_id: str) -> dict[str, object]:
    robot_agent.reconcile_verification_tasks()
    task = agent_tasks.get(task_id)
    return {"ok": task is not None, "task": task}


@router.get("/api/agent/fault-evaluation")
def agent_fault_evaluation() -> dict[str, object]:
    """Read-only live fault evaluation; never sends a hardware command."""
    return robot_agent.live_fault_evaluation()


@router.get("/api/agent/audit")
def agent_audit_list(
    limit: int = 100,
    event: str | None = None,
    tool: str | None = None,
    ok: bool | None = None,
) -> dict[str, object]:
    return {"ok": True, "events": xline_database.list_audit(limit, event, tool, ok)}


@router.get("/api/agent/cases")
def agent_case_list(project_id: str | None = None, limit: int = 50, include_inactive: bool = False) -> dict[str, object]:
    return {"ok": True, "cases": xline_database.list_ai_cases(project_id, limit, include_inactive)}


@router.post("/api/agent/cases/{case_id}/status")
def agent_case_status(case_id: str, status: str) -> dict[str, object]:
    """Disable or delete a remembered AI case without removing audit history."""
    changed = xline_database.set_ai_case_status(case_id, status)
    return {"ok": changed, "case_id": case_id, "status": status if changed else None}


@router.post("/api/agent/cases/{case_id}/promote")
def agent_case_promote(case_id: str) -> dict[str, object]:
    try:
        template = xline_database.promote_ai_case(case_id)
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": template is not None, "template": template}


@router.post("/api/agent/templates/{template_id}/validate")
def agent_template_validate(template_id: str, parameters: dict[str, object]) -> dict[str, object]:
    return xline_database.validate_ai_template(template_id, parameters)


@router.post("/api/agent/templates/{template_id}/accept")
def agent_template_accept(template_id: str, payload: dict[str, object]) -> dict[str, object]:
    return xline_database.accept_ai_template(
        template_id,
        dict(payload.get("parameters") or {}),
        dict(payload.get("acceptance") or {}),
    )


@router.get("/api/agent/config")
def agent_config(client_id: str | None = None) -> dict[str, object]:
    with agent_user_scope(client_id):
        return robot_agent.config()


@router.post("/api/agent/config")
def update_agent_config(command: AgentConfigCommand) -> dict[str, object]:
    with agent_user_scope(command.client_id):
        return robot_agent.update_config(
            command.mode,
            command.model,
            command.api_key,
            command.clear_api_key,
            cad_planning_model=command.cad_planning_model,
        )


@router.post("/api/agent/test")
def test_agent_config(client_id: str | None = None) -> dict[str, object]:
    with agent_user_scope(client_id):
        return robot_agent.test_connection()


@router.post("/api/agent/attachments/image")
async def upload_agent_image(file: UploadFile = File(...)) -> dict[str, object]:
    payload = await file.read(MAX_IMAGE_BYTES + 1)
    try:
        metadata = agent_attachments.save_image(
            file.filename or "image",
            file.content_type or "application/octet-stream",
            payload,
        )
    except ValueError as error:
        return {"ok": False, "message": str(error)}
    return {
        "ok": True,
        "message": "图片已作为参考附件上传。当前模型不会自动读取图片中的尺寸，请在消息中补充关键要求。",
        "attachment": metadata,
    }


@router.post('/api/agent/chat')
def agent_chat(command: AgentChatRequest) -> dict[str, object]:
    return agent_http_service.agent_chat(command=command)


@router.get('/api/agent/runs')
def agent_run_list(conversation_id: str | None = None, limit: int = 50) -> dict[str, object]:
    return agent_http_service.agent_run_list(conversation_id=conversation_id, limit=limit)


@router.get('/api/agent/runs/{run_id}')
def agent_run_detail(run_id: str) -> dict[str, object]:
    return agent_http_service.agent_run_detail(run_id=run_id)


@router.post('/api/agent/runs/{run_id}/cancel')
def cancel_agent_run(run_id: str, client_id: str | None = None) -> dict[str, object]:
    return agent_http_service.cancel_agent_run(run_id=run_id, client_id=client_id)


@router.post('/api/agent/runs/{run_id}/resume')
def resume_agent_run(run_id: str, client_id: str | None = None) -> dict[str, object]:
    return agent_http_service.resume_agent_run(run_id=run_id, client_id=client_id)


@router.post('/api/agent/chat/stream')
def agent_chat_stream(command: AgentChatRequest) -> StreamingResponse:
    return agent_http_service.agent_chat_stream(command=command)


from ..agent_service import robot_agent
from ..schemas import AgentConfirmRequest

@router.post("/api/agent/confirm")
def agent_confirm(command: AgentConfirmRequest) -> dict[str, object]:
    from ..agent_response_builder import normalize_acceptance_response
    return normalize_acceptance_response(robot_agent.confirm(command.action_id, command.approved, command.client_id))

