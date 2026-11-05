from __future__ import annotations

import re
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .agent_skills import layer_drawing_paths
from .agent_skills import recommend_recovery
from .cad_revision import verify_variant_revision_for_planning
from .creative_projects import get_creative_project_store
from .drawing_store import cad_directory, resolve_drawing
from .drawing_versions import drawing_versions
from .mission_ledger import mission_ledger
from .ros_adapter import ros_adapter
from .state import robot_state
from .trajectory_comparison import compare_trajectories
from .route_optimization_comparison import (
    attach_ros2_result,
    build_route_optimization_comparison,
)
from .task_store import agent_tasks
from .spatial_partition import (
    build_spatial_partition,
    next_partition_segment,
    next_partition_zone,
)


def prepare_project_plan(project_id: str) -> dict[str, Any]:
    project_store = get_creative_project_store()
    project = project_store.get(project_id)
    if project is None:
        return {"ok": False, "message": "创意项目不存在"}
    selected_id = project.get("selected_variant_id")
    variant = next(
        (item for item in project.get("variants", []) if item.get("id") == selected_id),
        None,
    )
    if variant is None:
        return {"ok": False, "message": "请先选择候选设计方案"}
    assessment = variant.get("assessment") or {}
    feasibility = assessment.get("feasibility") or {}
    if feasibility.get("ok") is not True:
        return {"ok": False, "message": "选中方案未通过设计可制造性检查"}
    project_scale = assessment.get("project_scale") or {}
    partition = None
    active_zone = None
    active_segment = None
    if project_scale.get("requires_partitioning") is True:
        partition = variant.get("spatial_partition")
        if not isinstance(partition, dict) or partition.get("status") != "ready":
            partition = build_spatial_partition(
                str(variant.get("id") or ""),
                list(variant.get("geometries") or []),
                list(variant.get("logical_objects") or []),
                dict(variant.get("topology") or {}),
                project_scale,
            )
            stored = project_store.set_variant_partition(
                project_id, str(variant.get("id") or ""), partition
            )
            if stored is None:
                return {
                    "ok": False,
                    "code": "project_partitioning_failed",
                    "message": "大型图纸分区校验未通过，已保留完整总图。",
                    "project_id": project_id,
                }
        active_zone = next_partition_zone(partition)
        if active_zone is None:
            return {
                "ok": True,
                "code": "project_partitioning_completed",
                "message": "所有施工区均已完成。",
                "project_id": project_id,
                "spatial_partition": partition,
            }
        active_segment = next_partition_segment(active_zone)
        if active_segment is None:
            return {
                "ok": False,
                "code": "partition_segment_missing",
                "message": "当前施工区没有可规划的分段，请重新生成分区。",
                "project_id": project_id,
            }
    source_revision = verify_variant_revision_for_planning(variant)
    if source_revision.get("ok") is not True:
        return {
            "ok": False,
            "message": str(source_revision.get("message") or "候选版本验证失败"),
            "source_revision": source_revision,
        }

    planning_geometries = (
        list(active_segment.get("global_geometries") or [])
        if isinstance(active_segment, dict)
        else list(variant["geometries"])
    )
    route_comparison = build_route_optimization_comparison(
        planning_geometries,
        start_point_m=[
            float(robot_state.robot_pose.get("x", 0.0)),
            float(robot_state.robot_pose.get("y", 0.0)),
        ],
    )
    existing = project.get("planning") or {}
    file_name = str(existing.get("file_name") or "")
    existing_source = existing.get("source_revision")
    active_zone_id = str((active_zone or {}).get("id") or "")
    active_segment_id = str((active_segment or {}).get("id") or "")
    source_matches = (
        isinstance(existing_source, dict)
        and existing_source.get("sha256") == source_revision.get("sha256")
    )
    needs_new_drawing = (
        existing.get("variant_id") != selected_id
        or str(existing.get("partition_zone_id") or "") != active_zone_id
        or str(existing.get("partition_segment_id") or "") != active_segment_id
        or not source_matches
        or resolve_drawing(file_name) is None
    )
    payload: dict[str, Any] | None = None
    requested_name = ""
    change_summary = ""
    if needs_new_drawing:
        printer = _project_printer(project)
        payload = {
            "schema_version": "1.0",
            "unit": "mm",
            "creative_project_id": project_id,
            "creative_variant_id": selected_id,
            "cad_source_revision": source_revision,
            **layer_drawing_paths(planning_geometries, printer),
        }
        if isinstance(active_zone, dict):
            local_frame = dict(active_zone.get("local_frame") or {})
            local_geometries = (
                list(active_segment.get("local_geometries") or [])
                if isinstance(active_segment, dict) else []
            )
            payload["coordinate_contract"] = {
                "schema": "cad.local-execution.v1",
                "canonical_space": "zone_local_mm",
                "planner_input_space": "map_mm",
                "projection_verified": True,
                "local_frame": local_frame,
                "local_lines": layer_drawing_paths(
                    local_geometries, printer
                )["lines"],
            }
            payload["spatial_partition"] = {
                "schema": "cad.partition-zone.v1",
                "zone_id": active_zone["id"],
                "sequence": active_zone["sequence"],
                "bounds_m": active_zone["bounds_m"],
                "source_geometry_ids": active_zone["source_geometry_ids"],
                "execution_segment_id": active_segment_id,
                "execution_segment_sequence": (active_segment or {}).get("sequence"),
                "continuity_link_ids": sorted({
                    link_id
                    for geometry in planning_geometries
                    for link_id in (
                        (geometry.get("partition_continuity") or {}).get(
                            "incoming_link_ids", []
                        )
                        + (geometry.get("partition_continuity") or {}).get(
                            "outgoing_link_ids", []
                        )
                    )
                }),
            }
        stem = re.sub(r"[^\w\-\u4e00-\u9fff]", "_", str(project["name"])).strip("_")
        zone_suffix = f"_{active_zone_id}" if active_zone_id else ""
        segment_suffix = f"_s{(active_segment or {}).get('sequence', 1):04d}" if active_segment_id else ""
        requested_name = (
            f"{stem or 'creative_project'}{zone_suffix}{segment_suffix}.json"
        )
        change_summary = (
            f"施工区 {active_zone_id} 分段 {active_segment_id}：{variant['name']}"
            if active_zone_id else f"选中方案：{variant['name']}"
        )
    else:
        version = existing.get("drawing_version")

    def build_planning(version_item: dict[str, Any]) -> dict[str, Any]:
        current_file_name = str(version_item["file_name"])
        submitted_now = ros_adapter.prepare_mission(current_file_name)
        snapshot = {
            "variant_id": selected_id,
            "file_name": current_file_name,
            "drawing_version": deepcopy(version_item),
            "source_revision": source_revision,
            "stage": robot_state.mission_stage if submitted_now else "planning_failed",
            "submitted": submitted_now,
            "validation": {},
            "summary": {},
            "quality": {},
            "error": "" if submitted_now else robot_state.mission_error,
            "preview_only": True,
            "execution_requires_confirmation": True,
            "route_optimization_comparison": route_comparison,
        }
        if isinstance(active_zone, dict):
            snapshot["partition_zone_id"] = active_zone["id"]
            snapshot["partition_segment_id"] = active_segment_id
            snapshot["partition_zone"] = {
                key: deepcopy(active_zone[key])
                for key in (
                    "id", "row", "column", "sequence", "bounds_m",
                    "source_geometry_ids", "progress",
                )
            }
            snapshot["spatial_partition_summary"] = deepcopy(
                (partition or {}).get("summary") or {}
            )
            snapshot["local_frame"] = deepcopy(active_zone.get("local_frame") or {})
            snapshot["partition_segment"] = {
                key: deepcopy((active_segment or {})[key])
                for key in (
                    "id", "sequence", "geometry_ids", "source_geometry_ids",
                    "printing_length_m", "progress",
                )
                if key in (active_segment or {})
            }
        return snapshot

    def partition_update_for(planning_snapshot: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(active_zone, dict):
            return None
        return {
            "variant_id": str(selected_id),
            "zone_id": str(active_zone["id"]),
            "segment_id": active_segment_id,
            "status": "planning" if planning_snapshot.get("submitted") else "failed",
            "updates": {
                "file_name": planning_snapshot["file_name"],
                "drawing_version": planning_snapshot["drawing_version"],
            },
        }

    if needs_new_drawing:
        assert isinstance(payload, dict)
        holder: dict[str, Any] = {}

        def planning_factory(version_item: dict[str, Any]) -> dict[str, Any]:
            planning_snapshot = build_planning(version_item)
            holder["partition_update"] = partition_update_for(planning_snapshot)
            return planning_snapshot

        # The partition update depends on the generated version.  Pass a
        # mapping whose nested values are populated by the factory before the
        # transaction applies it.
        partition_proxy: dict[str, Any] | None = {} if isinstance(active_zone, dict) else None

        def transactional_factory(version_item: dict[str, Any]) -> dict[str, Any]:
            planning_snapshot = planning_factory(version_item)
            if partition_proxy is not None:
                partition_proxy.update(holder["partition_update"])
            return planning_snapshot

        bundle = drawing_versions.save_project_planning(
            cad_directory(), requested_name, payload, "creative_project", change_summary,
            project_store=project_store,
            project_id=project_id,
            planning_factory=transactional_factory,
            partition_update=partition_proxy,
        )
        version = bundle["drawing_version"]
        planning = bundle["planning"]
    else:
        planning = build_planning(version)
        stored = project_store.set_planning_with_partition(
            project_id, planning, partition_update_for(planning)
        )
        if stored is None:
            return {"ok": False, "message": "项目规划状态保存失败", "project_id": project_id}
    submitted = planning.get("submitted") is True
    return {
        "ok": submitted,
        "message": (
            f"已提交施工区 {active_zone_id} 分段 "
            f"{active_segment_id} 的 ROS2 规划预览"
            if submitted and active_zone_id
            else "已提交 ROS2 规划预览"
            if submitted else robot_state.mission_error
        ),
        "project_id": project_id,
        "planning": planning,
    }


def refresh_project_plan(project_id: str) -> dict[str, Any]:
    project = get_creative_project_store().get(project_id)
    if project is None:
        return {"ok": False, "message": "创意项目不存在"}
    planning = dict(project.get("planning") or {})
    selected_id = project.get("selected_variant_id")
    variant = next(
        (item for item in project.get("variants", []) if item.get("id") == selected_id),
        None,
    )
    source_revision = verify_variant_revision_for_planning(variant)
    planned_source = planning.get("source_revision")
    source_matches = (
        source_revision.get("ok") is True
        and isinstance(planned_source, dict)
        and planning.get("variant_id") == selected_id
        and planned_source.get("sha256") == source_revision.get("sha256")
    )
    if not source_matches:
        planning.update({
            "stage": "planning_failed",
            "validation": {"ok": False, "reason": "candidate_revision_mismatch"},
            "error": "候选方案已变化或规划版本过旧，请重新生成路径规划",
            "ready_for_confirmation": False,
            "current_source_revision": source_revision,
        })
        get_creative_project_store().set_planning(project_id, planning)
        return {
            "ok": False,
            "message": planning["error"],
            "project_id": project_id,
            "planning": planning,
        }
    file_name = str(planning.get("file_name") or "")
    if not file_name:
        return {"ok": False, "message": "项目尚未提交规划"}
    if robot_state.mission_file != file_name:
        return {"ok": False, "message": "当前 ROS2 规划结果不属于该项目", "planning": planning}

    stage = robot_state.mission_stage
    planning.update({
        "stage": stage,
        "validation": dict(robot_state.mission_validation),
        "summary": dict(robot_state.mission_summary),
        "quality": dict(robot_state.mission_quality),
        "error": robot_state.mission_error,
        "ready_for_confirmation": (
            stage == "ready" and robot_state.mission_validation.get("ok") is True
        ),
    })
    comparison = planning.get("route_optimization_comparison")
    if isinstance(comparison, dict) and robot_state.mission_summary:
        planning["route_optimization_comparison"] = attach_ros2_result(
            comparison, dict(robot_state.mission_summary)
        )
    partition_zone_id = str(planning.get("partition_zone_id") or "")
    partition_segment_id = str(planning.get("partition_segment_id") or "")
    if partition_zone_id:
        zone_status = _partition_status_for_stage(stage)
        update_arguments = {
            "planning": {
                "stage": stage,
                "validation": dict(robot_state.mission_validation),
                "quality": dict(robot_state.mission_quality),
                "error": robot_state.mission_error,
            },
        }
        if partition_segment_id:
            get_creative_project_store().update_variant_partition_segment(
                project_id,
                str(selected_id),
                partition_zone_id,
                partition_segment_id,
                zone_status,
                **update_arguments,
            )
        else:
            get_creative_project_store().update_variant_partition_zone(
                project_id,
                str(selected_id),
                partition_zone_id,
                zone_status,
                **update_arguments,
            )
        refreshed_project = get_creative_project_store().get(project_id) or {}
        refreshed_variant = next(
            (
                item for item in refreshed_project.get("variants", [])
                if item.get("id") == selected_id
            ),
            {},
        )
        planning["spatial_partition_summary"] = deepcopy(
            (refreshed_variant.get("spatial_partition") or {}).get("summary") or {}
        )
    get_creative_project_store().set_planning(project_id, planning)
    return {"ok": True, "project_id": project_id, "planning": planning}


def ensure_project_plan_ready(project_id: str) -> dict[str, Any]:
    """Restore this project's persisted plan into the single ROS planning slot.

    A project may remain ``planning_ready`` after another preview (or a status
    reset) replaces the process-wide ROS planning state.  Execution must not
    trust the persisted snapshot blindly, but it should reactivate and verify
    that exact drawing instead of telling the user to plan it again manually.
    """
    refreshed = refresh_project_plan(project_id)
    planning = refreshed.get("planning")
    if (
        refreshed.get("ok") is True
        and isinstance(planning, dict)
        and planning.get("ready_for_confirmation") is True
    ):
        return refreshed

    project = get_creative_project_store().get(project_id)
    if project is None:
        return {"ok": False, "code": "project_missing", "message": "创意项目不存在"}
    planning = dict(project.get("planning") or {})
    selected_id = project.get("selected_variant_id")
    variant = next(
        (item for item in project.get("variants", []) if item.get("id") == selected_id),
        None,
    )
    source_revision = verify_variant_revision_for_planning(variant)
    planned_source = planning.get("source_revision")
    if (
        source_revision.get("ok") is not True
        or not isinstance(planned_source, dict)
        or planning.get("variant_id") != selected_id
        or planned_source.get("sha256") != source_revision.get("sha256")
    ):
        return refreshed

    file_name = str(planning.get("file_name") or "")
    if not file_name or resolve_drawing(file_name) is None:
        return {
            "ok": False,
            "code": "project_plan_file_missing",
            "message": "当前项目的规划图纸不存在，请重新生成路线。",
            "project_id": project_id,
            "planning": planning,
        }
    if robot_state.mission_running:
        return {
            "ok": False,
            "code": "mission_already_running",
            "message": "当前已有任务正在执行，不能切换到另一项目的规划。",
            "project_id": project_id,
            "planning": planning,
        }

    submitted = ros_adapter.prepare_mission(file_name)
    if not submitted:
        return {
            "ok": False,
            "code": "project_plan_recheck_failed",
            "message": robot_state.mission_error or "当前项目路径重新检查失败。",
            "project_id": project_id,
            "planning": planning,
        }

    planning.update({
        "stage": robot_state.mission_stage,
        "submitted": True,
        "validation": dict(robot_state.mission_validation),
        "summary": dict(robot_state.mission_summary),
        "quality": dict(robot_state.mission_quality),
        "error": robot_state.mission_error,
        "ready_for_confirmation": (
            robot_state.mission_stage == "ready"
            and robot_state.mission_validation.get("ok") is True
        ),
    })
    get_creative_project_store().set_planning(project_id, planning)
    if planning["ready_for_confirmation"]:
        return {
            "ok": True,
            "code": "project_plan_restored",
            "message": "已恢复并通过当前项目的路径检查。",
            "project_id": project_id,
            "planning": planning,
        }
    return {
        "ok": True,
        "code": "project_plan_rechecking",
        "message": "正在恢复当前项目并重新检查路径，通过后将自动进入执行确认。",
        "project_id": project_id,
        "planning": planning,
        "retryable": True,
    }


def mark_project_execution_pending(project_id: str, action_id: str) -> dict[str, Any] | None:
    project = get_creative_project_store().get(project_id)
    if project is None:
        return None
    planning = project.get("planning") or {}
    zone_id = str(planning.get("partition_zone_id") or "")
    segment_id = str(planning.get("partition_segment_id") or "")
    variant_id = str(project.get("selected_variant_id") or "")
    if zone_id and variant_id:
        if segment_id:
            get_creative_project_store().update_variant_partition_segment(
                project_id,
                variant_id,
                zone_id,
                segment_id,
                "pending_confirmation",
                action_id=action_id,
            )
        else:
            get_creative_project_store().update_variant_partition_zone(
                project_id,
                variant_id,
                zone_id,
                "pending_confirmation",
                action_id=action_id,
            )
    return get_creative_project_store().set_execution(project_id, {
        "stage": "pending_confirmation",
        "action_id": action_id,
        "file_name": planning.get("file_name"),
        "mission_id": robot_state.mission_ledger_id,
        "auto_resume_allowed": False,
        **({"partition_zone_id": zone_id} if zone_id else {}),
        **({"partition_segment_id": segment_id} if segment_id else {}),
    })


def stop_project_before_deletion(project_id: str) -> dict[str, Any]:
    """Move a non-running execution to a terminal state before deletion."""
    project = get_creative_project_store().get(project_id)
    if project is None:
        return {"ok": False, "message": "项目不存在"}

    status = str(project.get("status") or "")
    if status == "executing":
        return {
            "ok": False,
            "message": "项目正在执行，不能直接删除；请先暂停或终止任务。",
        }
    if status not in {"pending_execution", "paused"}:
        return {"ok": True, "project": project}

    execution = dict(project.get("execution") or {})
    planning = dict(project.get("planning") or {})
    file_name = str(execution.get("file_name") or planning.get("file_name") or "")

    if status == "pending_execution":
        action_id = str(execution.get("action_id") or "")
        pending = agent_tasks.get(action_id) if action_id else None
        if pending and pending.get("state") == "pending_confirmation":
            agent_tasks.transition(
                action_id,
                "cancelled",
                "项目删除前已取消待确认任务",
                result={"ok": True, "message": "项目已删除"},
            )

    owns_runtime_mission = bool(
        file_name and file_name == str(robot_state.mission_file or "")
    )
    if status == "paused" and owns_runtime_mission and (
        robot_state.mission_running or robot_state.mission_paused
    ):
        if not robot_state.mission_paused:
            return {
                "ok": False,
                "message": "项目任务仍在运动，不能直接删除；请先暂停或终止任务。",
            }
        if not ros_adapter.control_mission_action("cancel", file_name):
            return {
                "ok": False,
                "message": "暂停任务取消失败，项目未删除；请检查小车连接后重试。",
            }

    cancelled = get_creative_project_store().set_execution(
        project_id,
        {
            **execution,
            "stage": "cancelled",
            "file_name": file_name or execution.get("file_name"),
            "running": False,
            "paused": False,
            "auto_resume_allowed": False,
            "cancel_reason": "project_deleted",
        },
    )
    if cancelled is None:
        return {"ok": False, "message": "项目状态更新失败，项目未删除。"}
    return {"ok": True, "project": cancelled}


def exit_project_plan(project_id: str) -> dict[str, Any]:
    """Discard a prepared ROS2 preview and return its candidate to editing."""
    project = get_creative_project_store().get(project_id)
    if project is None:
        return {"ok": False, "message": "创意项目不存在"}

    status = str(project.get("status") or "")
    allowed_statuses = {
        "planning", "planning_ready", "planning_failed", "pending_execution",
    }
    if status not in allowed_statuses:
        if status in {"executing", "paused"} or robot_state.mission_running:
            return {
                "ok": False,
                "message": "小车任务已进入执行阶段，请使用暂停或终止任务，不能直接退出规划。",
            }
        return {"ok": False, "message": "当前项目没有可退出的 ROS2 规划。"}

    planning = dict(project.get("planning") or {})
    execution = dict(project.get("execution") or {})
    file_name = str(planning.get("file_name") or execution.get("file_name") or "")
    selected_variant_id = str(project.get("selected_variant_id") or "")
    if not selected_variant_id:
        return {"ok": False, "message": "当前规划没有绑定候选方案，无法返回修改。"}

    owns_runtime_mission = bool(
        file_name and file_name == str(robot_state.mission_file or "")
    )
    if owns_runtime_mission and (robot_state.mission_running or robot_state.mission_paused):
        return {
            "ok": False,
            "message": "小车任务已经启动，请先在任务页终止任务，再继续修改图纸。",
        }

    if owns_runtime_mission and status != "planning_failed":
        if not ros_adapter.control_mission_action("cancel", file_name):
            return {
                "ok": False,
                "message": "ROS2 规划预览取消失败，项目仍保持原状态，请检查小车连接后重试。",
            }

    if status == "pending_execution":
        action_id = str(execution.get("action_id") or "")
        pending = agent_tasks.get(action_id) if action_id else None
        if pending and pending.get("state") == "pending_confirmation":
            agent_tasks.transition(
                action_id,
                "cancelled",
                "用户退出 ROS2 规划",
                result={"ok": True, "message": "已退出当前 ROS2 规划"},
            )
        project = get_creative_project_store().set_execution(
            project_id,
            {
                **execution,
                "stage": "confirmation_cancelled",
                "running": False,
                "paused": False,
                "auto_resume_allowed": False,
                "cancel_reason": "planning_exited_by_user",
            },
        )
        if project is None:
            return {"ok": False, "message": "待执行确认取消失败，请稍后重试。"}

    current = get_creative_project_store().get(project_id)
    if current is None:
        return {"ok": False, "message": "创意项目不存在"}
    if str(current.get("status") or "") != "planning_failed":
        cancelled_planning = {
            **dict(current.get("planning") or planning),
            "stage": "cancelled",
            "ready_for_confirmation": False,
            "cancel_reason": "planning_exited_by_user",
        }
        current = get_creative_project_store().set_planning(project_id, cancelled_planning)
        if current is None:
            return {"ok": False, "message": "规划状态清理失败，请稍后重试。"}

    updated = get_creative_project_store().begin_design_iteration(
        project_id, selected_variant_id
    )
    if updated is None:
        return {"ok": False, "message": "规划已取消，但项目未能返回设计状态。"}
    return {
        "ok": True,
        "message": "已退出当前 ROS2 规划，候选图纸已保留，可以继续修改。",
        "project": updated,
        "planning_cancelled": True,
    }


def refresh_project_execution(project_id: str) -> dict[str, Any]:
    project = get_creative_project_store().get(project_id)
    if project is None:
        return {"ok": False, "message": "创意项目不存在"}
    planning = project.get("planning") or {}
    file_name = str(planning.get("file_name") or "")
    if not file_name:
        return {"ok": False, "message": "项目尚未完成规划"}
    if robot_state.mission_file != file_name:
        return {"ok": False, "message": "当前执行任务不属于该项目"}

    mission_id = robot_state.mission_ledger_id
    mission = mission_ledger.get(mission_id) if mission_id else None
    previous_execution = dict(project.get("execution") or {})
    stage = robot_state.mission_stage
    if project.get("status") == "pending_execution" and stage == "ready":
        stage = "pending_confirmation"
    total = int(robot_state.mission_total or 0)
    completed = int(robot_state.mission_completed or 0)
    execution = {
        **previous_execution,
        "stage": stage,
        "file_name": file_name,
        "mission_id": mission_id or previous_execution.get("mission_id"),
        "running": robot_state.mission_running,
        "paused": robot_state.mission_paused,
        "completed_segments": completed,
        "total_segments": total,
        "progress": round(completed / total, 4) if total > 0 else 0.0,
        "current_segment_id": robot_state.mission_current_id,
        "last_verified_segment_id": robot_state.mission_last_verified_id,
        "checkpoint": dict(robot_state.mission_checkpoint),
        "segment_verification": dict(robot_state.mission_segment_verification),
        "oscillation_detected": robot_state.oscillation_detected,
        "oscillation_event_count": len((mission or {}).get("oscillation_events", [])),
        "error": robot_state.mission_error,
        "ledger_state": (mission or {}).get("state"),
        "auto_resume_allowed": False,
    }
    if stage == "paused":
        execution["recovery_assessment"] = _current_mission_resume_assessment(
            file_name, execution
        )
    else:
        execution.pop("recovery_assessment", None)
    zone_id = str(planning.get("partition_zone_id") or "")
    segment_id = str(planning.get("partition_segment_id") or "")
    variant_id = str(project.get("selected_variant_id") or "")
    if zone_id and variant_id:
        zone_status = _partition_status_for_stage(stage)
        update_arguments = {
            "geometry_completed": completed,
            "execution": {
                "stage": stage,
                "mission_id": mission_id,
                "completed_segments": completed,
                "total_segments": total,
                "last_verified_segment_id": robot_state.mission_last_verified_id,
                "error": robot_state.mission_error,
            },
        }
        if segment_id:
            updated = get_creative_project_store().update_variant_partition_segment(
                project_id,
                variant_id,
                zone_id,
                segment_id,
                zone_status,
                **update_arguments,
            )
        else:
            updated = get_creative_project_store().update_variant_partition_zone(
                project_id,
                variant_id,
                zone_id,
                zone_status,
                **update_arguments,
            )
        selected_variant = next(
            (
                item for item in (updated or {}).get("variants", [])
                if item.get("id") == variant_id
            ),
            {},
        )
        partition_summary = (
            selected_variant.get("spatial_partition") or {}
        ).get("summary") or {}
        selected_partition = selected_variant.get("spatial_partition") or {}
        selected_zone = next(
            (
                item for item in selected_partition.get("zones", [])
                if item.get("id") == zone_id
            ),
            {},
        )
        execution["partition_zone_id"] = zone_id
        if segment_id:
            execution["partition_segment_id"] = segment_id
        execution["spatial_partition_summary"] = deepcopy(partition_summary)
        if stage == "completed" and partition_summary.get("all_completed") is not True:
            if selected_zone.get("status") == "completed":
                execution["stage"] = "zone_completed"
                execution["next_zone_required"] = True
            else:
                execution["stage"] = "segment_completed"
                execution["next_segment_required"] = True
    get_creative_project_store().set_execution(project_id, execution)
    return {"ok": True, "project_id": project_id, "execution": execution}


def _partition_status_for_stage(stage: str) -> str:
    return {
        "ready": "planned",
        "pending_confirmation": "pending_confirmation",
        "executing": "executing",
        "paused": "paused",
        "completed": "completed",
        "failed": "failed",
        "execution_failed": "failed",
        "planning_failed": "failed",
        "cancelled": "cancelled",
        "interrupted": "failed",
    }.get(stage, "planning")


def project_recovery_assessment(project_id: str) -> dict[str, Any]:
    refreshed = refresh_project_execution(project_id)
    if not refreshed.get("ok"):
        return refreshed
    execution = dict(refreshed["execution"])
    recommendation = _current_mission_resume_assessment(
        str(execution.get("file_name") or ""), execution
    )
    execution["recovery_assessment"] = recommendation
    get_creative_project_store().set_execution(project_id, execution)
    return {
        "ok": True,
        "project_id": project_id,
        "execution": execution,
        "recovery": recommendation,
    }


def _current_mission_resume_assessment(
    file_name: str, execution: dict[str, Any]
) -> dict[str, Any]:
    """Assess whether the paused runtime mission can continue without replanning."""
    snapshot = robot_state.snapshot()
    recommendation = recommend_recovery(snapshot)
    reasons: list[str] = []
    owns_runtime_mission = bool(
        file_name and file_name == str(snapshot.get("mission_file") or "")
    )
    if not owns_runtime_mission:
        reasons.append("当前暂停任务与项目图纸不一致")
    if snapshot.get("mission_running") is not True or snapshot.get("mission_paused") is not True:
        reasons.append("原任务已不在可续跑的暂停状态")
    if snapshot.get("emergency_stopped") is True:
        reasons.append("急停仍未解除")
    if snapshot.get("control_ready") is not True:
        reasons.append("小车移动控制权尚未恢复")
    if snapshot.get("localization_valid") is not True:
        reasons.append("定位尚未恢复")
    if snapshot.get("mission_required_printers") and snapshot.get("printer_ready") is not True:
        reasons.append("任务所需喷码机尚未就绪")
    if snapshot.get("oscillation_detected") is True:
        reasons.append("检测到轨迹振荡，需要重新规划")
    mission_error = str(snapshot.get("mission_error") or "").strip()
    emergency_error = (
        "emergency stop" in mission_error.lower() or "急停" in mission_error
    )
    if mission_error and not (emergency_error and snapshot.get("emergency_stopped") is False):
        reasons.append(mission_error)

    reasons = list(dict.fromkeys(reasons))
    can_resume = not reasons
    return {
        **recommendation,
        "ok": can_resume,
        "can_resume_current_mission": can_resume,
        "resume_from_verified_segment": execution.get("last_verified_segment_id"),
        "resume_requires_replanning": not can_resume,
        "resume_requires_user_confirmation": True,
        "auto_resume_allowed": False,
        "reasons": reasons,
        "recommended_actions": (
            ["确认现场安全后继续当前任务"]
            if can_resume
            else recommendation.get("recommended_actions") or ["处理异常后重新评估"]
        ),
        "assessment_updated_at": datetime.now(timezone.utc).isoformat(),
    }


def resume_project_execution(project_id: str) -> dict[str, Any]:
    """Resume the existing paused mission after a fresh deterministic safety check."""
    project = get_creative_project_store().get(project_id)
    if project is None:
        return {"ok": False, "message": "创意项目不存在"}
    if str(project.get("status") or "") != "paused":
        return {"ok": False, "message": "只有已暂停的项目可以继续当前任务"}

    execution = dict(project.get("execution") or {})
    planning = dict(project.get("planning") or {})
    file_name = str(execution.get("file_name") or planning.get("file_name") or "")
    assessment = _current_mission_resume_assessment(file_name, execution)
    if assessment.get("can_resume_current_mission") is not True:
        execution["recovery_assessment"] = assessment
        get_creative_project_store().set_execution(project_id, execution)
        return {
            "ok": False,
            "code": "project_resume_not_ready",
            "message": "当前任务仍不满足继续条件：" + "；".join(assessment["reasons"]),
            "recovery": assessment,
        }

    if not ros_adapter.control_mission_action("resume", file_name):
        return {
            "ok": False,
            "code": "project_resume_failed",
            "message": robot_state.mission_error or "小车未接受继续任务指令",
            "recovery": assessment,
        }

    refreshed = refresh_project_execution(project_id)
    if not refreshed.get("ok"):
        return refreshed
    return {
        "ok": True,
        "message": "已继续当前任务，正在从暂停位置恢复执行。",
        "project_id": project_id,
        "execution": refreshed["execution"],
    }


def prepare_project_recovery(project_id: str) -> dict[str, Any]:
    project = get_creative_project_store().get(project_id)
    if project is None:
        return {"ok": False, "message": "创意项目不存在"}
    selected_id = project.get("selected_variant_id")
    variant = next(
        (
            item for item in project.get("variants", [])
            if item.get("id") == selected_id
        ),
        None,
    )
    source_revision = verify_variant_revision_for_planning(variant)
    if source_revision.get("ok") is not True:
        return {
            "ok": False,
            "code": "recovery_source_revision_invalid",
            "message": str(
                source_revision.get("message") or "恢复规划的候选版本验证失败"
            ),
            "source_revision": source_revision,
        }
    execution = project.get("execution") or {}
    mission_id = execution.get("mission_id") or robot_state.mission_ledger_id
    mission = mission_ledger.get(str(mission_id)) if mission_id else None
    if mission is None:
        return {"ok": False, "message": "没有可恢复的任务账本"}
    project_status = str(project.get("status"))
    retrying_recovery = (
        project_status == "planning_failed"
        and isinstance((project.get("planning") or {}).get("recovery"), dict)
    )
    if (
        project_status not in {"paused", "execution_failed", "cancelled"}
        and not retrying_recovery
    ):
        return {"ok": False, "message": "只有暂停、失败或取消的项目可以创建恢复规划"}
    if robot_state.mission_running and not robot_state.mission_paused:
        return {"ok": False, "message": "任务仍在运动，必须先暂停或取消"}
    if robot_state.mission_paused:
        ros_adapter.control_mission_action("cancel", str(mission.get("file_name") or ""))

    ledger_segments = list(mission.get("segments") or [])
    planned_segments = list(mission.get("planned_segments") or [])
    remaining: list[dict[str, Any]] = []
    completed_printing_ids: list[Any] = []
    uncertain_segment_ids: list[Any] = []
    for index, segment in enumerate(planned_segments):
        ledger = ledger_segments[index] if index < len(ledger_segments) else {}
        if ledger.get("kind") != "printing":
            continue
        if ledger.get("state") == "completed":
            completed_printing_ids.append(segment.get("id"))
            continue
        if ledger.get("state") in {"executing", "failed", "interrupted"}:
            uncertain_segment_ids.append(segment.get("id"))
        item = dict(segment)
        item.pop("selected", None)
        remaining.append(item)
    if not remaining:
        return {"ok": False, "message": "没有未完成的喷墨路径，不能创建恢复任务"}

    project_name = re.sub(r"[^\w\-\u4e00-\u9fff]", "_", str(project["name"])).strip("_")
    payload = {
        "schema_version": "1.0",
        "unit": "mm",
        "creative_project_id": project_id,
        "recovery_of_mission_id": mission_id,
        "completed_printing_segment_ids": completed_printing_ids,
        "lines": remaining,
        "travel_policy": "regenerated_by_xline_ws3_planner",
    }
    project_store = get_creative_project_store()

    def recovery_planning_factory(version: dict[str, Any]) -> dict[str, Any]:
        file_name = str(version["file_name"])
        submitted = ros_adapter.prepare_mission(file_name)
        return {
            "variant_id": selected_id,
            "file_name": file_name,
            "drawing_version": version,
            "source_revision": source_revision,
            "stage": robot_state.mission_stage if submitted else "planning_failed",
            "submitted": submitted,
            "validation": {}, "summary": {}, "quality": {},
            "error": "" if submitted else robot_state.mission_error,
            "preview_only": True,
            "execution_requires_confirmation": True,
            "recovery": {
                "parent_mission_id": mission_id,
                "completed_printing_segment_ids": completed_printing_ids,
                "remaining_printing_segment_count": len(remaining),
                "uncertain_partial_segment_ids": uncertain_segment_ids,
                "manual_inspection_required": bool(uncertain_segment_ids),
                "travel_paths_regenerated": True,
                "auto_resume_allowed": False,
            },
        }

    bundle = drawing_versions.save_project_planning(
        cad_directory(), f"{project_name or 'creative_project'}_recovery.json",
        payload, "recovery", f"恢复任务，跳过 {len(completed_printing_ids)} 个已完成喷墨段",
        project_store=project_store,
        project_id=project_id,
        planning_factory=recovery_planning_factory,
    )
    planning = bundle["planning"]
    submitted = planning.get("submitted") is True
    stored = bundle.get("project")
    succeeded = submitted and isinstance(stored, dict)
    if not submitted:
        message = robot_state.mission_error or "恢复规划提交失败"
    elif stored is None:
        message = "恢复规划已提交，但项目状态保存失败，请刷新后重试"
    else:
        message = "恢复规划已提交；已完成喷墨段将跳过，疑似部分执行段需人工检查。"
    return {
        "ok": succeeded,
        "message": message,
        "project_id": project_id,
        "planning": planning,
    }


def build_project_acceptance_report(project_id: str) -> dict[str, Any]:
    project = get_creative_project_store().get(project_id)
    if project is None:
        return {"ok": False, "message": "创意项目不存在"}
    planning_file = str((project.get("planning") or {}).get("file_name") or "")
    if planning_file and robot_state.mission_file == planning_file:
        refresh_project_execution(project_id)
        project = get_creative_project_store().get(project_id) or project
    planning = dict(project.get("planning") or {})
    execution = dict(project.get("execution") or {})
    mission_id = execution.get("mission_id") or robot_state.mission_ledger_id
    mission = mission_ledger.get(str(mission_id)) if mission_id else None
    mission_report = (mission or {}).get("report")
    if not isinstance(mission_report, dict):
        mission_report = dict(robot_state.mission_report)
    trajectory = compare_trajectories(
        list((mission or {}).get("planned_paths", [])),
        list((mission or {}).get("actual_trace", [])),
    )
    final_state = str(execution.get("stage") or robot_state.mission_stage or "unknown")
    warnings: list[str] = []
    for warning in (
        mission_report.get("warnings", [])
        if isinstance(mission_report, dict) else []
    ):
        if isinstance(warning, str) and warning not in warnings:
            warnings.append(warning)
    if not trajectory.get("available"):
        warnings.append(str(trajectory.get("reason")))
    elif trajectory.get("maximum_deviation_m", 0) > 0.2:
        warnings.append("实际轨迹最大偏差超过 0.2 m")
    oscillations = len((mission or {}).get("oscillation_events", []))
    if oscillations:
        warnings.append(f"执行期间检测到 {oscillations} 次航向振荡")
    if final_state == "completed" and not warnings:
        verdict = "accepted"
    elif final_state == "completed":
        verdict = "accepted_with_warnings"
    elif final_state in {"failed", "interrupted", "execution_failed"}:
        verdict = "failed"
    else:
        verdict = "incomplete"
    selected = next(
        (item for item in project.get("variants", [])
         if item.get("id") == project.get("selected_variant_id")),
        None,
    )
    report = {
        "schema_version": "1.0",
        "project_id": project_id,
        "project_name": project.get("name"),
        "original_prompt": project.get("original_prompt"),
        "requirements": project.get("requirements", {}),
        "constraints": project.get("constraints", {}),
        "selected_variant": {
            "id": (selected or {}).get("id"),
            "name": (selected or {}).get("name"),
            "design_assessment": (selected or {}).get("assessment", {}),
        },
        "drawing_version": planning.get("drawing_version"),
        "planning_quality": planning.get("quality", {}),
        "execution": execution,
        "mission_report": mission_report,
        "trajectory_comparison": trajectory,
        "final_state": final_state,
        "verdict": verdict,
        "warnings": warnings,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    get_creative_project_store().set_report(project_id, report)
    return {"ok": True, "project_id": project_id, "report": report}


def _project_printer(project: dict[str, Any]) -> str:
    requirements = project.get("requirements") or {}
    printer = requirements.get("printer")
    if printer is None and isinstance(requirements.get("requirements"), dict):
        printer = requirements["requirements"].get("printer")
    # xline_ws3 currently creates only printer_center.
    return "center"


class CreativeProjectSynchronizer:
    def __init__(self, interval_seconds: float = 1.0) -> None:
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="creative-project-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None

    def sync_once(self) -> None:
        for project in get_creative_project_store().list(200):
            status = str(project.get("status", ""))
            execution = project.get("execution") or {}
            mission_id = str(execution.get("mission_id") or "")
            if status in {"executing", "paused"} and mission_id:
                mission = mission_ledger.get(mission_id)
                if mission and mission.get("state") in {"interrupted", "failed"}:
                    self._mark_interrupted_project(project, mission)
                    continue
            planning = project.get("planning") or {}
            file_name = str(planning.get("file_name") or "")
            if status == "pending_execution":
                action_id = str((project.get("execution") or {}).get("action_id") or "")
                task = agent_tasks.get(action_id) if action_id else None
                if task and task.get("state") in {"cancelled", "expired", "failed"}:
                    get_creative_project_store().set_execution(project["id"], {
                        **dict(project.get("execution") or {}),
                        "stage": "confirmation_cancelled",
                        "confirmation_state": task.get("state"),
                        "auto_resume_allowed": False,
                    })
                    continue
            if not file_name or robot_state.mission_file != file_name:
                continue
            if status in {"planning", "planning_ready", "planning_failed"}:
                refresh_project_plan(project["id"])
            if status in {"pending_execution", "executing", "paused", "execution_failed"}:
                refreshed = refresh_project_execution(project["id"])
                # Execution is a project lifecycle boundary. Generate the
                # report once the runtime reaches a terminal state so the
                # project does not require a second manual workflow.
                if refreshed.get("ok"):
                    current = get_creative_project_store().get(project["id"]) or {}
                    current_status = str(current.get("status", ""))
                    if current_status in {"completed", "execution_failed"} and not isinstance(
                        current.get("acceptance_report"), dict
                    ):
                        build_project_acceptance_report(project["id"])

    @staticmethod
    def _mark_interrupted_project(project: dict[str, Any], mission: dict[str, Any]) -> None:
        """Persist an interruption for recovery without issuing any motion command."""
        segments = mission.get("segments") if isinstance(mission.get("segments"), list) else []
        completed = [
            item for item in segments
            if isinstance(item, dict) and item.get("state") == "completed"
        ]
        last_verified = completed[-1].get("segment_id") if completed else None
        get_creative_project_store().set_execution(project["id"], {
            **dict(project.get("execution") or {}),
            "stage": "interrupted",
            "file_name": mission.get("file_name"),
            "mission_id": mission.get("id"),
            "completed_segments": len(completed),
            "total_segments": len(segments),
            "last_verified_segment_id": last_verified,
            "ledger_state": mission.get("state"),
            "error": "后端重启或运行中断，未自动恢复运动",
            "auto_resume_allowed": False,
            "recovery_required": True,
        })

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.sync_once()
            except Exception as error:
                robot_state.add_log(f"creative project sync failed: {error}")


creative_project_sync = CreativeProjectSynchronizer()
