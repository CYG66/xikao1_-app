from __future__ import annotations

import hashlib
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


class DrawingVersionStore:
    def __init__(self, path: Path | None = None) -> None:
        self._database_enabled = path is None
        configured = os.getenv("XLINE_DRAWING_VERSION_STORE", "").strip()
        root = Path(tempfile.gettempdir()) / "xline-agent"
        self.path = path or (Path(configured) if configured else root / "drawing_versions.json")
        self._lock = threading.RLock()
        self._items: list[dict[str, Any]] = []
        self._payloads: dict[str, dict[str, Any]] = {}
        self._load()

    def save(self, directory: Path, requested_name: str, payload: dict[str, Any], source: str,
             change_summary: str = "") -> dict[str, Any]:
        stem = Path(requested_name).stem
        existing = [item for item in self._items if item.get("base_name") == stem]
        version = max((int(item.get("version", 0)) for item in existing), default=0) + 1
        file_name = f"{stem}_v{version:03d}.json"
        encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        directory.mkdir(parents=True, exist_ok=True)
        (directory / file_name).write_bytes(encoded)
        item = {
            "drawing_id": str(existing[0]["drawing_id"]) if existing else str(uuid.uuid4()),
            "base_name": stem,
            "version": version,
            "file_name": file_name,
            "parent_file_name": existing[-1]["file_name"] if existing else None,
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "source": source,
            "status": "saved",
            "change_summary": change_summary,
            "created_at": utc_now(),
        }
        project_id = payload.get("creative_project_id")
        if project_id:
            item["project_id"] = str(project_id)
        with self._lock:
            self._items.append(item)
            self._payloads[file_name] = deepcopy(payload)
            self._save()
        return deepcopy(item)

    def find_by_file(self, file_name: str) -> dict[str, Any] | None:
        with self._lock:
            item = next((value for value in reversed(self._items) if value.get("file_name") == file_name), None)
            return deepcopy(item) if item else None

    def list(self, drawing_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            values = self._items
            if drawing_id:
                values = [item for item in values if item.get("drawing_id") == drawing_id]
            return deepcopy(sorted(values, key=lambda item: item.get("created_at", ""), reverse=True))

    def restore(self, file_name: str, directory: Path, project_id: str | None = None) -> dict[str, Any] | None:
        """Create a new version from an existing version without overwriting history."""
        with self._lock:
            source = next(
                (item for item in self._items if item.get("file_name") == file_name),
                None,
            )
            payload = deepcopy(self._payloads.get(file_name))
        if source is None or not isinstance(payload, dict):
            return None
        source_project = str(source.get("project_id") or payload.get("creative_project_id") or "")
        if project_id and source_project and source_project != project_id:
            return None
        if project_id and not source_project:
            payload["creative_project_id"] = project_id
        return self.save(
            directory,
            str(source.get("base_name") or Path(file_name).stem),
            payload,
            "rollback",
            f"从图纸版本 {file_name} 回退生成新版本",
        )

    def _load(self) -> None:
        if self._database_enabled:
            stored = xline_database.load_design_versions()
            if stored:
                self._items = []
                for item in stored:
                    payload = item.pop("payload", {})
                    file_name = str(item.get("file_name", ""))
                    self._payloads[file_name] = payload if isinstance(payload, dict) else {}
                    self._items.append(item)
                return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._items = [item for item in data.get("versions", []) if isinstance(item, dict)]
        except (OSError, ValueError, TypeError):
            self._items = []

    def _save(self) -> None:
        if self._database_enabled:
            for item in self._items:
                file_name = str(item.get("file_name", ""))
                xline_database.save_design_version(item, self._payloads.get(file_name, {}))
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"schema_version": "1.0", "versions": self._items},
                                        ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)


drawing_versions = DrawingVersionStore()
