from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

from .agent_skills import layer_drawing_paths
from .agent_skills import recommend_recovery
from .creative_projects import creative_projects
from .drawing_store import cad_directory, resolve_drawing
from .drawing_versions import drawing_versions
from .mission_ledger import mission_ledger
from .ros_adapter import ros_adapter
from .state import robot_state
from .trajectory_comparison import compare_trajectories
from .task_store import agent_tasks


def prepare_project_plan(project_id: str) -> dict[str, Any]:
    project = creative_projects.get(project_id)
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

    existing = project.get("planning") or {}
    file_name = str(existing.get("file_name") or "")
    if existing.get("variant_id") != selected_id or resolve_drawing(file_name) is None:
        printer = _project_printer(project)
        payload = {
            "schema_version": "1.0",
            "unit": "mm",
            "creative_project_id": project_id,
            "creative_variant_id": selected_id,
            **layer_drawing_paths(list(variant["geometries"]), printer),
        }
        stem = re.sub(r"[^\w\-\u4e00-\u9fff]", "_", str(project["name"])).strip("_")
        requested_name = f"{stem or 'creative_project'}.json"
        version = drawing_versions.save(
            cad_directory(), requested_name, payload, "creative_project", f"选中方案：{variant['name']}"
        )
        file_name = str(version["file_name"])
    else:
        version = existing.get("drawing_version")

    submitted = ros_adapter.prepare_mission(file_name)
    planning = {
        "variant_id": selected_id,
        "file_name": file_name,
        "drawing_version": version,
        "stage": robot_state.mission_stage if submitted else "planning_failed",
        "submitted": submitted,
        "validation": {},
        "summary": {},
        "quality": {},
        "error": "" if submitted else robot_state.mission_error,
        "preview_only": True,
        "execution_requires_confirmation": True,
    }
    creative_projects.set_planning(project_id, planning)
    return {
        "ok": submitted,
        "message": "已提交 ROS2 规划预览" if submitted else robot_state.mission_error,
        "project_id": project_id,
        "planning": planning,
    }


def refresh_project_plan(project_id: str) -> dict[str, Any]:
    project = creative_projects.get(project_id)
    if project is None:
        return {"ok": False, "message": "创意项目不存在"}
    planning = dict(project.get("planning") or {})
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
    creative_projects.set_planning(project_id, planning)
    return {"ok": True, "project_id": project_id, "planning": planning}


def mark_project_execution_pending(project_id: str, action_id: str) -> dict[str, Any] | None:
    project = creative_projects.get(project_id)
    if project is None:
        return None
    planning = project.get("planning") or {}
    return creative_projects.set_execution(project_id, {
        "stage": "pending_confirmation",
        "action_id": action_id,
        "file_name": planning.get("file_name"),
        "mission_id": robot_state.mission_ledger_id,
        "auto_resume_allowed": False,
    })


def refresh_project_execution(project_id: str) -> dict[str, Any]:
    project = creative_projects.get(project_id)
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
    creative_projects.set_execution(project_id, execution)
    return {"ok": True, "project_id": project_id, "execution": execution}


def project_recovery_assessment(project_id: str) -> dict[str, Any]:
    refreshed = refresh_project_execution(project_id)
    if not refreshed.get("ok"):
        return refreshed
    execution = dict(refreshed["execution"])
    recommendation = recommend_recovery(robot_state.snapshot())
    return {
        "ok": True,
        "project_id": project_id,
        "execution": execution,
        "recovery": {
            **recommendation,
            "resume_from_verified_segment": execution.get("last_verified_segment_id"),
            "resume_requires_replanning": True,
            "resume_requires_user_confirmation": True,
            "auto_resume_allowed": False,
        },
    }


def prepare_project_recovery(project_id: str) -> dict[str, Any]:
    project = creative_projects.get(project_id)
    if project is None:
        return {"ok": False, "message": "创意项目不存在"}
    execution = project.get("execution") or {}
    mission_id = execution.get("mission_id") or robot_state.mission_ledger_id
    mission = mission_ledger.get(str(mission_id)) if mission_id else None
    if mission is None:
        return {"ok": False, "message": "没有可恢复的任务账本"}
    if str(project.get("status")) not in {"paused", "execution_failed", "cancelled"}:
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
    version = drawing_versions.save(
        cad_directory(), f"{project_name or 'creative_project'}_recovery.json",
        payload, "recovery", f"恢复任务，跳过 {len(completed_printing_ids)} 个已完成喷墨段",
    )
    file_name = str(version["file_name"])
    submitted = ros_adapter.prepare_mission(file_name)
    planning = {
        "variant_id": project.get("selected_variant_id"),
        "file_name": file_name,
        "drawing_version": version,
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
    stored = creative_projects.set_planning(project_id, planning)
    return {
        "ok": submitted and stored is not None,
        "message": (
            "恢复规划已提交；已完成喷墨段将跳过，疑似部分执行段需人工检查。"
            if submitted else robot_state.mission_error
        ),
        "project_id": project_id,
        "planning": planning,
    }


def build_project_acceptance_report(project_id: str) -> dict[str, Any]:
    project = creative_projects.get(project_id)
    if project is None:
        return {"ok": False, "message": "创意项目不存在"}
    planning_file = str((project.get("planning") or {}).get("file_name") or "")
    if planning_file and robot_state.mission_file == planning_file:
        refresh_project_execution(project_id)
        project = creative_projects.get(project_id) or project
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
    creative_projects.set_report(project_id, report)
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
        for project in creative_projects.list(200):
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
                    creative_projects.set_execution(project["id"], {
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
                    current = creative_projects.get(project["id"]) or {}
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
        creative_projects.set_execution(project["id"], {
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
