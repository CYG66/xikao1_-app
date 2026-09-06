from __future__ import annotations

import json
import os
import tempfile
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


TaskState = Literal[
    "pending_confirmation",
    "cancelled",
    "executing",
    "completed",
    "failed",
    "expired",
    "interrupted",
]

TERMINAL_STATES = {"cancelled", "completed", "failed", "expired", "interrupted"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentTaskStore:
    def __init__(self, path: Path | None = None) -> None:
        configured = os.getenv("XLINE_AGENT_TASK_STORE", "").strip()
        default_root = (
            Path(tempfile.gettempdir()) / "xline-agent"
            if os.name == "nt"
            else Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))
            / "xline-agent"
        )
        self.path = path or (Path(configured) if configured else default_root / "tasks.json")
        self._lock = threading.RLock()
        self._tasks: dict[str, dict[str, Any]] = {}
        self._load()
        self._interrupt_unfinished_tasks()

    def create_pending(
        self,
        task_id: str,
        name: str,
        arguments: dict[str, Any],
        expires_at: datetime,
    ) -> dict[str, Any]:
        now = utc_now()
        task = {
            "id": task_id,
            "tool": name,
            "arguments": deepcopy(arguments),
            "state": "pending_confirmation",
            "created_at": now,
            "updated_at": now,
            "expires_at": expires_at.astimezone(timezone.utc).isoformat(),
            "result": None,
            "events": [self._event("pending_confirmation", "等待用户确认")],
        }
        with self._lock:
            self._tasks[task_id] = task
            self._save()
        return deepcopy(task)

    def transition(
        self,
        task_id: str,
        state: TaskState,
        message: str,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            current = str(task["state"])
            if current in TERMINAL_STATES:
                return deepcopy(task)
            task["state"] = state
            task["updated_at"] = utc_now()
            task["events"].append(self._event(state, message))
            if result is not None:
                task["result"] = deepcopy(result)
            self._save()
            return deepcopy(task)

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None and self._expire_if_needed(task):
                self._save()
            return deepcopy(task) if task is not None else None

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            changed = False
            for task in self._tasks.values():
                changed = self._expire_if_needed(task) or changed
            if changed:
                self._save()
            tasks = sorted(
                self._tasks.values(), key=lambda item: str(item.get("created_at", "")), reverse=True
            )
            return deepcopy(tasks[: max(1, min(limit, 200))])

    def recoverable_pending(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        recovered: list[dict[str, Any]] = []
        with self._lock:
            changed = False
            for task in self._tasks.values():
                if task.get("state") != "pending_confirmation":
                    continue
                try:
                    expires_at = datetime.fromisoformat(str(task["expires_at"]))
                except (KeyError, TypeError, ValueError):
                    expires_at = now
                if expires_at <= now:
                    task["state"] = "expired"
                    task["updated_at"] = utc_now()
                    task["events"].append(self._event("expired", "确认已过期"))
                    changed = True
                else:
                    recovered.append(deepcopy(task))
            if changed:
                self._save()
        return recovered

    def _interrupt_unfinished_tasks(self) -> None:
        with self._lock:
            changed = False
            for task in self._tasks.values():
                if task.get("state") != "executing":
                    continue
                task["state"] = "interrupted"
                task["updated_at"] = utc_now()
                task["events"].append(
                    self._event("interrupted", "后端重启，任务不会自动恢复执行")
                )
                changed = True
            if changed:
                self._save()

    def _expire_if_needed(self, task: dict[str, Any]) -> bool:
        if task.get("state") != "pending_confirmation":
            return False
        try:
            expires_at = datetime.fromisoformat(str(task["expires_at"]))
        except (KeyError, TypeError, ValueError):
            expires_at = datetime.now(timezone.utc)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at > datetime.now(timezone.utc):
            return False
        task["state"] = "expired"
        task["updated_at"] = utc_now()
        task["events"].append(self._event("expired", "确认已过期"))
        return True

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            tasks = payload.get("tasks", [])
            if isinstance(tasks, list):
                self._tasks = {
                    str(task["id"]): task
                    for task in tasks
                    if isinstance(task, dict) and isinstance(task.get("id"), str)
                }
        except (OSError, json.JSONDecodeError, TypeError):
            self._tasks = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"schema_version": "1.0", "tasks": list(self._tasks.values())}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _event(state: str, message: str) -> dict[str, str]:
        return {"at": utc_now(), "state": state, "message": message}


agent_tasks = AgentTaskStore()
