"""Small, side-effect-free helpers shared by the agent service workflow.

Keeping these operations outside ``agent_service.py`` makes project context
resolution testable without constructing the network/model service and gives
future CAD/project modules a stable seam to reuse.
"""

from __future__ import annotations

from copy import deepcopy

from typing import Any


def project_id_from_route(
    route: dict[str, Any], *, fresh_design_request: bool = False
) -> str | None:
    if fresh_design_request:
        return None
    selected_project_id = str(route.get("selected_project_id") or "").strip()
    if selected_project_id:
        return selected_project_id
    for memory_key in ("object_memory", "retrieved_memory"):
        memory = route.get(memory_key)
        if not isinstance(memory, dict):
            continue
        objects = memory.get("objects")
        projects = objects.get("project") if isinstance(objects, dict) else None
        if isinstance(projects, list) and projects:
            first = projects[0]
            if isinstance(first, dict) and first.get("id"):
                return str(first["id"])
    return None


def conversation_id_from_route(route: dict[str, Any]) -> str | None:
    for memory_key in ("object_memory", "retrieved_memory"):
        memory = route.get(memory_key)
        if isinstance(memory, dict) and memory.get("conversation_id"):
            return str(memory["conversation_id"])
    return None


def merge_design_requirements(
    project: dict[str, Any], route: dict[str, Any]
) -> dict[str, Any]:
    requirements = dict(project.get("requirements") or {})
    # Persisted projects are authoritative. Conversation memory is retrieval
    # context, not an additional source of confirmed construction parameters.
    if project.get("id"):
        shape = requirements.get("shape") or requirements.get("drawing_type")
        if shape and "shape" not in requirements:
            requirements["shape"] = shape
        return deepcopy(requirements)
    retrieved = route.get("retrieved_memory")
    confirmed = (
        retrieved.get("confirmed_requirements")
        if isinstance(retrieved, dict)
        else None
    )
    if not isinstance(confirmed, dict):
        memory = route.get("object_memory")
        profile = (
            memory.get("requirement_profile")
            if isinstance(memory, dict)
            else None
        )
        confirmed = profile.get("confirmed") if isinstance(profile, dict) else None
    if isinstance(confirmed, dict):
        # 记忆 confirmed 只补项目缺失的键：项目（用户最新确认/修改）优先，
        # 避免旧快照浅覆盖把用户刚改过的参数静默回滚。
        for key, value in confirmed.items():
            if key not in requirements or not requirements[key]:
                requirements[key] = deepcopy(value)
    shape = requirements.get("shape") or requirements.get("drawing_type")
    if shape and "shape" not in requirements:
        requirements["shape"] = shape
    return requirements


def template_geometry_count(template: str) -> int:
    return {
        "room": 1,
        "two_rooms": 2,
        "corridor": 1,
        "basketball": 19,
        "basketball_court": 19,
        "badminton": 9,
        "badminton_court": 9,
        "parking": 1,
        "parking_space": 1,
        "parking_lot": 7,
        "warehouse": 6,
        "grid": 10,
        "foundation": 1,
    }.get(template, 1)
