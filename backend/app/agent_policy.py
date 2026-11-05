from __future__ import annotations

from typing import Any


BASE_AGENT_TOOLS = frozenset({
    "get_robot_status",
    "stop_robot",
    "drive_robot",
    "drive_sequence",
    "printer_spray",
})

ADVANCED_AGENT_TOOLS = frozenset({
    "get_robot_status",
    "stop_robot",
    "parameterize_design",
    "clarify_requirements",
    "create_creative_project",
    "update_creative_project",
    "select_design_variant",
    "prepare_project_plan",
    "refresh_project_plan",
    "refresh_project_execution",
    "assess_project_recovery",
    "prepare_project_recovery",
    "generate_project_report",
    "check_drawing_feasibility",
    "analyze_geometry_topology",
    "layer_drawing_paths",
    "recommend_recovery",
    "modify_drawing",
    "apply_cad_candidate_edit",
    "set_mission",
    "execute_prepared_mission",
    "control_ln150",
    "control_printer",
    "printer_spray",
})


def normalize_policy_mode(mode: str | None) -> str:
    return "advanced" if mode in {"advanced", "work"} else "base"


def agent_tool_allowed(name: str, mode: str | None) -> bool:
    normalized = normalize_policy_mode(mode)
    allowed = ADVANCED_AGENT_TOOLS if normalized == "advanced" else BASE_AGENT_TOOLS
    return name in allowed


def agent_tool_policy(name: str, mode: str | None) -> dict[str, Any]:
    normalized = normalize_policy_mode(mode)
    allowed = agent_tool_allowed(name, normalized)
    return {
        "allowed": allowed,
        "mode": normalized,
        "tool": name,
        "reason": (
            "工具在当前模式白名单中"
            if allowed
            else f"{normalized} 模式不允许调用 {name}"
        ),
    }
