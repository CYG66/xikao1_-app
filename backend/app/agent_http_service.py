from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from .agent_response_builder import normalize_acceptance_response
from fastapi.responses import StreamingResponse
from .agent_service import robot_agent
from .agent_attachments import agent_attachments
from .conversation_memory import conversation_memory
from .cad_revision import verify_cad_revision_state
from .incremental_cad import parse_incremental_edit, resolve_incremental_correction, resolve_incremental_followup
from .creative_projects import get_creative_project_store
from .drawing_store import preview_paths, resolve_drawing
from .schemas import AgentChatRequest, AgentDrawingSelection
from .state import robot_state
from .agent_run_store import agent_runs
from .agent_failure_policy import classify_agent_failure
from .request_context import agent_user_scope
from .structured_usage import structured_usage_scope, usage_scoped_events
from .cad_edit_session import binding_key, pending_binding, selection_binding


def _agent_message_with_attachments(
    command: AgentChatRequest, message: str | None = None
) -> str:
    user_message = message or command.message
    if not command.attachments:
        return user_message
    context: list[str] = []
    for attachment in command.attachments:
        if attachment.kind == "image":
            metadata = (
                agent_attachments.get(attachment.attachment_id)
                if attachment.attachment_id
                else None
            )
            if metadata is None:
                context.append(f"- 图片“{attachment.display_name}”上传记录已失效，不能据此判断内容。")
            else:
                context.append(
                    f"- 参考图片“{metadata['display_name']}”已上传；当前文本模型未解析图片像素，"
                    "回答时必须说明需要用户描述关键尺寸或改用具备视觉能力的模型。"
                )
            continue
        target = resolve_drawing(attachment.file_name or "")
        if target is None:
            context.append(f"- CAD 图纸“{attachment.display_name}”不存在，不能据此修改或规划。")
            continue
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
            paths = preview_paths(payload) if isinstance(payload, dict) else []
        except (OSError, json.JSONDecodeError):
            paths = []
        context.append(
            f"- 已验证 CAD 图纸“{attachment.file_name}”，包含 {len(paths)} 条可预览路径；"
            "如需修改，必须基于该文件的当前版本进行差异化更新。"
        )
    return f"{user_message}\n\n附件上下文（系统验证）：\n" + "\n".join(context)



_REQUIREMENT_GATED_ACTIONS = frozenset({
    "drive_robot",
    "drive_sequence",
    "printer_spray",
    "control_printer",
    "control_ln150",
    "set_mission",
    "execute_prepared_mission",
})



def _enforce_requirement_confirmation(
    result: dict[str, object], route: dict[str, object]
) -> dict[str, object]:
    """Do not let unconfirmed design parameters reach a physical action."""
    retrieved = route.get("retrieved_memory")
    pending = retrieved.get("pending_requirements") if isinstance(retrieved, dict) else None
    if not isinstance(pending, dict) or not pending:
        memory = route.get("object_memory")
        profile = memory.get("requirement_profile") if isinstance(memory, dict) else None
        pending = profile.get("pending") if isinstance(profile, dict) else None
    action = result.get("pending_action")
    # Base-mode shape requests are deterministic, low-speed chassis previews,
    # not CAD designs waiting to become construction projects.  Their physical
    # action still remains pending until the user confirms it, so do not cancel
    # that confirmation merely because conversation memory extracted shape
    # parameters such as radius or side length.
    if (
        route.get("mode") == "base"
        and route.get("name") == "motion_control"
        and route.get("decision_source") in {
            "base_rectangular_motion_request",
            "base_circular_motion_request",
            "base_polygonal_motion_request",
            "base_motion_demo_followup",
        }
        and isinstance(action, dict)
        and action.get("name") in {"drive_robot", "drive_sequence"}
    ):
        return result
    if (
        isinstance(pending, dict)
        and set(pending) == {"linear_speed_mps"}
        and route.get("name") == "motion_control"
        and isinstance(action, dict)
        and action.get("name") in {"drive_robot", "drive_sequence"}
    ):
        arguments = action.get("arguments")
        steps = (
            arguments.get("steps") if action.get("name") == "drive_sequence"
            else [arguments]
        ) if isinstance(arguments, dict) else None
        try:
            expected = float(pending["linear_speed_mps"])
            matching = bool(steps) and all(
                isinstance(step, dict)
                and abs(float(step.get("linear")) - expected) < 1e-6
                for step in steps
            )
        except (TypeError, ValueError):
            matching = False
        if matching:
            return result
    if (
        not isinstance(pending, dict)
        or not pending
        or not isinstance(action, dict)
        or action.get("name") not in _REQUIREMENT_GATED_ACTIONS
    ):
        return result
    action_id = str(action.get("id") or "").strip()
    if action_id:
        robot_agent.confirm(action_id, False)
    result["pending_action"] = None
    result["requirements_confirmation_required"] = True
    result["message"] = (
        "本次设计要求尚未确认。请先检查并确认需求档案，"
        "确认后再发出任务执行或设备控制指令。"
    )
    return result


def _candidate_acceptance_summary(result: dict[str, object]) -> dict[str, object] | None:
    """Return the authoritative acceptance evidence for a candidate response."""
    variant = result.get("variant") if isinstance(result.get("variant"), dict) else {}
    record = variant.get("construction_record") if isinstance(variant, dict) else None
    interpretation = result.get("construction_interpretation")
    from .cad_candidate_state import authoritative_acceptance_summary
    summary=authoritative_acceptance_summary(variant)
    if summary is not None:
        return summary
    candidates=[result.get("acceptance_summary"),
                interpretation.get("acceptance_summary") if isinstance(interpretation, dict) else None]
    return next((item for item in candidates if isinstance(item, dict)), None)


def _bind_and_filter_candidate_visibility(
    run_id: str, result: dict[str, object]
) -> dict[str, object]:
    """Expose candidates only after acceptance and current-run binding pass.

    Persistence remains diagnostic and recoverable.  This boundary controls
    what the App may render, so missing or stale evidence is hidden instead of
    being mistaken for a valid candidate.
    """
    variant = result.get("variant") if isinstance(result.get("variant"), dict) else None
    if (variant is None and result.get('variants')
            and not result.get('preview_paths') and result.get('drawing_json') is None):
        # Project-update tools include historical versions as metadata. With
        # no submitted candidate or drawing artifact these are not outputs of
        # this run. Keep the actual update/clarification response and expose
        # no candidate list.
        result = dict(result)
        result.pop('variants', None)
    if (result.get('target_clarification') and result.get('clarification_required')
            and isinstance(variant, dict) and not variant.get('geometries')):
        # A target question may identify its source version; it is not a new
        # candidate submission. Preserve the question without exposing an
        # unverified candidate or rewriting it as a generation failure.
        result = dict(result)
        result['source_variant_id'] = variant.get('id')
        for key in ('variant', 'variants', 'preview_paths', 'drawing_json'):
            result.pop(key, None)
        return result
    candidate_claimed = (
        variant is not None
        or bool(result.get('variants'))
        or result.get('drawing_json') is not None
    )
    if variant is None and not candidate_claimed:
        return result
    if variant is None:
        # A response without one canonical candidate cannot establish a
        # project/version/run binding even if a nested tool leaked previews.
        variant = {}
    run = agent_runs.get(run_id) or {}
    project = result.get("project") if isinstance(result.get("project"), dict) else {}
    project_id = str(result.get("project_id") or project.get("id") or "").strip()
    variant_id = str(variant.get("id") or "").strip()
    project_variants = project.get("variants") if isinstance(project, dict) else None
    listed = any(
        isinstance(item, dict) and str(item.get("id") or "").strip() == variant_id
        for item in (project_variants if isinstance(project_variants, list) else [])
    )
    run_project = str(run.get("project_id") or "").strip()
    source_variant = str(run.get("source_variant_id") or "").strip()
    parent_variant = str(variant.get("parent_variant_id") or "").strip()
    binding_ok = bool(run and run_project and project_id and variant_id and listed)
    # A candidate must have been committed during this run.  Project membership
    # alone is insufficient because an older candidate can be returned by a
    # stale service snapshot and then receive the current run label.
    run_created = str(run.get("created_at") or "")
    variant_created = str(variant.get("created_at") or "")
    if run_created and variant_created and variant_created < run_created:
        binding_ok = False
    if run_project and run_project != project_id:
        binding_ok = False
    if source_variant and variant_id != source_variant and parent_variant != source_variant:
        binding_ok = False
    summary = _candidate_acceptance_summary(result)
    from .cad_candidate_state import candidate_is_accepted
    accepted = (candidate_is_accepted(variant)
                and isinstance(summary, dict) and summary.get("status") == "passed"
                and summary.get("review_required") is not True)
    if accepted and binding_ok:
        result["candidate_binding"] = {
            "run_id": run_id,
            "project_id": project_id,
            "variant_id": variant_id,
        }
        result["candidate_visibility"] = {"status": "visible", "run_id": run_id}
        return result

    reasons: list[str] = []
    if not accepted:
        reasons.append("acceptance_summary.status_not_passed")
    if not binding_ok:
        reasons.append("candidate_not_bound_to_current_run")
        if run_created and variant_created and variant_created < run_created:
            reasons.append("candidate_created_before_current_run")
    result["candidate_visibility"] = {
        "status": "hidden",
        "run_id": run_id,
        "reason": reasons,
    }
    result["ok"] = False
    result["message"] = "候选尚未通过当前运行的几何验收或版本绑定检查，暂不展示。已保留需求，请重新生成。"
    if "response_text" in result:
        result["response_text"] = result["message"]
    result["next_action"] = "review_acceptance"
    result["preview_paths"] = []
    result["drawing_json"] = None
    result["variants"] = []
    result["variant"] = None
    if isinstance(project, dict):
        hidden_project = dict(project)
        hidden_project["variants"] = []
        result["project"] = hidden_project
    for key in ("tool_result",):
        tool = result.get(key)
        if isinstance(tool, dict) and tool.get("name") == "persist_candidate_variant":
            tool = dict(tool)
            tool.update({"ok": False, "variant_id": None, "preview_paths": [],
                         "variant": None, "variants": [], "drawing_json": None})
            nested_project = tool.get('project')
            if isinstance(nested_project, dict):
                tool['project'] = {**nested_project, 'variants': []}
            tool["message"] = "候选尚未通过当前运行的几何验收，暂不展示。"
            result[key] = tool
    tools = result.get("tool_results")
    if isinstance(tools, list):
        filtered_tools = []
        for tool in tools:
            if isinstance(tool, dict) and tool.get("name") == "persist_candidate_variant":
                tool = dict(tool)
                tool.update({"ok": False, "variant_id": None, "preview_paths": [],
                             "variant": None, "variants": [], "drawing_json": None})
                nested_project = tool.get('project')
                if isinstance(nested_project, dict):
                    tool['project'] = {**nested_project, 'variants': []}
            filtered_tools.append(tool)
        result["tool_results"] = filtered_tools
    return result



def _routing_history(
    history: list[dict[str, str]], memory: dict[str, object]
) -> list[dict[str, str]]:
    """Add durable conversational context when the client window is incomplete."""
    summary = memory.get("summary") if isinstance(memory, dict) else None
    if not isinstance(summary, dict):
        return history
    result = list(history)
    existing = {(item.get("role"), item.get("content")) for item in result}
    remembered: list[dict[str, str]] = []
    for request in summary.get("recent_requests", []):
        if isinstance(request, str) and request.strip():
            remembered.append({"role": "user", "content": request.strip()})
    answer = summary.get("last_answer")
    if isinstance(answer, str) and answer.strip():
        remembered.append({"role": "assistant", "content": answer.strip()})
    state = memory.get("workflow_state") if isinstance(memory, dict) else None
    pending = state.get("pending") if isinstance(state, dict) else None
    question = pending.get("question") if isinstance(pending, dict) else None
    if isinstance(question, str) and question.strip():
        remembered.append({"role": "assistant", "content": question.strip()})
    prefix = [item for item in remembered if (item["role"], item["content"]) not in existing]
    return (prefix + result)[-12:]



def _resolve_cad_followup(message: str, memory: dict[str, object]) -> str:
    previous = memory.get("last_cad_edit") if isinstance(memory, dict) else None
    if not isinstance(previous, dict):
        return message
    project = get_creative_project_store().get(str(previous.get("project_id") or ""))
    variants = project.get("variants") if isinstance(project, dict) else None
    result_variant = next((
        item for item in variants
        if isinstance(item, dict)
        and str(item.get("id") or "") == str(previous.get("variant_id") or "")
    ), None) if isinstance(variants, list) else None
    parent_variant_id = str(
        previous.get("parent_variant_id")
        or (result_variant.get("parent_variant_id") if isinstance(result_variant, dict) else "")
        or ""
    )
    parent_variant = next((
        item for item in variants
        if isinstance(item, dict) and str(item.get("id") or "") == parent_variant_id
    ), None) if isinstance(variants, list) and parent_variant_id else None
    parent_geometries = (
        parent_variant.get("geometries") if isinstance(parent_variant, dict) else None
    )
    parent_instance_ids = sorted({
        value for item in parent_geometries
        if isinstance(item, dict)
        and isinstance((value := item.get("template_instance")), int)
        and value > 0
    }) if isinstance(parent_geometries, list) else None
    correction = resolve_incremental_correction(
        message, previous, parent_instance_ids
    )
    current_base = str(project.get("design_base_variant_id") or "") if isinstance(project, dict) else ""
    if (
        correction is not None
        and isinstance(project, dict)
        and project.get("status") == "designing"
        and parent_variant_id
        and current_base in {parent_variant_id, str(previous.get("variant_id") or "")}
    ):
        if current_base != parent_variant_id:
            if get_creative_project_store().begin_design_iteration(
                str(previous.get("project_id") or ""), parent_variant_id
            ) is None:
                return message
        return correction
    if (
        not isinstance(project, dict)
        or project.get("status") != "designing"
        or str(project.get("design_base_variant_id") or "")
        != str(previous.get("variant_id") or "")
    ):
        return message
    base_variant_id = str(project.get("design_base_variant_id") or "")
    variants = project.get("variants")
    base_variant = next((
        item for item in variants
        if isinstance(item, dict) and str(item.get("id") or "") == base_variant_id
    ), None) if isinstance(variants, list) else None
    geometries = base_variant.get("geometries") if isinstance(base_variant, dict) else None
    available_instance_ids = sorted({
        value for item in geometries
        if isinstance(item, dict)
        and isinstance((value := item.get("template_instance")), int)
        and value > 0
    }) if isinstance(geometries, list) else None
    return resolve_incremental_followup(
        message, previous, available_instance_ids
    ) or message



def _cad_navigation_action(message: str) -> str | None:
    text = re.sub(r"[\s，。！？、,.!?；;：:]+", "", message.lower())
    if any(word in text for word in ("小车", "任务", "喷墨", "喷码", "底盘")):
        return None
    if any(word in text for word in (
        "恢复刚才撤销", "恢复上一步修改", "重做", "重新应用刚才修改",
    )):
        return "redo"
    if any(word in text for word in (
        "撤销刚才的修改", "撤销上一步", "回退上一步", "回到修改前", "撤销这次图纸修改",
    )):
        return "undo"
    return None



def _navigate_cad_candidate(
    message: str,
    memory: dict[str, object],
    conversation_id: str | None,
) -> dict[str, object] | None:
    action = _cad_navigation_action(message)
    if action is None:
        return None
    last_edit = memory.get("last_cad_edit") if isinstance(memory, dict) else None
    navigation = memory.get("candidate_navigation") if isinstance(memory, dict) else None
    project_id = str(
        (navigation.get("project_id") if isinstance(navigation, dict) else "")
        or (last_edit.get("project_id") if isinstance(last_edit, dict) else "")
        or ""
    )
    project = get_creative_project_store().get(project_id) if project_id else None
    if not isinstance(project, dict) or project.get("status") != "designing":
        return {
            "ok": False, "message": "当前没有可撤销或重做的设计候选。",
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "pending_action": None,
        }
    variants = project.get("variants")
    if not isinstance(variants, list):
        return {
            "ok": False, "message": "候选历史数据不完整，无法撤销或重做。",
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "pending_action": None,
        }
    by_id = {
        str(item.get("id")): item for item in variants
        if isinstance(item, dict) and item.get("id")
    }
    current_id = str(project.get("design_base_variant_id") or "")
    current = by_id.get(current_id)
    redo_stack = list(navigation.get("redo_stack") or []) if isinstance(navigation, dict) else []
    if redo_stack and str(navigation.get("current_variant_id") or "") != current_id:
        conversation_memory.set_candidate_navigation(conversation_id, None)
        return {
            "ok": False, "message": "候选分支已变化，旧的撤销与重做记录已清除。",
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "pending_action": None,
        }

    if action == "undo":
        if not isinstance(current, dict):
            return {
                "ok": False, "message": "当前候选不存在，无法执行撤销。",
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "pending_action": None,
            }
        if not redo_stack:
            expected = str(last_edit.get("variant_id") or "") if isinstance(last_edit, dict) else ""
            if not expected or current_id != expected:
                return {
                    "ok": False, "message": "当前候选不是本会话最近修改的结果，未执行撤销。",
                    "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                    "pending_action": None,
                }
        target_id = str(current.get("parent_variant_id") or "")
        target = by_id.get(target_id)
        if not isinstance(target, dict):
            return {
                "ok": False, "message": "已经是此分支最早的候选，无法继续撤销。",
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "pending_action": None,
            }
        redo_stack.append(current_id)
        revision_to_verify = current.get("revision_contract")
        expected_revision_state = "before"
    else:
        if not redo_stack:
            return {
                "ok": False, "message": "当前没有可重做的候选修改。",
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "pending_action": None,
            }
        target_id = str(redo_stack[-1])
        target = by_id.get(target_id)
        if (
            not isinstance(target, dict)
            or str(target.get("parent_variant_id") or "") != current_id
        ):
            conversation_memory.set_candidate_navigation(conversation_id, None)
            return {
                "ok": False, "message": "候选分支已变化，旧的重做记录已清除。",
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "pending_action": None,
            }
        redo_stack.pop()
        revision_to_verify = target.get("revision_contract")
        expected_revision_state = "after"

    updated = get_creative_project_store().begin_design_iteration(project_id, target_id)
    if not isinstance(updated, dict):
        return {
            "ok": False, "message": "候选切换失败，请刷新项目后重试。",
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "pending_action": None,
        }
    rollback_verification = (
        verify_cad_revision_state(
            revision_to_verify,
            list(target.get("geometries") or []),
            expected_revision_state,
        )
        if isinstance(revision_to_verify, dict)
        else {
            "schema": "cad.rollback.verification.v1",
            "status": "unavailable",
            "verified": False,
            "expected": expected_revision_state,
            "reason": "历史候选没有 cad.revision.v1 快照",
        }
    )
    if rollback_verification["status"] == "failed":
        get_creative_project_store().begin_design_iteration(project_id, current_id)
        return {
            "ok": False,
            "message": "候选切换后的几何快照与历史记录不一致，已恢复原候选。",
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "pending_action": None,
            "rollback_verification": rollback_verification,
        }
    next_navigation = {
        "project_id": project_id,
        "redo_stack": redo_stack,
        "current_variant_id": target_id,
    }
    conversation_memory.set_candidate_navigation(
        conversation_id, next_navigation if redo_stack else None
    )
    verb = "撤销" if action == "undo" else "重做"
    verification_text = (
        "，几何快照复核通过"
        if rollback_verification["status"] == "success" else ""
    )
    return {
        "ok": True,
        "configured": robot_agent.configured,
        "message": f"已{verb}候选修改{verification_text}，当前回到：{target.get('name') or target_id}。",
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "pending_action": None,
        "api_attempted": False,
        "api_provider": None,
        "project_id": project_id,
        "project": updated,
        "variants": updated.get("variants", []),
        "variant": target,
        "preview_paths": target.get("preview_paths", []),
        "next_action": "continue_design_iteration",
        "cad_history_navigation": {
            "action": action,
            "from_variant_id": current_id,
            "to_variant_id": target_id,
            "redo_available": bool(redo_stack),
        },
        "rollback_verification": rollback_verification,
    }



def _run_idempotency_key(command: AgentChatRequest) -> str:
    payload = command.model_dump(mode="json", exclude_none=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _prepare_run_step(
    run_id: str,
    command: AgentChatRequest,
    pending_command: dict[str, object] | None,
) -> dict[str, object]:
    prepared = _prepare_agent_chat_context(command)
    route = prepared.get("route")
    if isinstance(route, dict):
        route["agent_run_id"] = run_id
        route["idempotency_key"] = run_id
    agent_runs.set_checkpoint(run_id, {
        "schema": "agent.checkpoint.v3",
        "step_id": "context_prepared",
        "next_step": "execute",
        "completed_steps": ["understanding", "context_prepared"],
        "idempotency_key": run_id,
        "project_id": command.project_id,
        "variant_id": command.variant_id,
        "drawing_selection": command.drawing_selection.model_dump() if command.drawing_selection else None,
        "pending_command": deepcopy(pending_command) if isinstance(pending_command, dict) else None,
        "prepared_context": prepared,
    })
    return prepared


def _generate_run_result(
    run_id: str,
    command: AgentChatRequest,
    prepared: dict[str, object],
) -> dict[str, object]:
    result = _agent_chat(command, prepared=prepared)
    result["agent_run_id"] = run_id
    agent_runs.set_checkpoint(run_id, {
        "schema": "agent.checkpoint.v3",
        "step_id": "result_generated",
        "next_step": "finalize",
        "completed_steps": ["understanding", "context_prepared", "execute"],
        "idempotency_key": run_id,
        "project_id": result.get("project_id") or command.project_id,
        "variant_id": (
            (result.get("variant") or {}).get("id")
            if isinstance(result.get("variant"), dict) else command.variant_id
        ),
        "drawing_selection": command.drawing_selection.model_dump() if command.drawing_selection else None,
        "pending_command": (
            result.get("cad_edit_contract") or result.get("cad_edit_command")
            if isinstance(result, dict) else None
        ),
        "result": result,
    })
    return result


def _finalize_run_result(
    run_id: str,
    command: AgentChatRequest,
    result: dict[str, object],
) -> dict[str, object]:
    result = dict(result)
    result["agent_run_id"] = run_id
    run = agent_runs.get(run_id) or {}
    project = result.get("project") if isinstance(result.get("project"), dict) else {}
    if not str(run.get("project_id") or "").strip():
        agent_runs.bind_context(
            run_id,
            project_id=str(result.get("project_id") or project.get("id") or "") or None,
        )
    result = _bind_and_filter_candidate_visibility(run_id, result)
    _record_agent_run_result(run_id, result)
    agent_runs.set_checkpoint(run_id, {
        "schema": "agent.checkpoint.v3",
        "step_id": "finalized",
        "next_step": None,
        "completed_steps": ["understanding", "context_prepared", "execute", "finalize"],
        "idempotency_key": run_id,
        "project_id": result.get("project_id"),
        "variant_id": (
            (result.get("variant") or {}).get("id")
            if isinstance(result.get("variant"), dict) else None
        ),
        "drawing_selection": command.drawing_selection.model_dump() if command.drawing_selection else None,
        "pending_command": result.get("cad_edit_contract") or result.get("cad_edit_command"),
        "result": result,
    })
    return result


def agent_chat(command: AgentChatRequest) -> dict[str, object]:
    # Keep model credentials and concurrency quotas request-scoped. The current
    # client_id is a local owner id until authenticated accounts are available.
    with agent_user_scope(command.client_id), structured_usage_scope():
        memory_snapshot = conversation_memory.context(command.conversation_id, [])
        pending_snapshot = memory_snapshot.get('pending_cad_edit') if isinstance(memory_snapshot, dict) else None
        run = agent_runs.create(
            command.message,
            conversation_id=command.conversation_id,
            user_id=command.client_id,
            project_id=command.project_id,
            source_variant_id=command.variant_id,
            drawing_selection=(command.drawing_selection.model_dump() if command.drawing_selection else None),
            pending_command=(pending_snapshot.get('command') if isinstance(pending_snapshot, dict) else None),
            idempotency_key=_run_idempotency_key(command),
            mode=command.mode,
        )
        agent_runs.transition(run["id"], "understanding", "开始理解用户请求")
        pending_command = pending_snapshot.get('command') if isinstance(pending_snapshot, dict) else None
        prepared = _prepare_run_step(run["id"], command, pending_command)
        result = _generate_run_result(run["id"], command, prepared)
        return _finalize_run_result(run["id"], command, result)



def agent_run_list(conversation_id: str | None = None, limit: int = 50) -> dict[str, object]:
    return {"ok": True, "runs": agent_runs.list(limit, conversation_id=conversation_id)}



def agent_run_detail(run_id: str) -> dict[str, object]:
    run = agent_runs.get(run_id)
    if run is None:
        return {"ok": False, "message": "Agent 运行记录不存在", "run": None}
    return {"ok": True, "run": run}



def cancel_agent_run(run_id: str, client_id: str | None = None) -> dict[str, object]:
    run = agent_runs.get(run_id)
    if run is None:
        return {"ok": False, "message": "Agent 运行记录不存在", "run": None}
    owner = str(run.get("user_id") or "")
    if owner and client_id and owner != client_id:
        return {"ok": False, "message": "无权取消其他用户的 AI 请求", "run": run}
    cancelled = agent_runs.cancel(run_id)
    if cancelled is None:
        return {"ok": False, "message": "Agent 运行记录不存在", "run": None}
    if cancelled.get("state") != "cancelled":
        return {"ok": False, "message": "该 AI 请求已结束，不能取消", "run": cancelled}
    return {"ok": True, "message": "AI 请求已取消", "run": cancelled}



def resume_agent_run(run_id: str, client_id: str | None = None) -> dict[str, object]:
    run = agent_runs.get(run_id)
    if run is None:
        return {"ok": False, "message": "Agent 运行记录不存在", "run": None}
    owner = str(run.get("user_id") or "")
    if owner and not client_id:
        return {"ok": False, "message": "恢复 AI 请求必须提供原始用户标识", "run": run}
    if owner and owner != client_id:
        return {"ok": False, "message": "无权恢复其他用户的 AI 请求", "run": run}
    if run.get("state") != "paused":
        return {"ok": False, "message": "当前运行不处于可恢复状态", "run": run}
    stored_selection = run.get("drawing_selection")
    checkpoint = run.get("checkpoint") if isinstance(run.get("checkpoint"), dict) else {}
    if stored_selection is None and isinstance(checkpoint.get("drawing_selection"), dict):
        stored_selection = checkpoint.get("drawing_selection")
    try:
        selection_model = (
            AgentDrawingSelection.model_validate(stored_selection)
            if isinstance(stored_selection, dict) else None
        )
    except Exception:
        conversation_memory.clear_pending_cad_edit(
            str(run.get("conversation_id") or "") or None,
            reason="cad_resume_invalid_selection",
        )
        return {"ok": False, "message": "恢复请求的选区快照无效，待确认命令已清除，请重新选择图形", "run": run}
    if selection_model is not None:
        stored_project = str(run.get("project_id") or "")
        stored_variant = str(run.get("source_variant_id") or "")
        if (stored_project and str(selection_model.project_id or "") != stored_project
                or stored_variant and str(selection_model.variant_id or "") != stored_variant):
            conversation_memory.clear_pending_cad_edit(
                str(run.get("conversation_id") or "") or None,
                reason="cad_resume_binding_mismatch",
            )
            return {"ok": False, "message": "恢复请求的项目、版本与选区不一致，待确认命令已清除，请重新选择图形", "run": run}
    stored_pending = run.get("pending_command")
    if not isinstance(stored_pending, dict) and isinstance(checkpoint.get("pending_command"), dict):
        stored_pending = checkpoint.get("pending_command")
    if isinstance(stored_pending, dict):
        selection_key = binding_key(selection_binding(stored_selection)) if isinstance(stored_selection, dict) else None
        command_project = str(stored_pending.get("project_id") or "")
        command_variant = str(stored_pending.get("variant_id") or "")
        command_key = binding_key(stored_pending.get("binding"))
        stored_project = str(run.get("project_id") or "")
        stored_variant = str(run.get("source_variant_id") or "")
        memory_now = conversation_memory.context(
            str(run.get("conversation_id") or "") or None, []
        )
        current_pending = (
            memory_now.get("pending_cad_edit") if isinstance(memory_now, dict) else None
        )
        current_command = (
            current_pending.get("command") if isinstance(current_pending, dict) else None
        )
        current_pending_key = binding_key(pending_binding(current_pending))
        current_command_key = (
            binding_key(current_command.get("binding"))
            if isinstance(current_command, dict) else None
        )
        if (selection_key is None
                or command_project != stored_project
                or command_variant != stored_variant
                or command_key != selection_key
                or current_pending_key != selection_key
                or current_command_key != selection_key
                or str((current_command or {}).get("project_id") or "") != stored_project
                or str((current_command or {}).get("variant_id") or "") != stored_variant
                or str((current_command or {}).get("operation") or "")
                    != str(stored_pending.get("operation") or "")):
            conversation_memory.clear_pending_cad_edit(
                str(run.get("conversation_id") or "") or None,
                reason="cad_resume_pending_command_mismatch",
            )
            return {"ok": False, "message": "恢复请求的待确认命令与项目、版本或选区不一致，已清除，请重新选择图形", "run": run}
    resumed = agent_runs.resume(run_id)
    if resumed is None or resumed.get("state") != "planning":
        return {"ok": False, "message": "当前运行不处于可恢复状态", "run": resumed or run}
    command = AgentChatRequest(
        message=str(resumed.get("user_message") or ""),
        mode=str(resumed.get("mode") or "advanced"),
        conversation_id=str(resumed.get("conversation_id") or "") or None,
        client_id=str(resumed.get("user_id") or client_id or "") or None,
        project_id=str(resumed.get("project_id") or "") or None,
        variant_id=str(resumed.get("source_variant_id") or "") or None,
        drawing_selection=selection_model,
    )
    checkpoint_result=checkpoint.get("result")
    if isinstance(checkpoint_result,dict) and checkpoint.get("step_id") in {
        "cad_result", "completed", "finalized",
    }:
        result=dict(checkpoint_result)
        result["agent_run_id"]=run_id
        result["resumed_from_checkpoint"]=True
        if resumed.get("state") not in {"completed","failed","cancelled"}:
            agent_runs.transition(run_id,"completed","从已持久化的 CAD 检查点恢复结果")
        return {"ok": result.get("ok") is True, "message":"已从 CAD 检查点恢复结果", "run":agent_runs.get(run_id), "result":result}
    if resumed.get("attempts") and not isinstance(checkpoint_result, dict):
        return {"ok": False, "message": "当前运行已产生执行记录，但缺少可恢复的步骤快照", "run": resumed}
    try:
        with agent_user_scope(command.client_id):
            if checkpoint.get("step_id") == "result_generated" and isinstance(checkpoint_result, dict):
                result = dict(checkpoint_result)
                resumed_step = "finalize"
            else:
                prepared_context = checkpoint.get("prepared_context")
                if checkpoint.get("step_id") == "context_prepared" and isinstance(prepared_context, dict):
                    prepared = dict(prepared_context)
                    resumed_step = "execute"
                else:
                    prepared = _prepare_run_step(
                        run_id,
                        command,
                        stored_pending if isinstance(stored_pending, dict) else None,
                    )
                    resumed_step = "context_prepared"
                result = _generate_run_result(run_id, command, prepared)
            result = _finalize_run_result(run_id, command, result)
        result["resumed_from_checkpoint"] = True
        result["resumed_step"] = resumed_step
        current = agent_runs.get(run_id) or resumed
        return {"ok": result.get("ok") is True, "message": f"AI 请求已从 {resumed_step} 步骤继续", "run": current, "result": result}
    except Exception as error:
        failure = {"category": "resume_failure", "message": str(error), "retryable": True}
        agent_runs.transition(run_id, "failed", "从检查点恢复失败", failure=failure)
        return {"ok": False, "message": "从检查点恢复失败", "run": agent_runs.get(run_id)}



def _record_agent_run_result(run_id: str, result: dict[str, object]) -> None:
    if result.get("clarification_required") is True:
        agent_runs.transition(run_id, "awaiting_clarification", "等待用户补充或确认目标")
        return

    variant = result.get("variant") if isinstance(result.get("variant"), dict) else {}
    project = result.get("project") if isinstance(result.get("project"), dict) else {}
    edit_plan = variant.get("edit_plan") if isinstance(variant.get("edit_plan"), dict) else {}
    machine_assertions = (
        result.get("machine_assertions")
        if isinstance(result.get("machine_assertions"), dict)
        else variant.get("machine_assertions")
        if isinstance(variant.get("machine_assertions"), dict)
        else {}
    )
    geometry_diff = (
        result.get("geometry_diff")
        if isinstance(result.get("geometry_diff"), dict)
        else variant.get("geometry_diff")
        if isinstance(variant.get("geometry_diff"), dict)
        else {}
    )
    edit_repair = (
        result.get("edit_repair")
        if isinstance(result.get("edit_repair"), dict)
        else variant.get("edit_repair")
        if isinstance(variant.get("edit_repair"), dict)
        else (edit_plan.get("assertion_recovery") or edit_plan.get("repair"))
        if isinstance(edit_plan.get("assertion_recovery") or edit_plan.get("repair"), dict)
        else {}
    )
    project_id = str(result.get("project_id") or project.get("id") or "").strip()
    variant_id = str(variant.get("id") or "").strip()
    is_cad_result = bool(variant_id or edit_plan or machine_assertions or geometry_diff)

    if project_id or variant_id:
        agent_runs.bind_context(
            run_id,
            project_id=project_id or None,
            source_variant_id=str(variant.get("parent_variant_id") or "").strip() or None,
        )

    if not is_cad_result:
        if result.get("ok") is True:
            agent_runs.transition(run_id, "completed", "AI 请求已完成")
        else:
            resolution = classify_agent_failure([], message=str(result.get("message") or ""))
            result["failure_resolution"] = resolution
            agent_runs.transition(
                run_id,
                "failed",
                "AI 请求未完成",
                failure={"message": str(result.get("message") or ""), **resolution},
            )
        return

    agent_runs.transition(run_id, "planning", "CAD 修改计划已生成")
    if edit_plan:
        agent_runs.add_step(run_id, {
            "idempotency_key": f"{run_id}:cad_plan",
            "kind": "cad_plan",
            "state": "done",
            "operation": edit_plan.get("operation"),
            "target": edit_plan.get("target"),
            "expected_changes": edit_plan.get("expected_changes"),
        })
        assertions = edit_plan.get("assertions")
        if isinstance(assertions, list):
            agent_runs.set_success_criteria(
                run_id, [dict(item) for item in assertions if isinstance(item, dict)]
            )
    agent_runs.transition(run_id, "executing", "CAD 修改已执行并生成候选方案")
    agent_runs.add_step(run_id, {
        "idempotency_key": f"{run_id}:cad_execute",
        "kind": "cad_execute",
        "state": "done" if result.get("ok") is True else "failed",
        "project_id": project_id or None,
        "variant_id": variant_id or None,
        "geometry_diff": geometry_diff or None,
    })
    if variant_id:
        agent_runs.add_artifact(run_id, {
            "idempotency_key": f"{run_id}:cad_candidate:{variant_id}",
            "kind": "cad_candidate",
            "project_id": project_id or None,
            "variant_id": variant_id,
            "name": variant.get("name"),
            "parent_variant_id": variant.get("parent_variant_id"),
        })
    verified = machine_assertions.get("verified") if machine_assertions else result.get("ok") is True
    failure_codes = list(machine_assertions.get("failure_codes") or []) if machine_assertions else []
    repair_attempted = edit_repair.get("attempted") is True
    if repair_attempted:
        trigger_codes = list(edit_repair.get("trigger_failure_codes") or [])
        agent_runs.transition(run_id, "verifying", "首次 CAD 机器断言未通过")
        agent_runs.add_attempt(run_id, {
            "idempotency_key": f"{run_id}:cad_attempt:0",
            "index": 0,
            "project_id": project_id or None,
            "variant_id": None,
            "verified": False,
            "failure_codes": trigger_codes,
            "assertion_report_sha256": edit_repair.get("before_report_sha256"),
        })
        agent_runs.transition(run_id, "retrying", "开始一次确定性自动修复")
        agent_runs.add_step(run_id, {
            "idempotency_key": f"{run_id}:cad_repair",
            "kind": "cad_repair",
            "state": "done" if edit_repair.get("recovered") is True else "failed",
            "strategy": edit_repair.get("strategy"),
            "actions": list(edit_repair.get("actions") or []),
            "trigger_failure_codes": trigger_codes,
            "attempt_count": int(edit_repair.get("attempt_count") or 0),
        })
        agent_runs.transition(run_id, "executing", "确定性修复已应用")
        agent_runs.transition(run_id, "verifying", "正在复核自动修复结果")
        attempt_index = 1
    else:
        agent_runs.transition(run_id, "verifying", "正在验证 CAD 修改结果")
        attempt_index = 0
    agent_runs.add_step(run_id, {
        "idempotency_key": f"{run_id}:cad_verify:{attempt_index}",
        "kind": "cad_verify",
        "state": "done" if verified is True else "failed",
        "verified": verified is True,
        "failure_codes": failure_codes,
    })
    agent_runs.add_attempt(run_id, {
        "idempotency_key": f"{run_id}:cad_attempt:{attempt_index}",
        "index": attempt_index,
        "project_id": project_id or None,
        "variant_id": variant_id or None,
        "verified": verified is True,
        "failure_codes": failure_codes,
        "assertion_report_sha256": (
            edit_repair.get("after_report_sha256")
            if repair_attempted else machine_assertions.get("report_sha256")
        ),
        "repair_attempted": repair_attempted,
    })
    if result.get("ok") is True and verified is True:
        agent_runs.transition(run_id, "completed", "CAD 修改已通过机器断言")
    else:
        resolution = classify_agent_failure(
            failure_codes, message=str(result.get("message") or "")
        )
        result["failure_resolution"] = resolution
        failure = {"message": str(result.get("message") or ""), **resolution}
        if resolution["next_action"] == "ask_user":
            agent_runs.transition(
                run_id, "awaiting_clarification", resolution["guidance"], failure=failure
            )
        else:
            agent_runs.transition(
                run_id, "failed", "CAD 修改未通过机器断言", failure=failure
            )



def _prepare_agent_chat_context(command: AgentChatRequest) -> dict[str, object]:
    """Prepare the request context shared by sync and streaming chat.

    This function intentionally stops before producing a model result. Both
    transports must resolve history, memory, follow-ups, route metadata and
    knowledge from the same snapshot so a request cannot take different
    business paths merely because the client selected streaming.
    """
    project_store = get_creative_project_store()
    history = [message.model_dump() for message in command.history]
    memory_before = conversation_memory.context(command.conversation_id, history)
    routing_history = _routing_history(history, memory_before)
    selection = command.drawing_selection.model_dump() if command.drawing_selection else {}
    project_ids = {str(value) for value in (command.project_id, selection.get('project_id')) if value}
    variant_ids = {str(value) for value in (command.variant_id, selection.get('variant_id')) if value}
    binding_error = None
    if len(project_ids) > 1 or len(variant_ids) > 1:
        binding_error = '请求中的项目、版本与选区不一致，请重新选择图形。'
    elif project_ids:
        bound = project_store.get(next(iter(project_ids)))
        if not isinstance(bound, dict):
            binding_error = '当前项目不存在，请重新选择项目。'
        elif variant_ids:
            variant = next((v for v in bound.get('variants') or [] if str(v.get('id')) in variant_ids), None)
            if variant is None:
                binding_error = '当前版本不属于所选项目，请重新选择图形。'
            else:
                from .cad_candidate_state import candidate_is_accepted
                if not candidate_is_accepted(variant):
                    binding_error = '当前版本尚未通过几何验收，不能作为修改基线。'
            if binding_error is None and selection.get('geometry_ids'):
                ids = {str(g.get('id')) for g in variant.get('geometries') or []}
                if any(str(i) not in ids for i in selection['geometry_ids']):
                    binding_error = '选区包含当前版本不存在的图元，请重新选择图形。'
            if binding_error is None and (selection.get('object_id') or selection.get('object_ids')):
                logical_ids = {
                    str(value)
                    for item in variant.get('logical_objects') or []
                    if isinstance(item, dict)
                    for value in (item.get('object_id'), item.get('id'))
                    if value is not None
                }
                selected_objects = {
                    str(value) for value in (
                        [selection.get('object_id')] + list(selection.get('object_ids') or [])
                    ) if value
                }
                if not selected_objects.issubset(logical_ids):
                    binding_error = '选区包含当前版本不存在的部件，请重新选择图形。'
    elif variant_ids:
        binding_error = '指定图纸版本时必须同时指定项目。'
    if binding_error:
        pending_before = memory_before.get('pending_cad_edit') if isinstance(memory_before, dict) else None
        pending_key = binding_key(pending_binding(pending_before))
        request_selection = dict(selection) if selection else None
        if request_selection:
            if project_ids:
                request_selection['project_id'] = next(iter(project_ids))
            if variant_ids:
                request_selection['variant_id'] = next(iter(variant_ids))
        request_key = binding_key(selection_binding(request_selection)) if request_selection else None
        if (isinstance(pending_before, dict) and pending_key is not None and
                (request_key is None or request_key != pending_key)):
            conversation_memory.clear_pending_cad_edit(
                command.conversation_id, reason='cad_context_binding_mismatch'
            )
            binding_error = '项目、版本、选区与待确认命令不一致，待确认命令已清除，请重新选择图形后再确认。'
        return {'history': history, 'memory_before': memory_before,
                'routing_history': routing_history,
                'resolution': {'required': True, 'resolved': False,
                               'ambiguous': False, 'candidates': []},
                'route': {
                    'name': 'drawing_design', 'tool_family': 'cad',
                    'operation': 'modify', 'stage': 'requirements',
                    'clarification_required': True,
                    'selected_project_id': next(iter(project_ids), None),
                    'selected_variant_id': next(iter(variant_ids), None),
                    'binding_error': binding_error,
                },
                'navigation_result': {'ok': False, 'message': binding_error,
                    'error_code': 'cad_context_binding_mismatch',
                    'preview_paths': [], 'variant': None, 'variants': []}}
    # Normalize the binding once.  The App may put project/version on the
    # request envelope while the selection contains only geometry IDs; every
    # downstream edit session must nevertheless receive the full tuple.
    if selection:
        if project_ids:
            selection['project_id'] = next(iter(project_ids))
        if variant_ids:
            selection['variant_id'] = next(iter(variant_ids))
    confirmation_message = bool(
        re.search(r"(确认|确定|提交|生成候选|继续执行)", command.message or "")
    )
    conversation_memory.observe(command.conversation_id, command.message)
    navigation_result = _navigate_cad_candidate(
        command.message, memory_before, command.conversation_id
    )
    if navigation_result is not None:
        pending_probe = memory_before.get('pending_cad_edit') if isinstance(memory_before, dict) else None
        probe_key = binding_key(pending_binding(pending_probe))
        probe_selection = dict(selection) if selection else None
        if probe_selection:
            if project_ids:
                probe_selection['project_id'] = next(iter(project_ids))
            if variant_ids:
                probe_selection['variant_id'] = next(iter(variant_ids))
        probe_binding = binding_key(selection_binding(probe_selection)) if probe_selection else None
        if (isinstance(pending_probe, dict) and probe_key is not None and
                (confirmation_message and probe_binding is None or
                 (probe_binding is not None and probe_binding != probe_key))):
            conversation_memory.clear_pending_cad_edit(
                command.conversation_id, reason='cad_context_binding_mismatch'
            )
            binding_error = '项目、版本、选区与待确认命令不一致，待确认命令已清除，请重新选择图形后再确认。'
            navigation_result = {
                'ok': False, 'message': binding_error,
                'error_code': 'cad_context_binding_mismatch',
                'preview_paths': [], 'variant': None, 'variants': [],
                'route': {'name': 'drawing_design', 'tool_family': 'cad',
                          'operation': 'modify', 'clarification_required': True,
                          'binding_error': binding_error,
                          'decision_source': 'cad_context_binding_guard'},
            }
        return {
            "history": history,
            "memory_before": memory_before,
            "routing_history": routing_history,
            "resolution": {'required': False, 'resolved': True,
                           'ambiguous': False, 'candidates': []},
            "route": navigation_result.get("route") if isinstance(navigation_result, dict) else None,
            "navigation_result": navigation_result,
        }
    from .cad_edit_session import continuation, edit_text, fresh_creation
    pending_before = memory_before.get('pending_cad_edit') if isinstance(memory_before, dict) else None
    pending_key = binding_key(pending_binding(pending_before))
    # A pending command is a four-part capability: project, variant, drawing
    # selection and command.  If a caller supplies any context for a follow-up
    # (or confirms without supplying the selection), invalidate the stale
    # command instead of allowing continuation() to silently reuse it.
    request_selection = dict(selection) if selection else None
    if request_selection and project_ids:
        request_selection['project_id'] = next(iter(project_ids))
    if request_selection and variant_ids:
        request_selection['variant_id'] = next(iter(variant_ids))
    request_key = binding_key(selection_binding(request_selection)) if request_selection else None
    context_supplied = bool(command.project_id or command.variant_id or command.drawing_selection is not None)
    pending_mismatch = (
        isinstance(pending_before, dict)
        and pending_key is not None
        and ((confirmation_message and request_key is None)
             or (context_supplied and request_key is not None and request_key != pending_key)
             or (context_supplied and request_key is None))
    )
    if pending_mismatch:
        conversation_memory.clear_pending_cad_edit(
            command.conversation_id, reason='cad_context_binding_mismatch'
        )
        binding_error = '项目、版本、选区与待确认命令不一致，待确认命令已清除，请重新选择图形后再确认。'
        return {
            'history': history,
            'memory_before': conversation_memory.context(command.conversation_id, history),
            'routing_history': routing_history,
            'resolution': {'required': True, 'resolved': False,
                           'ambiguous': False, 'candidates': []},
            'route': {
                'name': 'drawing_design', 'tool_family': 'cad',
                'operation': 'modify', 'stage': 'requirements',
                'clarification_required': True,
                'binding_error': binding_error,
                'decision_source': 'cad_context_binding_guard',
            },
            'navigation_result': {'ok': False, 'message': binding_error,
                'error_code': 'cad_context_binding_mismatch',
                'preview_paths': [], 'variant': None, 'variants': []},
        }
    supplied_selection=selection if command.drawing_selection is not None else None
    edit_session=continuation(command.message,memory_before,command.project_id,supplied_selection,project_store.get)
    contextual_message = edit_session['message'] if edit_session else _resolve_cad_followup(command.message, memory_before)
    resolution = conversation_memory.resolve(
        command.conversation_id, contextual_message, history
    )
    resolved_message = str(resolution.get("message") or command.message)
    model_message = _agent_message_with_attachments(command, resolved_message)
    route = (
        robot_agent.route_intent(command.message, command.mode)
        if resolution.get("ambiguous")
        else robot_agent.resolve_intent(resolved_message, command.mode, routing_history)
    )
    route["user_message"] = command.message
    bound_project_id = str(command.project_id or selection.get('project_id') or '')
    bound_variant_id = str(command.variant_id or selection.get('variant_id') or '')
    if bound_project_id:
        route["selected_project_id"] = bound_project_id
    if bound_variant_id:
        route["selected_variant_id"] = bound_variant_id
    route["reference_resolution"] = {
        key: resolution.get(key)
        for key in ("required", "resolved", "ambiguous", "target", "candidates")
        if resolution.get(key) is not None
    }
    route["object_memory"] = resolution.get("memory", {})
    route["retrieved_memory"] = resolution.get("retrieved", {})
    if command.drawing_selection is not None:
        route["drawing_selection"] = dict(selection)
    # A request carrying an existing project, an explicit drawing selection,
    # and at least one saved candidate is a continuation/edit. Do not let
    # model intent classification downgrade it to a fresh project creation.
    bound_project = project_store.get(bound_project_id) if bound_project_id else None
    if (
        bound_project_id
        and command.drawing_selection is not None
        and isinstance(bound_project, dict)
        and bound_project.get("variants")
    ):
        route.update({
            "name": "drawing_design",
            "tool_family": "cad",
            "operation": "modify",
            "decision_source": "bound_project_edit",
            "selected_project_id": bound_project_id,
            "clarification_required": False,
            "review_required": False,
            "safety_confirmation_required": False,
        })
    if edit_session:
        route['cad_edit_session']=edit_session
        route['selected_project_id']=edit_session['project_id']
        route['selected_variant_id']=edit_session['variant_id']
        route['drawing_selection']=edit_session['drawing_selection']
    # An explicit project_id from the request is authoritative. Automatic
    # session recovery may refer to an older conversation project and must not
    # overwrite the copied template project selected by the caller.
    if bound_project_id:
        route['selected_project_id'] = bound_project_id
    if bound_variant_id:
        route['selected_variant_id'] = bound_variant_id
    route['project_binding_trace'] = {
        'request_project_id': bound_project_id or None,
        'session_project_id': edit_session.get('project_id') if edit_session else None,
        'selected_project_id': route.get('selected_project_id'),
        'conversation_id': command.conversation_id,
    }
    if isinstance(route.get('drawing_selection'),dict):
        pending_edit = memory_before.get('pending_cad_edit') if isinstance(memory_before, dict) else None
        current_binding=selection_binding(route.get('drawing_selection'))
        route['cad_context_binding'] = {
            'project_id': str(route.get('selected_project_id') or '') or None,
            'variant_id': str(route.get('selected_variant_id') or route['drawing_selection'].get('variant_id') or '') or None,
            'selection': current_binding,
            'pending_command_binding': pending_binding(pending_edit),
        }
        confirmation_message=bool(re.search(r"(确认|确定|提交|生成候选|继续执行)", command.message or ""))
        if (confirmation_message and isinstance(pending_edit, dict) and edit_session
                and pending_edit.get('project_id') == route.get('selected_project_id')
                and pending_edit.get('variant_id') == route['drawing_selection'].get('variant_id')
                and binding_key(pending_edit.get('binding') or selection_binding(pending_edit.get('drawing_selection')))
                    == binding_key(current_binding)):
            pending_command = pending_edit.get('command') or pending_edit.get('cad_edit_command')
            command_project = str(pending_command.get('project_id') or '') if isinstance(pending_command, dict) else ''
            command_variant = str(pending_command.get('variant_id') or '') if isinstance(pending_command, dict) else ''
            command_binding = pending_command.get('binding') if isinstance(pending_command, dict) else None
            if (isinstance(pending_command, dict) and pending_command.get('operation')
                    and command_project == str(route.get('selected_project_id') or '')
                    and command_variant == str(route['drawing_selection'].get('variant_id') or '')
                    and binding_key(command_binding) == binding_key(current_binding)):
                route.update({
                    'name':'drawing_design','tool_family':'cad','operation':'modify',
                    'decision_source':'conversation_pending_cad_edit',
                    'resolved_edit':pending_command,
                    'project_id':str(command.project_id or pending_edit.get('project_id') or ''),
                    'selected_project_id':str(command.project_id or pending_edit.get('project_id') or ''),
                    'clarification_required':False,'review_required':False,
                })
            elif isinstance(pending_command, dict):
                conversation_memory.clear_pending_cad_edit(
                    command.conversation_id, reason='cad_pending_command_binding_mismatch'
                )
                route.update({
                    'clarification_required': True,
                    'clarification_question': '待确认命令与当前项目、版本或选区不一致，已清除，请重新选择图形后再确认。',
                    'binding_error': 'cad_pending_command_binding_mismatch',
                    'decision_source': 'cad_context_binding_guard',
                })
        # Parse the user's edit before enriched context (which includes base
        # creation requirements and can mask a precise array operation).
        parse_inputs = ([contextual_message, command.message] if edit_session
                        else [command.message, contextual_message])
        selected_parse = next((value for value in (
            parse_incremental_edit(edit_text(text)+" 图形") for text in parse_inputs
        ) if value is not None), None)
        from .cad_edit_chain import parse_incremental_edit_chain
        selected_chain=parse_incremental_edit_chain(edit_text(command.message),selection_bound=True)
        if (
            command.mode == "advanced"
            and (not fresh_creation(command.message) or command.project_id)
            and not route.get('binding_error')
            and selected_parse is not None
        ):
            route.update({
                "name": "drawing_design",
                "tool_family": "cad",
                "operation": "modify",
                "decision_source": "incremental_cad_edit",
                "review_required": False,
                "clarification_required": False,
                "safety_confirmation_required": False,
                "resolved_edit":selected_parse,
            })
            if command.project_id:
                conversation_memory.remember(
                    command.conversation_id,
                    command.message,
                    {"ok": True, "cad_edit_command": selected_parse,
                     "project_id": str(command.project_id),
                     "drawing_selection": dict(selection)},
                    route=route,
                )
            if selected_chain:
                route.update(decision_source='incremental_cad_edit_chain',edit_chain=selected_chain)
    # Rebuild the actual service message after edit-session and requirement
    # merging. Previously only contextual_message changed; both transports
    # still dispatched the stale pre-merge model_message.
    resolved_message = contextual_message
    model_message = _agent_message_with_attachments(command, resolved_message)
    stale_guide = robot_agent._stale_project_guard(route)
    knowledge = robot_agent.knowledge_context(command.message, route)
    # Freeze the resolved execution input after all parameter merging. Both
    # streaming and non-streaming dispatch consume this prepared context;
    # checkpoints persist the same snapshot through prepared_context.
    from .cad_requirement_contract import project_requirement_state
    execution_project_id = robot_agent._project_id_from_route(route)
    execution_project = project_store.get(execution_project_id) if execution_project_id else None
    execution_selection = deepcopy(route.get('drawing_selection'))
    execution_snapshot = {
        'schema': 'cad.execution-context.v1',
        'project_id': execution_project_id,
        'source_variant_id': (
            (execution_selection or {}).get('variant_id')
            or route.get('selected_variant_id') or command.variant_id
        ),
        'drawing_selection': execution_selection,
        'operation': route.get('operation'),
        'decision_source': route.get('decision_source'),
        'requirement_state': project_requirement_state(execution_project) if execution_project else None,
        'requirements': deepcopy((execution_project or {}).get('requirements') or {}),
        'constraints': deepcopy((execution_project or {}).get('constraints') or {}),
    }
    execution_snapshot['sha256'] = hashlib.sha256(json.dumps(
        execution_snapshot, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), default=str,
    ).encode('utf-8')).hexdigest()
    route['execution_context'] = execution_snapshot
    return {
        "history": history,
        "memory_before": memory_before,
        "routing_history": routing_history,
        "navigation_result": None,
        "contextual_message": contextual_message,
        "resolution": resolution,
        "resolved_message": resolved_message,
        "model_message": model_message,
        "route": route,
        "knowledge": knowledge,
        "stale_guide": stale_guide,
    }



def _execution_context_error(route):
    """Reject a prepared CAD context that drifted before execution."""
    snapshot = route.get('execution_context')
    if not isinstance(snapshot, dict):
        return None  # Legacy checkpoints have no frozen context.
    if route.get('tool_family') != 'cad' and route.get('name') != 'drawing_design':
        return None
    from .cad_requirement_contract import project_requirement_state
    value = deepcopy(snapshot)
    digest = value.pop('sha256', None)
    actual = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), default=str).encode('utf-8')).hexdigest()
    reason = None
    if digest != actual:
        reason = 'snapshot_integrity'
    elif (snapshot.get('project_id') != robot_agent._project_id_from_route(route)
          or snapshot.get('operation') != route.get('operation')
          or snapshot.get('drawing_selection') != route.get('drawing_selection')):
        reason = 'route_binding_changed'
    project_id = snapshot.get('project_id')
    if project_id and reason is None:
        project = get_creative_project_store().get(project_id)
        if not project:
            reason = 'project_missing'
        elif project_requirement_state(project) != snapshot.get('requirement_state'):
            reason = 'requirements_changed'
        elif snapshot.get('source_variant_id') and not any(
            variant.get('id') == snapshot['source_variant_id']
            for variant in project.get('variants') or []
        ):
            reason = 'source_variant_missing'
    if reason:
        return {'ok': False, 'error_code': 'cad_execution_context_stale',
                'message': '项目或需求已变化，请基于当前项目重新确认操作。',
                'reason': reason, 'project_id': project_id, 'api_attempted': False}
    return None


def _agent_chat(
    command: AgentChatRequest,
    *,
    prepared: dict[str, object] | None = None,
) -> dict[str, object]:
    prepared = prepared or _prepare_agent_chat_context(command)
    history = prepared["history"]
    memory_before = prepared["memory_before"]
    navigation_result = prepared["navigation_result"]
    if navigation_result is not None:
        navigation_result["object_memory"] = conversation_memory.remember(
            command.conversation_id, command.message, navigation_result
        )
        return normalize_acceptance_response(navigation_result)
    resolution = prepared["resolution"]
    model_message = prepared["model_message"]
    route = prepared["route"]
    context_error = _execution_context_error(route)
    if context_error is not None:
        return context_error
    knowledge = prepared["knowledge"]
    stale_guide = prepared["stale_guide"]
    if stale_guide is not None:
        enriched = robot_agent.enrich_result({
            "ok": True,
            "configured": robot_agent.configured,
            "message": stale_guide,
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "pending_action": None,
            "api_attempted": False,
            "api_provider": None,
        }, route, knowledge)
        enriched["object_memory"] = conversation_memory.remember(
            command.conversation_id, command.message, enriched, route=route
        )
        return enriched
    if resolution.get("ambiguous") and not route.get("drawing_selection"):
        route.update({
            "clarification_required": True,
            "clarification_question": str(resolution.get("question")),
            "decision_source": "object_memory_clarification",
        })
    knowledge = robot_agent.knowledge_context(command.message, route)
    try:
        if route.get("clarification_required"):
            enriched = robot_agent.enrich_result({
                "ok": True,
                "configured": robot_agent.configured,
                "message": str(route.get("clarification_question")),
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "pending_action": None,
                "api_attempted": route.get("decision_source") in {
                    "model_clarification", "safety_clarification",
                },
                "api_provider": robot_agent.mode,
            }, route, knowledge)
            enriched["object_memory"] = conversation_memory.remember(
                command.conversation_id, command.message, enriched, route=route
            )
            return enriched
        result = robot_agent.chat(
            model_message,
            history,
            mode=command.mode,
            route=route,
        )
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        api_attempted = int(usage.get("total_tokens", 0) or 0) > 0 or (
            robot_agent.configured and (
                robot_agent.normalize_agent_mode(command.mode) == "advanced"
                or route.get("api_required", False)
            )
        )
        result["api_attempted"] = api_attempted
        result["api_provider"] = robot_agent.mode if api_attempted else None
        result = _enforce_requirement_confirmation(result, route)
        enriched = robot_agent.enrich_result(result, route, knowledge)
        enriched["object_memory"] = conversation_memory.remember(
            command.conversation_id, command.message, enriched, route=route
        )
        return enriched
    except Exception as error:
        robot_state.add_log(f"agent error: {error}")
        enriched = robot_agent.enrich_result({
            "ok": False,
            "configured": robot_agent.configured,
            "message": "AI 服务暂时不可用，请稍后重试。",
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "pending_action": None,
        }, route, knowledge)
        enriched["object_memory"] = conversation_memory.remember(
            command.conversation_id, command.message, enriched, route=route
        )
        return enriched



def agent_chat_stream(command: AgentChatRequest) -> StreamingResponse:
    memory_snapshot = conversation_memory.context(command.conversation_id, [])
    pending_snapshot = memory_snapshot.get('pending_cad_edit') if isinstance(memory_snapshot, dict) else None
    run = agent_runs.create(
        command.message,
        conversation_id=command.conversation_id,
        user_id=command.client_id,
        project_id=command.project_id,
        source_variant_id=command.variant_id,
        drawing_selection=(command.drawing_selection.model_dump() if command.drawing_selection else None),
        pending_command=(pending_snapshot.get('command') if isinstance(pending_snapshot, dict) else None),
        idempotency_key=_run_idempotency_key(command),
        mode=command.mode,
    )

    def events():
        # Starlette may resume this generator in different worker contexts;
        # do not hold a ContextVar token across the full response lifetime.
        agent_runs.transition(run["id"], "understanding", "开始理解用户请求")
        pending_command = pending_snapshot.get('command') if isinstance(pending_snapshot, dict) else None
        prepared = _prepare_run_step(run["id"], command, pending_command)
        final_result: dict[str, object] | None = None
        finalized = False
        for payload in usage_scoped_events(_agent_chat_stream_events(command, prepared=prepared)):
            try:
                decoded = json.loads(payload)
            except (TypeError, json.JSONDecodeError):
                decoded = {}
            if isinstance(decoded, dict) and decoded.get("type") == "result":
                final_result = decoded
                decoded["agent_run_id"] = run["id"]
                agent_runs.set_checkpoint(run["id"], {
                    "schema":"agent.checkpoint.v3",
                    "step_id":"result_generated",
                    "next_step":"finalize",
                    "completed_steps":["understanding", "context_prepared", "execute"],
                    "idempotency_key":run["id"],
                    "project_id":decoded.get("project_id"),
                    "variant_id":(decoded.get("variant") or {}).get("id") if isinstance(decoded.get("variant"),dict) else None,
                    "drawing_selection": command.drawing_selection.model_dump() if command.drawing_selection else None,
                    "pending_command": (decoded.get('cad_edit_contract') or decoded.get('cad_edit_command')) if isinstance(decoded, dict) else None,
                    "result":decoded,
                })
                decoded = _finalize_run_result(run["id"], command, decoded)
                final_result = decoded
                finalized = True
                payload = json.dumps(decoded, ensure_ascii=False) + "\n"
            yield payload
        if not finalized:
            _record_agent_run_result(run["id"], final_result or {"ok": False})

    return StreamingResponse(events(), media_type="application/x-ndjson")



def _agent_chat_stream_events(
    command: AgentChatRequest,
    *,
    prepared: dict[str, object] | None = None,
):
        prepared = prepared or _prepare_agent_chat_context(command)
        history = prepared["history"]
        memory_before = prepared["memory_before"]
        navigation_result = prepared["navigation_result"]
        if navigation_result is not None:
            yield json.dumps({
                "type": "context",
                "agent_context": {"stage": "cad_candidate_navigation"},
                "api_configured": robot_agent.configured,
                "api_provider": robot_agent.mode,
                "knowledge_sources": [],
                "object_memory": memory_before,
                "retrieved_memory": {},
            }, ensure_ascii=False) + "\n"
            navigation_result["object_memory"] = conversation_memory.remember(
                command.conversation_id, command.message, navigation_result
            )
            yield json.dumps(
                {"type": "result", **normalize_acceptance_response(navigation_result)}, ensure_ascii=False
            ) + "\n"
            return
        resolution = prepared["resolution"]
        model_message = prepared["model_message"]
        route = prepared["route"]
        context_error = _execution_context_error(route)
        if context_error is not None:
            yield json.dumps({'type': 'result', **context_error}, ensure_ascii=False) + '\n'
            return
        knowledge = prepared["knowledge"]
        stale_guide = prepared["stale_guide"]
        if stale_guide is not None:
            yield json.dumps({
                "type": "context",
                "agent_context": robot_agent.runtime_context(route),
                "api_configured": robot_agent.configured,
                "api_provider": robot_agent.mode,
                "knowledge_sources": [],
                "object_memory": resolution.get("memory", {}),
                "retrieved_memory": resolution.get("retrieved", {}),
            }, ensure_ascii=False) + "\n"
            enriched = robot_agent.enrich_result({
                "ok": True,
                "configured": robot_agent.configured,
                "message": stale_guide,
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "pending_action": None,
                "api_attempted": False,
                "api_provider": None,
            }, route, knowledge)
            enriched["object_memory"] = conversation_memory.remember(
                command.conversation_id, command.message, enriched, route=route
            )
            yield json.dumps({"type": "result", **enriched}, ensure_ascii=False) + "\n"
            return
        if resolution.get("ambiguous") and not route.get("drawing_selection"):
            route.update({
                "clarification_required": True,
                "clarification_question": str(resolution.get("question")),
                "decision_source": "object_memory_clarification",
            })
        knowledge = robot_agent.knowledge_context(command.message, route)
        try:
            yield json.dumps({
                "type": "context",
                "agent_context": robot_agent.runtime_context(route),
                "api_configured": robot_agent.configured,
                "api_provider": robot_agent.mode,
                "knowledge_sources": [
                    {key: item.get(key) for key in (
                        "id", "title", "source", "line_start", "line_end", "score"
                    )}
                    for item in knowledge.get("matches", [])
                ],
                "object_memory": resolution.get("memory", {}),
                "retrieved_memory": resolution.get("retrieved", {}),
            }, ensure_ascii=False) + "\n"
            if route.get("clarification_required"):
                result = robot_agent.enrich_result({
                    "ok": True,
                    "configured": robot_agent.configured,
                    "message": str(route.get("clarification_question")),
                    "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                    "pending_action": None,
                    "api_attempted": route.get("decision_source") in {
                        "model_clarification", "safety_clarification",
                    },
                    "api_provider": robot_agent.mode,
                }, route, knowledge)
                result["object_memory"] = conversation_memory.remember(
                    command.conversation_id, command.message, result, route=route
                )
                yield json.dumps({"type": "result", **result}, ensure_ascii=False) + "\n"
                return
            for event in robot_agent.chat_stream(
                model_message,
                history,
                mode=command.mode,
                route=route,
                user_id=command.client_id,
            ):
                if event.get("type") == "result":
                    usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
                    api_attempted = int(usage.get("total_tokens", 0) or 0) > 0 or (
                        robot_agent.configured and (
                            robot_agent.normalize_agent_mode(command.mode) == "advanced"
                            or route.get("api_required", False)
                        )
                    )
                    event["api_attempted"] = api_attempted
                    event["api_provider"] = robot_agent.mode if api_attempted else None
                    event = _enforce_requirement_confirmation(event, route)
                    event = robot_agent.enrich_result(event, route, knowledge)
                    event["object_memory"] = conversation_memory.remember(
                        command.conversation_id, command.message, event, route=route
                    )
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as error:
            # Never leave a streaming response without a terminal result.
            # Keep implementation details in the server log only.
            robot_state.add_log(f"agent stream error: {error}")
            error_text = str(error)
            user_message = (
                f"CAD 几何验收失败：{error_text}"
                if "实际径向" in error_text or "几何" in error_text
                else "AI 服务响应中断，请稍后重试。"
            )
            result = {
                "ok": False,
                "configured": robot_agent.configured,
                "message": user_message,
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "pending_action": None,
                "api_attempted": True,
                "api_provider": robot_agent.mode,
                "failure_category": "model_stream_failure",
                "retryable": True,
            }
            result = robot_agent.enrich_result(result, route, knowledge)
            result["object_memory"] = conversation_memory.remember(
                command.conversation_id, command.message, result, route=route
            )
            yield json.dumps({"type": "result", **result}, ensure_ascii=False) + "\n"

