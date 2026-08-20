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


class AgentAuditStore:
    def __init__(self, path: Path | None = None) -> None:
        configured = os.getenv("XLINE_AGENT_AUDIT_STORE", "").strip()
        default_root = (
            Path(tempfile.gettempdir()) / "xline-agent"
            if os.name == "nt"
            else Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))
            / "xline-agent"
        )
        self.path = path or (
            Path(configured) if configured else default_root / "agent_audit.jsonl"
        )
        self._lock = threading.RLock()

    def append(
        self,
        event: str,
        tool: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        record = {
            "id": uuid.uuid4().hex,
            "at": utc_now(),
            "event": event,
            "tool": tool,
            "arguments": self._redact(arguments),
            "ok": result.get("ok") is not False,
            "message": str(result.get("message", "")),
        }
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                os.chmod(self.path, 0o600)
            except OSError:
                pass
            try:
                xline_database.record_audit(record)
            except Exception:
                # Audit persistence must never block a tool or safety action.
                pass
        return deepcopy(record)

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        maximum = max(1, min(limit, 500))
        with self._lock:
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except OSError:
                return []
        records: list[dict[str, Any]] = []
        for line in reversed(lines):
            try:
                item = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(item, dict):
                records.append(item)
            if len(records) >= maximum:
                break
        return records

    @classmethod
    def _redact(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): "***"
                if any(secret in str(key).lower() for secret in ("api_key", "token", "password"))
                else cls._redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._redact(item) for item in value]
        return value


agent_audit = AgentAuditStore()
