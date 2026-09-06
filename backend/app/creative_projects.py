from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from .task_store import utc_now
from .database import xline_database


PROJECT_STATUSES = {
    "draft", "clarifying", "ready_for_design", "designing",
    "ready_for_planning", "planning", "planning_ready", "planning_failed",
    "pending_execution", "executing", "paused", "execution_failed",
    "completed", "cancelled",
}

ALLOWED_TRANSITIONS = {
    "draft": {"clarifying", "ready_for_design", "cancelled"},
    "clarifying": {"clarifying", "ready_for_design", "cancelled"},
    "ready_for_design": {"ready_for_design", "designing", "cancelled"},
    "designing": {"designing", "ready_for_planning", "cancelled"},
    "ready_for_planning": {"designing", "planning", "cancelled"},
    "planning": {"planning", "planning_ready", "planning_failed", "cancelled"},
    "planning_failed": {"designing", "planning", "cancelled"},
    "planning_ready": {"planning", "pending_execution", "cancelled"},
    "pending_execution": {"planning_ready", "executing", "execution_failed", "cancelled"},
    "executing": {"executing", "paused", "completed", "execution_failed", "cancelled"},
    "paused": {"paused", "executing", "planning", "execution_failed", "cancelled"},
    "execution_failed": {"planning", "cancelled"},
    "completed": set(),
    "cancelled": {"planning"},
}


class CreativeProjectStore:
    def __init__(self, path: Path | None = None) -> None:
        self._database_enabled = path is None
        configured = os.getenv("XLINE_CREATIVE_PROJECT_STORE", "").strip()
        default_root = (
            Path(tempfile.gettempdir()) / "xline-agent"
            if os.name == "nt"
            else Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))
            / "xline-agent"
        )
        self.path = path or (Path(configured) if configured else default_root / "creative_projects.json")
        self._lock = threading.RLock()
        self._projects: dict[str, dict[str, Any]] = {}
        self._load()

    def create(self, name: str, original_prompt: str,
               requirements: dict[str, Any] | None = None,
               constraints: dict[str, Any] | None = None,
               missing_parameters: list[str] | None = None) -> dict[str, Any]:
        now = utc_now()
        missing = self._clean_missing(missing_parameters or [])
        project_id = str(uuid.uuid4())
        status = "clarifying" if missing else "ready_for_design"
        project = {
            "id": project_id, "name": name.strip(),
            "original_prompt": original_prompt.strip(),
            "requirements": deepcopy(requirements or {}),
            "constraints": deepcopy(constraints or {}),
            "missing_parameters": missing, "status": status, "variants": [],
            "created_at": now, "updated_at": now,
            "events": [self._event("created", f"项目已创建，状态为 {status}")],
        }
        with self._lock:
            self._projects[project_id] = project
            self._save()
        return deepcopy(project)

    def update(self, project_id: str, *, name: str | None = None,
               requirements: dict[str, Any] | None = None,
               constraints: dict[str, Any] | None = None,
               missing_parameters: list[str] | None = None,
               status: str | None = None,
               event_message: str = "项目需求已更新") -> dict[str, Any] | None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                return None
            content_update = any(value is not None for value in (
                name, requirements, constraints, missing_parameters
            ))
            if content_update and project.get("status") not in {
                "draft", "clarifying", "ready_for_design"
            }:
                return None
            target_status = status
            if target_status is None and missing_parameters is not None:
                target_status = "clarifying" if self._clean_missing(missing_parameters) else "ready_for_design"
            if target_status is not None:
                if target_status not in PROJECT_STATUSES:
                    raise ValueError(f"unsupported project status: {target_status}")
                if not self._transition(project, target_status):
                    return None
            if name is not None:
                project["name"] = name.strip()
            if requirements is not None:
                project["requirements"] = self._merge(project["requirements"], requirements)
            if constraints is not None:
                project["constraints"] = self._merge(project["constraints"], constraints)
            if missing_parameters is not None:
                project["missing_parameters"] = self._clean_missing(missing_parameters)
            project["updated_at"] = utc_now()
            project["events"].append(self._event("updated", event_message))
            self._save()
            return deepcopy(project)

    def get(self, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            project = self._projects.get(project_id)
            return deepcopy(project) if project is not None else None

    def list(self, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            projects = list(self._projects.values())
            if status:
                projects = [item for item in projects if item.get("status") == status]
            projects.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
            return deepcopy(projects[:max(1, min(limit, 200))])

    def delete(self, project_id: str) -> bool:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.get("status") in {"planning", "pending_execution", "executing", "paused"}:
                return False
            self._projects.pop(project_id)
            if self._database_enabled:
                xline_database.delete_project(project_id)
            self._save()
            return True

    def add_variant(self, project_id: str, name: str, geometries: list[dict[str, Any]],
                    rationale: str, assessment: dict[str, Any],
                    preview_paths: list[list[list[float]]]) -> dict[str, Any] | None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.get("status") not in {
                "ready_for_design", "designing", "ready_for_planning", "planning_failed"
            }:
                return None
            variant = {
                "id": str(uuid.uuid4()),
                "name": name.strip(),
                "rationale": rationale.strip(),
                "geometries": deepcopy(geometries),
                "assessment": deepcopy(assessment),
                "preview_paths": deepcopy(preview_paths),
                "selected": False,
                "created_at": utc_now(),
            }
            project["variants"].append(variant)
            if not self._transition(project, "designing"):
                return None
            project["updated_at"] = utc_now()
            project["events"].append(self._event("variant_added", f"新增方案：{variant['name']}"))
            self._save()
            return deepcopy(variant)

    def select_variant(self, project_id: str, variant_id: str) -> dict[str, Any] | None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.get("status") not in {"designing", "ready_for_planning"}:
                return None
            selected = None
            for variant in project["variants"]:
                variant["selected"] = variant.get("id") == variant_id
                if variant["selected"]:
                    selected = variant
            if selected is None:
                return None
            project["selected_variant_id"] = variant_id
            if not self._transition(project, "ready_for_planning"):
                return None
            project["updated_at"] = utc_now()
            project["events"].append(self._event("variant_selected", f"已选择方案：{selected['name']}"))
            self._save()
            return deepcopy(project)

    def set_planning(self, project_id: str, planning: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                return None
            if project.get("planning") == planning:
                return deepcopy(project)
            stage = str(planning.get("stage", ""))
            target_status = "planning"
            if stage == "ready" and (planning.get("validation") or {}).get("ok") is True:
                target_status = "planning_ready"
            elif stage in {"planning_failed", "failed", "cancelled"} or planning.get("error"):
                target_status = "planning_failed"
            if not self._transition(project, target_status):
                return None
            project["planning"] = deepcopy(planning)
            project["updated_at"] = utc_now()
            project["events"].append(self._event("planning_updated", f"规划阶段：{stage or 'unknown'}"))
            self._save()
            return deepcopy(project)

    def set_execution(self, project_id: str, execution: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                return None
            if project.get("execution") == execution:
                return deepcopy(project)
            stage = str(execution.get("stage", ""))
            target_status = {
                "pending_confirmation": "pending_execution",
                "confirmation_cancelled": "planning_ready",
                "executing": "executing",
                "paused": "paused",
                "completed": "completed",
                "cancelled": "cancelled",
                "failed": "execution_failed",
                "interrupted": "execution_failed",
            }.get(stage, project["status"])
            if target_status != project["status"] and not self._transition(project, target_status):
                return None
            project["execution"] = deepcopy(execution)
            project["updated_at"] = utc_now()
            project["events"].append(self._event("execution_updated", f"执行阶段：{stage or 'unknown'}"))
            self._save()
            return deepcopy(project)

    def set_report(self, project_id: str, report: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                return None
            project["acceptance_report"] = deepcopy(report)
            project["updated_at"] = utc_now()
            project["events"].append(self._event("report_generated", "项目验收报告已生成"))
            self._save()
            return deepcopy(project)

    def confirm_recovery_inspection(self, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None or project.get("status") != "planning_ready":
                return None
            planning = project.get("planning")
            recovery = planning.get("recovery") if isinstance(planning, dict) else None
            if not isinstance(recovery, dict) or recovery.get("manual_inspection_required") is not True:
                return None
            recovery["manual_inspection_confirmed"] = True
            recovery["manual_inspection_confirmed_at"] = utc_now()
            project["updated_at"] = utc_now()
            project["events"].append(self._event("recovery_inspection_confirmed", "用户已确认检查疑似部分喷墨段"))
            self._save()
            return deepcopy(project)

    def find_by_action(self, action_id: str) -> dict[str, Any] | None:
        with self._lock:
            project = next((item for item in self._projects.values()
                            if (item.get("execution") or {}).get("action_id") == action_id), None)
            return deepcopy(project) if project is not None else None

    def _load(self) -> None:
        if self._database_enabled:
            stored = xline_database.load_payloads("projects", "project_id")
            if stored:
                self._projects = {
                    str(item["id"]): item for item in stored
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                }
                return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            projects = payload.get("projects", [])
            if isinstance(projects, list):
                self._projects = {str(item["id"]): item for item in projects
                                  if isinstance(item, dict) and isinstance(item.get("id"), str)}
                if self._database_enabled:
                    for item in self._projects.values():
                        xline_database.save_project(item)
        except (OSError, json.JSONDecodeError, TypeError):
            self._projects = {}

    def _save(self) -> None:
        if self._database_enabled:
            for project in self._projects.values():
                xline_database.save_project(project)
                if isinstance(project.get("planning"), dict):
                    xline_database.save_planning(
                        str(project["id"]), project["planning"],
                        str(project.get("status", "draft")), str(project.get("updated_at", "")),
                    )
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(
            {"schema_version": "1.0", "projects": list(self._projects.values())},
            ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _merge(current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(current)
        merged.update(deepcopy(updates))
        return merged

    @staticmethod
    def _clean_missing(values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @staticmethod
    def _event(event_type: str, message: str) -> dict[str, str]:
        return {"at": utc_now(), "type": event_type, "message": message}

    @staticmethod
    def _transition(project: dict[str, Any], target: str) -> bool:
        current = str(project.get("status", "draft"))
        if target == current:
            return True
        if target not in ALLOWED_TRANSITIONS.get(current, set()):
            return False
        project["status"] = target
        return True


creative_projects = CreativeProjectStore()
