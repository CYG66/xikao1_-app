"""SQLite persistence for business history and telemetry.

The database is an audit/history layer. Real-time safety decisions must still
come from ROS2/CAN state, never from a cached database row.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any


def _default_path() -> Path:
    configured = os.getenv("XLINE_DATABASE_PATH", "").strip()
    if configured:
        return Path(configured)
    if os.name == "nt":
        return Path(tempfile.gettempdir()) / "xline-agent" / "xline.db"
    return (
        Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))
        / "xline-agent"
        / "xline.db"
    )


class XLineDatabase:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _default_path()
        self._lock = threading.RLock()
        self._last_telemetry_monotonic = 0.0
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def _session(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._session() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL,
                    description TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    vehicle_id TEXT,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS design_versions (
                    version_id TEXT PRIMARY KEY,
                    project_id TEXT,
                    version INTEGER NOT NULL,
                    parent_version_id TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS planning_tasks (
                    planning_id TEXT PRIMARY KEY,
                    project_id TEXT,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS execution_tasks (
                    execution_id TEXT PRIMARY KEY,
                    project_id TEXT,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS execution_segments (
                    segment_id TEXT PRIMARY KEY,
                    execution_id TEXT,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vehicle_id TEXT,
                    recorded_at TEXT NOT NULL,
                    localization_valid INTEGER,
                    emergency_stopped INTEGER,
                    control_ready INTEGER,
                    linear_velocity REAL,
                    pose_json TEXT NOT NULL,
                    status_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_logs (
                    event_id TEXT PRIMARY KEY,
                    recorded_at TEXT NOT NULL,
                    event TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    ok INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_case_memory (
                    case_id TEXT PRIMARY KEY,
                    project_id TEXT,
                    category TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    ok INTEGER NOT NULL,
                    input_json TEXT NOT NULL,
                    outcome_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS device_capabilities (
                    device_id TEXT PRIMARY KEY,
                    model TEXT NOT NULL,
                    software_version TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    motion_limits_json TEXT NOT NULL,
                    topics_json TEXT NOT NULL,
                    services_json TEXT NOT NULL,
                    actions_json TEXT NOT NULL,
                    localization_json TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_telemetry_recorded_at
                    ON telemetry(recorded_at);
                CREATE INDEX IF NOT EXISTS idx_audit_recorded_at
                    ON audit_logs(recorded_at);
                CREATE INDEX IF NOT EXISTS idx_design_versions_project_id
                    ON design_versions(project_id);
                CREATE INDEX IF NOT EXISTS idx_planning_tasks_project_id
                    ON planning_tasks(project_id);
                CREATE INDEX IF NOT EXISTS idx_execution_tasks_project_id
                    ON execution_tasks(project_id);
                CREATE INDEX IF NOT EXISTS idx_audit_event
                    ON audit_logs(event);
                CREATE INDEX IF NOT EXISTS idx_audit_tool
                    ON audit_logs(tool);
                """
            )
            migrations = (
                (1, "initial business, telemetry and audit schema"),
                (2, "device capability and ROS2 interface registry"),
                (3, "audit query indexes and consistent backup support"),
            )
            connection.executemany(
                """INSERT OR IGNORE INTO schema_migrations
                   (version, applied_at, description)
                   VALUES (?, datetime('now'), ?)""",
                migrations,
            )

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def record_audit(self, record: dict[str, Any]) -> None:
        with self._lock, self._session() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO audit_logs
                (event_id, recorded_at, event, tool, ok, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    str(record.get("id", "")),
                    str(record.get("at", "")),
                    str(record.get("event", "")),
                    str(record.get("tool", "")),
                    int(record.get("ok") is True),
                    self._json(record),
                ),
            )

    def list_audit(
        self,
        limit: int = 100,
        event: str | None = None,
        tool: str | None = None,
        ok: bool | None = None,
    ) -> list[dict[str, Any]]:
        maximum = max(1, min(limit, 500))
        clauses: list[str] = []
        params: list[Any] = []
        if event:
            clauses.append("event = ?")
            params.append(event)
        if tool:
            clauses.append("tool = ?")
            params.append(tool)
        if ok is not None:
            clauses.append("ok = ?")
            params.append(int(ok))
        query = "SELECT payload_json FROM audit_logs"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY recorded_at DESC LIMIT ?"
        params.append(maximum)
        with self._lock, self._session() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            try:
                value = json.loads(row[0])
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                records.append(value)
        return records

    def backup(self, destination: Path) -> dict[str, Any]:
        """Create a consistent SQLite backup, including WAL contents."""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            source = self._connect()
            try:
                target = sqlite3.connect(destination)
                try:
                    source.backup(target)
                finally:
                    target.close()
            finally:
                source.close()
        return {
            "ok": True,
            "path": str(destination),
            "size_bytes": destination.stat().st_size,
        }

    def migration_status(self) -> dict[str, Any]:
        with self._lock, self._session() as connection:
            rows = connection.execute(
                "SELECT version, applied_at, description FROM schema_migrations ORDER BY version"
            ).fetchall()
        return {
            "current_version": int(rows[-1]["version"]) if rows else 0,
            "migrations": [dict(row) for row in rows],
        }

    def record_ai_case(
        self,
        project_id: str,
        category: str,
        tool: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        case_id = f"{project_id}:{tool}:{time.time_ns()}"
        with self._lock, self._session() as connection:
            connection.execute(
                """INSERT INTO ai_case_memory
                (case_id, project_id, category, tool, ok, input_json, outcome_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (
                    case_id, project_id, category, tool,
                    int(result.get("ok") is True), self._json(arguments), self._json(result),
                ),
            )

    def list_ai_cases(self, project_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        maximum = max(1, min(limit, 200))
        query = "SELECT * FROM ai_case_memory"
        params: tuple[Any, ...] = ()
        if project_id:
            query += " WHERE project_id = ?"
            params = (project_id,)
        query += " ORDER BY created_at DESC LIMIT ?"
        params += (maximum,)
        with self._lock, self._session() as connection:
            rows = connection.execute(query, params).fetchall()
        cases: list[dict[str, Any]] = []
        for row in rows:
            try:
                arguments = json.loads(row["input_json"])
                outcome = json.loads(row["outcome_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            cases.append({
                "case_id": row["case_id"], "project_id": row["project_id"],
                "category": row["category"], "tool": row["tool"],
                "ok": bool(row["ok"]), "arguments": arguments,
                "result": outcome, "created_at": row["created_at"],
            })
        return cases

    def upsert_device_capabilities(
        self, snapshot: dict[str, Any], interfaces: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Persist the latest discovered device contract.

        This is a capability registry and history aid. Callers must continue
        to use the live ROS2/CAN state for safety and motion authorization.
        """
        vehicle = snapshot.get("vehicle") if isinstance(snapshot.get("vehicle"), dict) else {}
        capabilities = vehicle.get("capabilities") if isinstance(vehicle.get("capabilities"), dict) else {}
        motion_limits = vehicle.get("motion_limits") if isinstance(vehicle.get("motion_limits"), dict) else {}
        localization = vehicle.get("localization") if isinstance(vehicle.get("localization"), dict) else {}
        interfaces = interfaces if isinstance(interfaces, dict) else {}
        device_id = str(vehicle.get("device_id") or "default")
        record = {
            "device_id": device_id,
            "model": str(vehicle.get("model") or "XLine Rover"),
            "software_version": str(vehicle.get("software_version") or ""),
            "capabilities": capabilities,
            "motion_limits": motion_limits,
            "topics": interfaces.get("topics", {
                "configured": interfaces.get("configured_topics", {}),
                "discovered": interfaces.get("discovered_topics", {}),
            }),
            "services": interfaces.get("services", {
                "configured": interfaces.get("configured_services", {}),
                "discovered": interfaces.get("discovered_services", {}),
            }),
            "actions": interfaces.get("actions", {
                "configured": interfaces.get("configured_actions", {}),
            }),
            "localization": localization,
            "last_seen": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        with self._lock, self._session() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO device_capabilities
                (device_id, model, software_version, capabilities_json,
                 motion_limits_json, topics_json, services_json, actions_json,
                 localization_json, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record["device_id"], record["model"], record["software_version"],
                    self._json(record["capabilities"]), self._json(record["motion_limits"]),
                    self._json(record["topics"]), self._json(record["services"]),
                    self._json(record["actions"]), self._json(record["localization"]),
                    record["last_seen"],
                ),
            )
        return record

    def list_device_capabilities(self, device_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM device_capabilities"
        params: tuple[Any, ...] = ()
        if device_id:
            query += " WHERE device_id = ?"
            params = (device_id,)
        query += " ORDER BY last_seen DESC"
        with self._lock, self._session() as connection:
            rows = connection.execute(query, params).fetchall()
        result: list[dict[str, Any]] = []
        json_columns = {
            "capabilities": "capabilities_json",
            "motion_limits": "motion_limits_json",
            "topics": "topics_json",
            "services": "services_json",
            "actions": "actions_json",
            "localization": "localization_json",
        }
        for row in rows:
            item: dict[str, Any] = {
                "device_id": row["device_id"], "model": row["model"],
                "software_version": row["software_version"], "last_seen": row["last_seen"],
            }
            for name, column in json_columns.items():
                try:
                    item[name] = json.loads(row[column])
                except (TypeError, json.JSONDecodeError):
                    item[name] = {}
            result.append(item)
        return result

    def load_payloads(self, table: str, id_column: str) -> list[dict[str, Any]]:
        allowed = {
            "projects": "project_id",
            "execution_tasks": "execution_id",
        }
        if table not in allowed or allowed[table] != id_column:
            raise ValueError("unsupported database payload table")
        with self._lock, self._session() as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {table} ORDER BY rowid"
            ).fetchall()
            values = []
            for row in rows:
                try:
                    item = json.loads(row[0])
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(item, dict):
                    values.append(item)
            return values

    def save_project(self, project: dict[str, Any]) -> None:
        with self._lock, self._session() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO projects
                (project_id, vehicle_id, status, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?)""",
                (str(project["id"]), str(project.get("vehicle_id", "")),
                 str(project.get("status", "draft")), self._json(project),
                 str(project.get("updated_at", ""))),
            )

    def delete_project(self, project_id: str) -> None:
        with self._lock, self._session() as connection:
            connection.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))

    def project_timeline(self, project_id: str) -> dict[str, list[dict[str, Any]]]:
        """Return the persisted business chain for one project.

        This is history and traceability data only. It is deliberately not
        used by ROS2 safety or motion decisions.
        """
        with self._lock, self._session() as connection:
            result: dict[str, list[dict[str, Any]]] = {}
            queries = {
                "design_versions": (
                    "SELECT payload_json FROM design_versions "
                    "WHERE project_id = ? ORDER BY version"
                ),
                "planning_tasks": (
                    "SELECT payload_json FROM planning_tasks "
                    "WHERE project_id = ? ORDER BY updated_at"
                ),
                "execution_tasks": (
                    "SELECT payload_json FROM execution_tasks "
                    "WHERE project_id = ? ORDER BY updated_at"
                ),
            }
            for name, query in queries.items():
                values: list[dict[str, Any]] = []
                for row in connection.execute(query, (project_id,)).fetchall():
                    try:
                        value = json.loads(row[0])
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if isinstance(value, dict):
                        values.append(value)
                result[name] = values

            segments: list[dict[str, Any]] = []
            rows = connection.execute(
                """SELECT s.payload_json
                   FROM execution_segments s
                   JOIN execution_tasks e ON e.execution_id = s.execution_id
                   WHERE e.project_id = ?
                   ORDER BY s.recorded_at, s.segment_id""",
                (project_id,),
            ).fetchall()
            for row in rows:
                try:
                    value = json.loads(row[0])
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(value, dict):
                    segments.append(value)
            result["execution_segments"] = segments
            return result

    def save_planning(self, project_id: str, planning: dict[str, Any], status: str, updated_at: str) -> None:
        planning_id = f"project:{project_id}"
        with self._lock, self._session() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO planning_tasks
                (planning_id, project_id, status, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, COALESCE((SELECT created_at FROM planning_tasks WHERE planning_id = ?), ?), ?)""",
                (planning_id, project_id, status, self._json(planning), planning_id, updated_at, updated_at),
            )

    def load_design_versions(self) -> list[dict[str, Any]]:
        with self._lock, self._session() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM design_versions ORDER BY created_at"
            ).fetchall()
            values = []
            for row in rows:
                try:
                    item = json.loads(row[0])
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(item, dict):
                    values.append(item)
            return values

    def save_design_version(self, item: dict[str, Any], payload: dict[str, Any]) -> None:
        stored = {**item, "payload": payload}
        project_id = item.get("project_id") or payload.get("creative_project_id")
        with self._lock, self._session() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO design_versions
                (version_id, project_id, version, parent_version_id, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (str(item["file_name"]), str(project_id) if project_id else None,
                 int(item.get("version", 0)),
                 item.get("parent_file_name"), self._json(stored), str(item.get("created_at", ""))),
            )

    def load_execution_tasks(self) -> list[dict[str, Any]]:
        return self.load_payloads("execution_tasks", "execution_id")

    def save_execution_task(self, mission: dict[str, Any]) -> None:
        with self._lock, self._session() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO execution_tasks
                (execution_id, project_id, status, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (str(mission["id"]), mission.get("project_id"), str(mission.get("state", "ready")),
                 self._json(mission), str(mission.get("created_at", "")), str(mission.get("updated_at", ""))),
            )
            connection.execute("DELETE FROM execution_segments WHERE execution_id = ?", (str(mission["id"]),))
            for segment in mission.get("segments", []):
                segment_id = f"{mission['id']}:{segment.get('index', 0)}"
                connection.execute(
                    """INSERT INTO execution_segments
                    (segment_id, execution_id, status, payload_json, recorded_at)
                    VALUES (?, ?, ?, ?, datetime('now'))""",
                    (segment_id, str(mission["id"]), str(segment.get("state", "pending")), self._json(segment)),
                )

    def record_telemetry(self, snapshot: dict[str, Any]) -> None:
        now = time.monotonic()
        with self._lock:
            if now - self._last_telemetry_monotonic < 1.0:
                return
            self._last_telemetry_monotonic = now
        vehicle = snapshot.get("vehicle") if isinstance(snapshot.get("vehicle"), dict) else {}
        runtime = vehicle.get("runtime") if isinstance(vehicle.get("runtime"), dict) else {}
        safety = vehicle.get("safety") if isinstance(vehicle.get("safety"), dict) else {}
        localization = snapshot.get("localization") if isinstance(snapshot.get("localization"), dict) else {}
        pose = snapshot.get("robot_pose") if isinstance(snapshot.get("robot_pose"), dict) else {}
        with self._lock, self._session() as connection:
            connection.execute(
                """INSERT INTO telemetry
                (vehicle_id, recorded_at, localization_valid, emergency_stopped,
                 control_ready, linear_velocity, pose_json, status_json)
                VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?)""",
                (
                    str(vehicle.get("device_id") or ""),
                    int(bool(localization.get("valid", snapshot.get("localization_valid", False)))),
                    int(bool(safety.get("emergency_stopped", snapshot.get("emergency_stopped", True)))),
                    int(bool(runtime.get("control_ready", snapshot.get("control_ready", False)))),
                    snapshot.get("linear_velocity"),
                    self._json(pose),
                    self._json(snapshot),
                ),
            )

    def summary(self) -> dict[str, Any]:
        with self._lock, self._session() as connection:
            counts = {}
            for table in ("projects", "design_versions", "planning_tasks", "execution_tasks", "execution_segments", "telemetry", "audit_logs", "ai_case_memory", "device_capabilities"):
                counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            latest = connection.execute(
                "SELECT recorded_at FROM telemetry ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return {
                "ok": True,
                "path": str(self.path),
                "counts": counts,
                "latest_telemetry_at": latest[0] if latest else None,
            }


xline_database = XLineDatabase()
