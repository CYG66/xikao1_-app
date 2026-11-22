from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from .task_store import utc_now
from .database import xline_database
from .startup_guard import assert_startup_admitted


class AgentAuditStore:
    """Audit writer with a transactional SQLite authority and JSONL mirror.

    SQLite ``audit_logs`` is the authoritative ledger for new events.  JSONL
    remains a recoverable mirror/export.  Persistence failures are never
    swallowed: they increment visible counters, set a degraded health state,
    and write a one-line warning to stderr.  Safety actions still proceed.
    """

    authority = "sqlite"

    def __init__(self, path: Path | None = None) -> None:
        assert_startup_admitted()
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
        self._health: dict[str, Any] = {
            "authority": self.authority,
            "degraded": False,
            "sqlite_failures": 0,
            "jsonl_failures": 0,
            "append_count": 0,
            "last_record_id": None,
            "last_success_at": None,
            "last_error": None,
        }

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
            sqlite_ok = False
            jsonl_ok = False
            try:
                xline_database.record_audit(record)
                sqlite_ok = True
            except Exception as error:  # noqa: BLE001 - surface, never swallow
                self._mark_failure("sqlite", record, error)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                jsonl_ok = True
                try:
                    os.chmod(self.path, 0o600)
                except OSError as error:
                    jsonl_ok = False
                    self._mark_failure("jsonl", record, error)
            except OSError as error:
                self._mark_failure("jsonl", record, error)

            self._health["append_count"] += 1
            self._health["last_record_id"] = record["id"]
            if sqlite_ok and jsonl_ok:
                self._health["degraded"] = False
                self._health["last_success_at"] = record["at"]
            else:
                self._health["degraded"] = True
        return deepcopy(record)

    def health_status(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._health)

    def _mark_failure(self, ledger: str, record: dict[str, Any], error: BaseException) -> None:
        counter = f"{ledger}_failures"
        self._health[counter] = int(self._health.get(counter, 0)) + 1
        self._health["degraded"] = True
        self._health["last_error"] = {
            "ledger": ledger,
            "error": f"{type(error).__name__}: {error}",
            "record_id": record["id"],
            "at": utc_now(),
        }
        print(
            f"[audit] {ledger} persistence failed for {record['id']}: "
            f"{type(error).__name__}: {error}",
            file=sys.stderr,
        )

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
