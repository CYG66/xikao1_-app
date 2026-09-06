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


class MissionLedgerStore:
    def __init__(self, path: Path | None = None) -> None:
        self._database_enabled = path is None
        configured = os.getenv("XLINE_MISSION_LEDGER_STORE", "").strip()
        default_root = (
            Path(tempfile.gettempdir()) / "xline-agent"
            if os.name == "nt"
            else Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))
            / "xline-agent"
        )
        self.path = path or (Path(configured) if configured else default_root / "mission_ledger.json")
        self._lock = threading.RLock()
        self._missions: dict[str, dict[str, Any]] = {}
        self._load()
        self._interrupt_running()

    def create(self, file_name: str, summary: dict[str, Any], segments: list[dict[str, Any]], classify: Any,
               quality: dict[str, Any] | None = None, drawing_version: dict[str, Any] | None = None,
               planned_paths: list[dict[str, Any]] | None = None,
               project_id: str | None = None) -> dict[str, Any]:
        now = utc_now()
        mission_id = str(uuid.uuid4())
        mission = {
            "id": mission_id,
            "file_name": file_name,
            "state": "ready",
            "created_at": now,
            "updated_at": now,
            "summary": deepcopy(summary),
            "quality": deepcopy(quality or {}),
            "drawing_version": deepcopy(drawing_version),
            "project_id": project_id or (drawing_version or {}).get("project_id"),
            "planned_paths": deepcopy(planned_paths or []),
            "planned_segments": deepcopy(segments),
            "actual_trace": [],
            "oscillation_events": [],
            "report": None,
            "segments": [
                {
                    "index": index,
                    "segment_id": segment.get("id"),
                    "kind": classify(segment),
                    "printer": str(segment.get("ink", {}).get("printer", "center")).lower()
                    if isinstance(segment.get("ink"), dict) else None,
                    "state": "pending",
                    "started_at": None,
                    "completed_at": None,
                    "precheck": None,
                    "postcheck": None,
                    "verification": None,
                }
                for index, segment in enumerate(segments)
            ],
        }
        with self._lock:
            self._missions[mission_id] = mission
            self._save()
        return deepcopy(mission)

    def set_mission_state(self, mission_id: str, state: str) -> None:
        with self._lock:
            mission = self._missions.get(mission_id)
            if mission is None:
                return
            mission["state"] = state
            mission["updated_at"] = utc_now()
            self._save()

    def start_segment(self, mission_id: str, index: int) -> None:
        self._update_segment(mission_id, index, "executing", started_at=utc_now())

    def record_precheck(self, mission_id: str, index: int, check: dict[str, Any]) -> None:
        self._update_segment(mission_id, index, "pending", precheck=deepcopy(check))

    def verify_segment(self, mission_id: str, index: int, verification: dict[str, Any]) -> None:
        state = "completed" if verification.get("ok") is True else "failed"
        self._update_segment(
            mission_id, index, state, completed_at=utc_now(), postcheck=deepcopy(verification),
            verification=deepcopy(verification)
        )

    def append_oscillation(self, mission_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            mission = self._missions.get(mission_id)
            if mission is not None:
                mission.setdefault("oscillation_events", []).append(deepcopy(event))
                mission["updated_at"] = utc_now()
                self._save()

    def set_report(self, mission_id: str, report: dict[str, Any]) -> None:
        with self._lock:
            mission = self._missions.get(mission_id)
            if mission is not None:
                mission["report"] = deepcopy(report)
                mission["updated_at"] = utc_now()
                self._save()

    def set_actual_trace(self, mission_id: str, trace: list[list[float]]) -> None:
        with self._lock:
            mission = self._missions.get(mission_id)
            if mission is not None:
                mission["actual_trace"] = deepcopy(trace)
                mission["updated_at"] = utc_now()
                self._save()

    def reports(self, limit: int = 50) -> list[dict[str, Any]]:
        return [item["report"] for item in self.list(limit) if isinstance(item.get("report"), dict)]

    def get(self, mission_id: str) -> dict[str, Any] | None:
        with self._lock:
            mission = self._missions.get(mission_id)
            return deepcopy(mission) if mission is not None else None

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            values = sorted(self._missions.values(), key=lambda item: item["created_at"], reverse=True)
            return deepcopy(values[: max(1, min(limit, 200))])

    def _update_segment(self, mission_id: str, index: int, state: str, **values: Any) -> None:
        with self._lock:
            mission = self._missions.get(mission_id)
            if mission is None or not 0 <= index < len(mission["segments"]):
                return
            segment = mission["segments"][index]
            segment["state"] = state
            segment.update(values)
            mission["updated_at"] = utc_now()
            self._save()

    def _interrupt_running(self) -> None:
        with self._lock:
            changed = False
            for mission in self._missions.values():
                if mission.get("state") != "executing":
                    continue
                mission["state"] = "interrupted"
                mission["updated_at"] = utc_now()
                for segment in mission.get("segments", []):
                    if segment.get("state") == "executing":
                        segment["state"] = "interrupted"
                changed = True
            if changed:
                self._save()

    def _load(self) -> None:
        if self._database_enabled:
            stored = xline_database.load_execution_tasks()
            if stored:
                self._missions = {
                    str(item["id"]): item for item in stored
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                }
                return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self._missions = {
                str(item["id"]): item for item in payload.get("missions", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            if self._database_enabled:
                for item in self._missions.values():
                    xline_database.save_execution_task(item)
        except (OSError, ValueError, TypeError):
            self._missions = {}

    def _save(self) -> None:
        if self._database_enabled:
            for mission in self._missions.values():
                xline_database.save_execution_task(mission)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(
            {"schema_version": "1.0", "missions": list(self._missions.values())},
            ensure_ascii=False, indent=2,
        ), encoding="utf-8")
        os.replace(temporary, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass


mission_ledger = MissionLedgerStore()
