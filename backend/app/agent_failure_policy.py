from __future__ import annotations

from typing import Any, Iterable


def classify_agent_failure(
    failure_codes: Iterable[str] | None,
    *,
    message: str = "",
) -> dict[str, Any]:
    codes = sorted({str(code).strip() for code in failure_codes or [] if str(code).strip()})
    code_set = set(codes)
    lowered = message.lower()

    if code_set & {"target_resolved", "required_parameters_present", "intent_grounding"}:
        category = "input_clarification"
        next_action = "ask_user"
        retryable = True
        user_action_required = True
        guidance = "请补充或点选明确的修改目标和缺失参数。"
    elif "version_binding" in code_set:
        category = "version_conflict"
        next_action = "refresh_and_replan"
        retryable = True
        user_action_required = False
        guidance = "当前计划绑定的图纸版本已变化，需要刷新最新候选并重新规划。"
    elif code_set & {"edit_plan", "declared_operation_effect", "preview_exact"}:
        category = "plan_mismatch"
        next_action = "replan"
        retryable = True
        user_action_required = False
        guidance = "修改结果与计划不一致，系统应基于原图重新生成计划。"
    elif code_set & {"geometry_preflight", "target_scope", "non_target_integrity"}:
        category = "geometry_validation"
        next_action = "manual_review"
        retryable = False
        user_action_required = True
        guidance = "几何校验或非目标保护未通过，已停止保存并保留原图。"
    elif "unsupported" in lowered or "不支持" in message:
        category = "unsupported_operation"
        next_action = "explain_capability"
        retryable = False
        user_action_required = True
        guidance = "当前 CAD 工具不支持该操作，需要调整指令或补充对应工具。"
    else:
        category = "execution_failure"
        next_action = "retry_later"
        retryable = True
        user_action_required = False
        guidance = "执行未完成，可在确认项目和版本未变化后重试。"

    return {
        "schema": "agent.failure-resolution.v1",
        "category": category,
        "failure_codes": codes,
        "next_action": next_action,
        "retryable": retryable,
        "user_action_required": user_action_required,
        "guidance": guidance,
    }
