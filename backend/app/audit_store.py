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
    and write a one-line warning to stderr.  The degraded state, failure
    counters and any unresolved ledger divergence are persisted next to the
    JSONL mirror so a process restart cannot silently make the audit look
    healthy.  Safety actions still proceed.
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
        configured_health = os.getenv("XLINE_AGENT_AUDIT_HEALTH_STORE", "").strip()
        if path is not None:
            # An explicitly supplied store is self-contained; sharing the
            # application-wide health file would leak counters across tests or
            # separate audit ledgers.
            parent = self.path.parent
            stem = self.path.stem or "agent_audit"
            self.health_path = parent / f"{stem}_health.json"
        elif configured_health:
            self.health_path = Path(configured_health)
        else:
            parent = self.path.parent
            stem = self.path.stem or "agent_audit"
            self.health_path = parent / f"{stem}_health.json"
        self._lock = threading.RLock()
        self._health: dict[str, Any] = {
            "authority": self.authority,
            "degraded": False,
            "degraded_since": None,
            "reconciliation_required": False,
            "sqlite_failures": 0,
            "jsonl_failures": 0,
            "append_count": 0,
            "last_record_id": None,
            "last_success_at": None,
            "last_reconciled_at": None,
            "reconciliation_note": None,
            "reconciliation_evidence": None,
            "last_error": None,
            "ledger_divergence": {
                "only_jsonl": 0,
                "only_sqlite": 0,
                "intersection": 0,
                "jsonl_total": 0,
                "sqlite_total": 0,
                "checked_at": None,
                "status": "not_checked",
            },
            "health_store": str(self.health_path),
        }
        self._load_health()
        self.refresh_ledger_divergence()

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
                self._health["last_success_at"] = record["at"]
                # A successful append does not prove the earlier failed event
                # was repaired.  ``degraded`` stays sticky until an explicit
                # reconciliation acknowledgement.
            else:
                self._health["degraded"] = True
            self._persist_health()
        return deepcopy(record)

    def mark_reconciled(
        self,
        note: str,
        *,
        evidence: str | None = None,
        expected_divergence: dict[str, int] | None = None,
    ) -> None:
        """Clear the degraded state only after evidence-backed reconciliation.

        The note and evidence are mandatory whenever the ledger divergence is
        still visible.  A caller must explicitly state the counts it reviewed
        so a single prose sentence cannot mask an unresolved gap.  Failure
        counters remain cumulative so an acknowledgement cannot erase history.
        """
        cleaned = str(note).strip()
        if not cleaned:
            raise ValueError("reconciliation note is required")
        cleaned_evidence = str(evidence or "").strip()
        with self._lock:
            self.refresh_ledger_divergence()
            divergence = self._health.get("ledger_divergence", {})
            unresolved = (
                divergence.get("status") != "ok"
                or int(divergence.get("only_jsonl", 0) or 0) > 0
                or int(divergence.get("only_sqlite", 0) or 0) > 0
            )
            if unresolved:
                if not cleaned_evidence:
                    raise ValueError("reconciliation evidence is required for an unresolved ledger")
                if not expected_divergence:
                    raise ValueError("expected_divergence is required for an unresolved ledger")
                expected_jsonl = int(expected_divergence.get("only_jsonl", -1))
                expected_sqlite = int(expected_divergence.get("only_sqlite", -1))
                if (
                    expected_jsonl != int(divergence.get("only_jsonl", 0) or 0)
                    or expected_sqlite != int(divergence.get("only_sqlite", 0) or 0)
                ):
                    raise ValueError("expected_divergence does not match the current ledger")
            self._health["degraded"] = False
            self._health["degraded_since"] = None
            self._health["reconciliation_required"] = False
            self._health["last_reconciled_at"] = utc_now()
            self._health["reconciliation_note"] = cleaned
            self._health["reconciliation_evidence"] = cleaned_evidence or None
            self._health["reconciliation_divergence"] = deepcopy(divergence)
            self._persist_health()

    def refresh_ledger_divergence(self) -> dict[str, Any]:
        """Compare the SQLite authority with the JSONL mirror without repairing it."""
        jsonl_ids = self._jsonl_event_ids()
        try:
            sqlite_ids = set(xline_database.audit_event_ids())
            status = "ok"
        except Exception as error:  # noqa: BLE001 - visibility is the point
            sqlite_ids = set()
            status = f"unavailable: {type(error).__name__}: {error}"
        with self._lock:
            only_jsonl = jsonl_ids - sqlite_ids
            only_sqlite = sqlite_ids - jsonl_ids
            divergence = {
                "only_jsonl": len(only_jsonl),
                "only_sqlite": len(only_sqlite),
                "intersection": len(jsonl_ids & sqlite_ids),
                "jsonl_total": len(jsonl_ids),
                "sqlite_total": len(sqlite_ids),
                "checked_at": utc_now(),
                "status": status,
            }
            self._health["ledger_divergence"] = divergence
            if status != "ok" or only_jsonl or only_sqlite:
                self._health["degraded"] = True
                self._health["reconciliation_required"] = True
                if not self._health.get("degraded_since"):
                    self._health["degraded_since"] = divergence["checked_at"]
            self._persist_health()
            return deepcopy(divergence)

    def health_status(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._health)

    def _jsonl_event_ids(self) -> set[str]:
        ids: set[str] = set()
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if isinstance(item, dict) and item.get("id"):
                        ids.add(str(item["id"]))
        except (OSError, UnicodeDecodeError):
            return ids
        return ids

    def _load_health(self) -> None:
        try:
            payload = json.loads(self.health_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
            # A damaged/unreadable health record must not look healthy.  Keep
            # degraded visible and require an explicit, evidence-backed
            # reconciliation before any later append can clear it.
            self._health["degraded"] = True
            self._health["degraded_since"] = utc_now()
            self._health["reconciliation_required"] = True
            self._health["last_error"] = {
                "ledger": "health",
                "error": f"{type(error).__name__}: {error}",
                "record_id": None,
                "at": utc_now(),
            }
            return
        if not isinstance(payload, dict):
            self._health["degraded"] = True
            self._health["degraded_since"] = utc_now()
            self._health["reconciliation_required"] = True
            self._health["last_error"] = {
                "ledger": "health",
                "error": "health record is not an object",
                "record_id": None,
                "at": utc_now(),
            }
            return
        for key in (
            "degraded",
            "degraded_since",
            "reconciliation_required",
            "sqlite_failures",
            "jsonl_failures",
            "append_count",
            "last_record_id",
            "last_success_at",
            "last_reconciled_at",
            "reconciliation_note",
            "reconciliation_evidence",
            "last_error",
            "ledger_divergence",
        ):
            if key in payload:
                self._health[key] = payload[key]
        self._health["health_store"] = str(self.health_path)

    def _persist_health(self) -> None:
        self._health["health_store"] = str(self.health_path)
        try:
            self.health_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.health_path.with_name(f".{self.health_path.name}.{os.getpid()}.tmp")
            temporary.write_text(
                json.dumps(self._health, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.health_path)
        except OSError as error:
            print(f"[audit] health store persistence failed: {type(error).__name__}: {error}", file=sys.stderr)

    def _mark_failure(self, ledger: str, record: dict[str, Any], error: BaseException) -> None:
        counter = f"{ledger}_failures"
        self._health[counter] = int(self._health.get(counter, 0)) + 1
        self._health["degraded"] = True
        self._health["reconciliation_required"] = True
        if not self._health.get("degraded_since"):
            self._health["degraded_since"] = utc_now()
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
