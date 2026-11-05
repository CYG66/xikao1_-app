from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from .task_store import utc_now
from .database import xline_database
from .geometry_diff import build_geometry_diff, build_path_impact


class DuplicateDrawingOperationError(RuntimeError):
    def __init__(self, item: dict[str, Any]) -> None:
        super().__init__(str(item.get("file_name", "")))
        self.item = deepcopy(item)


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
             change_summary: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            metadata = metadata or {}
            operation_id = str(metadata.get("operation_id") or "").strip()
            if operation_id:
                previous = next((value for value in reversed(self._items)
                                 if value.get("operation_id") == operation_id), None)
                if previous:
                    raise DuplicateDrawingOperationError(previous)
            stem = self._base_stem(requested_name)
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
            item.update({key: deepcopy(value) for key, value in metadata.items() if value is not None})
            project_id = payload.get("creative_project_id")
            if project_id:
                item["project_id"] = str(project_id)
            self._items.append(item)
            self._payloads[file_name] = deepcopy(payload)
            self._save()
        return deepcopy(item)

    def save_project_candidate(
        self,
        directory: Path,
        requested_name: str,
        payload: dict[str, Any],
        source: str,
        change_summary: str,
        metadata: dict[str, Any],
        *,
        project_store: Any,
        project_id: str,
        variant_id: str,
    ) -> dict[str, Any]:
        """Persist the drawing version and owning project as one unit of work."""
        with self._lock, project_store._lock:
            operation_id = str(metadata.get("operation_id") or "").strip()
            if operation_id:
                previous = next((value for value in reversed(self._items)
                                 if value.get("operation_id") == operation_id), None)
                if previous:
                    raise DuplicateDrawingOperationError(previous)
            project = project_store._projects.get(project_id)
            if project is None or project.get("deleted_at"):
                raise ValueError("creative project does not exist")
            variant = next((item for item in project.get("variants") or []
                            if str(item.get("id") or "") == variant_id), None)
            if variant is None:
                raise ValueError("candidate variant does not exist")

            stem = self._base_stem(requested_name)
            existing = [item for item in self._items if item.get("base_name") == stem]
            version_number = max((int(item.get("version", 0)) for item in existing), default=0) + 1
            file_name = f"{stem}_v{version_number:03d}.json"
            encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            item = {
                "drawing_id": str(existing[0]["drawing_id"]) if existing else str(uuid.uuid4()),
                "base_name": stem,
                "version": version_number,
                "file_name": file_name,
                "parent_file_name": existing[-1]["file_name"] if existing else None,
                "sha256": hashlib.sha256(encoded).hexdigest(),
                "source": source,
                "status": "saved",
                "change_summary": change_summary,
                "created_at": utc_now(),
                **{key: deepcopy(value) for key, value in metadata.items() if value is not None},
                "project_id": project_id,
            }
            before_items = deepcopy(self._items)
            before_payloads = deepcopy(self._payloads)
            before_projects = deepcopy(project_store._projects)
            before_durable = deepcopy(getattr(project_store, "_durable_projects", {}))
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / file_name
            targets: list[tuple[Path, bytes]] = [(target, encoded)]
            try:
                self._items.append(item)
                self._payloads[file_name] = deepcopy(payload)
                variant["saved_drawing"] = deepcopy(item)
                project["updated_at"] = utc_now()
                if self._database_enabled and project_store._database_enabled:
                    self._replace_file_group(
                        targets,
                        commit=lambda: xline_database.save_project_bundle(
                            list(project_store._projects.values()),
                            [{"item": item, "payload": payload}],
                        ),
                    )
                elif not self._database_enabled and not project_store._database_enabled:
                    drawing_bytes = json.dumps(
                        {"schema_version": "1.0", "versions": self._items},
                        ensure_ascii=False, indent=2,
                    ).encode("utf-8")
                    project_bytes = json.dumps(
                        {"schema_version": "1.0", "projects": list(project_store._projects.values())},
                        ensure_ascii=False, indent=2,
                    ).encode("utf-8")
                    targets.extend([
                        (self.path, drawing_bytes),
                        (project_store.path, project_bytes),
                    ])
                    self._replace_file_group(targets)
                else:
                    raise RuntimeError("project and drawing stores must use the same persistence mode")
            except Exception:
                self._items = before_items
                self._payloads = before_payloads
                project_store._projects = before_projects
                project_store._durable_projects = before_durable
                raise
            project_store._durable_projects = deepcopy(project_store._projects)
            return deepcopy(item)

    def save_project_planning(
        self,
        directory: Path,
        requested_name: str,
        payload: dict[str, Any],
        source: str,
        change_summary: str,
        *,
        project_store: Any,
        project_id: str,
        planning_factory: Any,
        metadata: dict[str, Any] | None = None,
        partition_update: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Save a planning drawing and its project/planning snapshot atomically.

        The final drawing file is made visible before ``planning_factory`` is
        called because the ROS planning adapter reads that file.  If planning
        construction, project mutation, or persistence fails, the drawing,
        version index, project memory, and durable snapshot are all restored.
        """
        metadata = metadata or {}
        with self._lock, project_store._lock:
            operation_id = str(metadata.get("operation_id") or "").strip()
            if operation_id:
                previous = next((value for value in reversed(self._items)
                                 if value.get("operation_id") == operation_id), None)
                if previous:
                    raise DuplicateDrawingOperationError(previous)
            project = project_store._projects.get(project_id)
            if project is None or project.get("deleted_at"):
                raise ValueError("creative project does not exist")

            stem = self._base_stem(requested_name)
            existing = [item for item in self._items if item.get("base_name") == stem]
            version_number = max((int(item.get("version", 0)) for item in existing), default=0) + 1
            file_name = f"{stem}_v{version_number:03d}.json"
            encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            item = {
                "drawing_id": str(existing[0]["drawing_id"]) if existing else str(uuid.uuid4()),
                "base_name": stem,
                "version": version_number,
                "file_name": file_name,
                "parent_file_name": existing[-1]["file_name"] if existing else None,
                "sha256": hashlib.sha256(encoded).hexdigest(),
                "source": source,
                "status": "saved",
                "change_summary": change_summary,
                "created_at": utc_now(),
                **{key: deepcopy(value) for key, value in metadata.items() if value is not None},
                "project_id": project_id,
            }
            before_items = deepcopy(self._items)
            before_payloads = deepcopy(self._payloads)
            before_projects = deepcopy(project_store._projects)
            before_durable = deepcopy(getattr(project_store, "_durable_projects", {}))
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / file_name
            transaction_result: dict[str, Any] = {}

            def commit_project_state() -> None:
                planning = planning_factory(deepcopy(item))
                if not isinstance(planning, dict):
                    raise RuntimeError("planning factory did not return a planning snapshot")
                if isinstance(partition_update, dict):
                    update = deepcopy(partition_update)
                    updates = update.pop("updates", {})
                    if not project_store._apply_variant_partition_segment(
                        project,
                        str(update["variant_id"]),
                        str(update["zone_id"]),
                        str(update["segment_id"]),
                        str(update["status"]),
                        **(updates if isinstance(updates, dict) else {}),
                    ):
                        raise RuntimeError("partition segment update failed")
                if not project_store._apply_planning(project, planning):
                    raise RuntimeError("project planning transition failed")
                self._items.append(item)
                self._payloads[file_name] = deepcopy(payload)
                if self._database_enabled and project_store._database_enabled:
                    xline_database.save_project_bundle(
                        list(project_store._projects.values()),
                        [{"item": item, "payload": payload}],
                    )
                elif not self._database_enabled and not project_store._database_enabled:
                    drawing_bytes = json.dumps(
                        {"schema_version": "1.0", "versions": self._items},
                        ensure_ascii=False, indent=2,
                    ).encode("utf-8")
                    project_bytes = json.dumps(
                        {"schema_version": "1.0", "projects": list(project_store._projects.values())},
                        ensure_ascii=False, indent=2,
                    ).encode("utf-8")
                    self._replace_file_group([
                        (self.path, drawing_bytes),
                        (project_store.path, project_bytes),
                    ])
                else:
                    raise RuntimeError("project and drawing stores must use the same persistence mode")
                transaction_result["planning"] = deepcopy(planning)

            try:
                self._replace_file_group([(target, encoded)], commit=commit_project_state)
            except Exception:
                self._items = before_items
                self._payloads = before_payloads
                project_store._projects = before_projects
                project_store._durable_projects = before_durable
                raise
            project_store._durable_projects = deepcopy(project_store._projects)
            return {
                "drawing_version": deepcopy(item),
                "planning": transaction_result["planning"],
                "project": deepcopy(project_store._projects[project_id]),
            }

    @staticmethod
    def _replace_file_group(
        entries: list[tuple[Path, bytes]], *, commit: Any = None
    ) -> None:
        """Replace several files with rollback if any replacement fails."""
        transaction_id = uuid.uuid4().hex
        originals: dict[Path, bytes | None] = {}
        temporary: list[tuple[Path, Path]] = []
        try:
            for target, payload in entries:
                target.parent.mkdir(parents=True, exist_ok=True)
                originals[target] = target.read_bytes() if target.exists() else None
                staged = target.with_name(f".{target.name}.{transaction_id}.tmp")
                staged.write_bytes(payload)
                temporary.append((staged, target))
            for staged, target in temporary:
                os.replace(staged, target)
            if commit is not None:
                commit()
        except Exception:
            for target, payload in originals.items():
                try:
                    if payload is None:
                        target.unlink(missing_ok=True)
                    else:
                        rollback = target.with_name(f".{target.name}.{transaction_id}.rollback")
                        rollback.write_bytes(payload)
                        os.replace(rollback, target)
                except OSError:
                    pass
            raise
        finally:
            for staged, _ in temporary:
                try:
                    staged.unlink(missing_ok=True)
                except OSError:
                    pass

    def find_by_file(self, file_name: str) -> dict[str, Any] | None:
        with self._lock:
            item = next((value for value in reversed(self._items) if value.get("file_name") == file_name), None)
            return deepcopy(item) if item else None

    def payload(self, file_name: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._payloads.get(file_name)
            return deepcopy(value) if isinstance(value, dict) else None

    def latest_for_file(self, file_name: str) -> dict[str, Any] | None:
        """Return the newest tracked version for a drawing base name."""
        stem = self._base_stem(file_name)
        with self._lock:
            values = [item for item in self._items if item.get("base_name") == stem]
            latest = max(values, key=lambda item: int(item.get("version", 0)), default=None)
            return deepcopy(latest) if latest else None

    def find_by_operation_id(self, operation_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = next(
                (value for value in reversed(self._items) if value.get("operation_id") == operation_id),
                None,
            )
            return deepcopy(item) if item else None

    @staticmethod
    def _base_stem(file_name: str) -> str:
        return re.sub(r"_v\d+$", "", Path(file_name).stem)

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
            latest = max(
                (
                    item
                    for item in self._items
                    if source is not None
                    and item.get("base_name") == source.get("base_name")
                ),
                key=lambda item: int(item.get("version", 0)),
                default=None,
            )
            latest_payload = deepcopy(
                self._payloads.get(str(latest.get("file_name")))
                if latest is not None
                else None
            )
        if source is None or not isinstance(payload, dict):
            return None
        source_project = str(source.get("project_id") or payload.get("creative_project_id") or "")
        if project_id and source_project and source_project != project_id:
            return None
        if project_id and not source_project:
            payload["creative_project_id"] = project_id
        source_lines = (
            latest_payload.get("lines") if isinstance(latest_payload, dict) else []
        )
        target_lines = payload.get("lines") if isinstance(payload, dict) else []
        geometry_diff = build_geometry_diff(
            source_lines if isinstance(source_lines, list) else [],
            target_lines if isinstance(target_lines, list) else [],
        )
        path_impact = build_path_impact(
            source_lines if isinstance(source_lines, list) else [],
            target_lines if isinstance(target_lines, list) else [],
        )
        return self.save(
            directory,
            str(source.get("base_name") or Path(file_name).stem),
            payload,
            "rollback",
            f"从图纸版本 {file_name} 回退生成新版本",
            {
                "rollback_source_file_name": file_name,
                "geometry_diff": geometry_diff,
                "path_impact": path_impact,
            },
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
