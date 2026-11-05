from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any
from datetime import datetime, timedelta, timezone

from .task_store import utc_now


AGENT_RUN_STATES = {
    "created",
    "understanding",
    "awaiting_clarification",
    "planning",
    "awaiting_confirmation",
    "executing",
    "verifying",
    "retrying",
    "paused",
    "completed",
    "failed",
    "cancelled",
}

TERMINAL_AGENT_RUN_STATES = {"completed", "failed", "cancelled"}

ALLOWED_AGENT_RUN_TRANSITIONS: dict[str, set[str]] = {
    "created": {"understanding", "cancelled", "failed"},
    # Read-only questions may finish after understanding without a plan.
    "understanding": {"awaiting_clarification", "planning", "completed", "failed", "cancelled"},
    "awaiting_clarification": {"understanding", "planning", "cancelled", "failed"},
    "planning": {"awaiting_confirmation", "executing", "completed", "failed", "cancelled"},
    "awaiting_confirmation": {"executing", "planning", "cancelled", "failed"},
    "executing": {"verifying", "retrying", "completed", "failed", "cancelled"},
    "verifying": {"completed", "retrying", "awaiting_clarification", "failed", "cancelled"},
    "retrying": {"planning", "executing", "failed", "cancelled"},
    "paused": {"planning", "cancelled", "failed"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


class AgentRunStore:
    """Persistence for one AI request lifecycle, separate from rover execution missions."""

    def __init__(self, path: Path | None = None) -> None:
        configured = os.getenv("XLINE_AGENT_RUN_STORE", "").strip()
        default_root = (
            Path(tempfile.gettempdir()) / "xline-agent"
            if os.name == "nt"
            else Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))
            / "xline-agent"
        )
        self.path = path or (Path(configured) if configured else default_root / "agent_runs.json")
        self._lock = threading.RLock()
        self._runs: dict[str, dict[str, Any]] = {}
        self._load()

    def create(
        self,
        user_message: str,
        *,
        conversation_id: str | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        source_variant_id: str | None = None,
        drawing_selection: dict[str, Any] | None = None,
        pending_command: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        mode: str = "advanced",
        success_criteria: list[dict[str, Any]] | None = None,
        timeout_seconds: int = 180,
    ) -> dict[str, Any]:
        now = utc_now()
        try:
            timeout_seconds = max(30, min(int(timeout_seconds), 3600))
        except (TypeError, ValueError):
            timeout_seconds = 180
        timeout_at = (
            datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
        ).isoformat()
        run = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "conversation_id": conversation_id,
            "project_id": project_id,
            "source_variant_id": source_variant_id,
            "drawing_selection": deepcopy(drawing_selection),
            "pending_command": deepcopy(pending_command),
            "idempotency_key": str(idempotency_key or "") or None,
            "mode": mode,
            "user_message": user_message,
            "state": "created",
            "created_at": now,
            "updated_at": now,
            "timeout_at": timeout_at,
            "steps": [],
            "artifacts": [],
            "success_criteria": deepcopy(success_criteria or []),
            "attempts": [],
            "checkpoint": None,
            "failure": None,
            "events": [{"at": now, "state": "created", "message": "AI 请求已创建"}],
        }
        with self._lock:
            self._runs[run["id"]] = run
            self._save()
        return deepcopy(run)

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                self._pause_if_expired(run)
            return deepcopy(run) if run else None

    def list(self, limit: int = 50, *, conversation_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            changed = False
            for run in self._runs.values():
                changed = self._pause_if_expired(run) or changed
            if changed:
                self._save()
            values = [
                run for run in self._runs.values()
                if conversation_id is None or run.get("conversation_id") == conversation_id
            ]
            values.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
            return deepcopy(values[: max(1, min(limit, 200))])

    def set_checkpoint(self, run_id: str, checkpoint: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            run["checkpoint"] = deepcopy(checkpoint)
            run["updated_at"] = utc_now()
            self._save()
            return deepcopy(run)

    def resume(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or str(run.get("state")) != "paused":
                return deepcopy(run) if run else None
            run["timeout_at"] = (
                datetime.now(timezone.utc) + timedelta(seconds=180)
            ).isoformat()
        return self.transition(run_id, "planning", "从最后检查点恢复，重新规划")

    def transition(
        self,
        run_id: str,
        state: str,
        message: str,
        *,
        failure: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or state not in AGENT_RUN_STATES:
                return None
            current = str(run["state"])
            if current in TERMINAL_AGENT_RUN_STATES:
                return deepcopy(run)
            if state not in ALLOWED_AGENT_RUN_TRANSITIONS.get(current, set()):
                return deepcopy(run)
            run["state"] = state
            run["updated_at"] = utc_now()
            run["events"].append({"at": run["updated_at"], "state": state, "message": message})
            if failure is not None:
                run["failure"] = deepcopy(failure)
            self._save()
            return deepcopy(run)

    def cancel(self, run_id: str, reason: str = "用户取消 AI 请求") -> dict[str, Any] | None:
        return self.transition(
            run_id,
            "cancelled",
            reason,
            failure={
                "category": "user_cancelled",
                "next_action": "none",
                "retryable": True,
                "reason": reason,
            },
        )

    def add_step(self, run_id: str, step: dict[str, Any]) -> dict[str, Any] | None:
        return self._append(run_id, "steps", step)

    def add_artifact(self, run_id: str, artifact: dict[str, Any]) -> dict[str, Any] | None:
        return self._append(run_id, "artifacts", artifact)

    def add_attempt(self, run_id: str, attempt: dict[str, Any]) -> dict[str, Any] | None:
        return self._append(run_id, "attempts", attempt)

    def set_success_criteria(self, run_id: str, criteria: list[dict[str, Any]]) -> dict[str, Any] | None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            run["success_criteria"] = deepcopy(criteria)
            run["updated_at"] = utc_now()
            self._save()
            return deepcopy(run)

    def bind_context(
        self,
        run_id: str,
        *,
        project_id: str | None = None,
        source_variant_id: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or str(run.get("state")) in TERMINAL_AGENT_RUN_STATES:
                return deepcopy(run) if run else None
            if project_id:
                run["project_id"] = project_id
            if source_variant_id:
                run["source_variant_id"] = source_variant_id
            run["updated_at"] = utc_now()
            self._save()
            return deepcopy(run)

    def _append(self, run_id: str, key: str, value: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or str(run.get("state")) in TERMINAL_AGENT_RUN_STATES:
                return deepcopy(run) if run else None
            values = run.setdefault(key, [])
            idempotency_key = str(value.get("idempotency_key") or "")
            if idempotency_key and any(
                str(item.get("idempotency_key") or "") == idempotency_key
                for item in values if isinstance(item, dict)
            ):
                return deepcopy(run)
            values.append(deepcopy(value))
            run["updated_at"] = utc_now()
            self._save()
            return deepcopy(run)

    @staticmethod
    def _pause_if_expired(run: dict[str, Any]) -> bool:
        if str(run.get("state")) in TERMINAL_AGENT_RUN_STATES | {"paused"}:
            return False
        raw_timeout = run.get("timeout_at")
        try:
            timeout_at = datetime.fromisoformat(str(raw_timeout))
        except (TypeError, ValueError):
            return False
        if timeout_at.tzinfo is None:
            timeout_at = timeout_at.replace(tzinfo=timezone.utc)
        if timeout_at > datetime.now(timezone.utc):
            return False
        now = utc_now()
        run["state"] = "paused"
        run["updated_at"] = now
        run["failure"] = {
            "category": "timeout",
            "next_action": "resume_from_checkpoint",
            "retryable": True,
            "reason": "AI 请求超时，已暂停并保留最后检查点",
        }
        run.setdefault("events", []).append({
            "at": now,
            "state": "paused",
            "message": "AI 请求超时，已暂停并保留最后检查点",
        })
        return True

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return
        runs = payload.get("runs", []) if isinstance(payload, dict) else []
        if isinstance(runs, list):
            self._runs = {
                str(run["id"]): run
                for run in runs
                if isinstance(run, dict) and isinstance(run.get("id"), str)
            }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"schema_version": "1.0", "runs": list(self._runs.values())}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass


agent_runs = AgentRunStore()
