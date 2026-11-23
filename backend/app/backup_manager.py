"""Consistent, verifiable backups for the rover's persistent stores.

SQLite's ``backup()`` gives a transactionally consistent main database, but
``xline.db`` is not the only state that matters.  Task/run/plan JSON files,
the JSONL audit mirror, CAD/attachments and model configuration can change
independently.  This module writes one timestamped backup directory containing:

* a copied SQLite database (via ``XLINE_DATABASE_PATH``/``xline_database``);
* every other configured persistent file and directory;
* a ``manifest.json`` with source, relative name, size and SHA256 for each
  entry, plus the state of SQLite WAL/SHM sidecars at copy time.

Restores are deliberately dry-run by default and only work inside an explicitly
authorized restore root.  Production paths are never valid restore targets.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

BACKUP_FORMAT = "xline-backup-v1"
BACKUP_ROOT_ENV = "XLINE_BACKUP_ROOT"
BACKUP_RETENTION_ENV = "XLINE_BACKUP_RETENTION"
RESTORE_ALLOWED_ENV = "XLINE_RESTORE_ALLOWED"
RESTORE_ROOT_ENV = "XLINE_RESTORE_ROOT"

_STATE_FILE_ENVS = (
    "XLINE_CREATIVE_PROJECT_STORE",
    "XLINE_AGENT_TASK_STORE",
    "XLINE_AGENT_RUN_STORE",
    "XLINE_AGENT_PLAN_STORE",
    "XLINE_AGENT_AUDIT_STORE",
    "XLINE_AGENT_MEMORY_STORE",
    "XLINE_MISSION_LEDGER_STORE",
    "XLINE_DRAWING_VERSION_STORE",
    "XLINE_AGENT_AUDIT_HEALTH_STORE",
)
_STATE_DIR_ENVS = (
    "XLINE_AGENT_ATTACHMENTS_DIR",
    "XLINE_PLANNED_RESULTS_DIR",
    "XLINE_CAD_DIR",
)
_CONFIG_FILE_ENVS = (
    "XLINE_AGENT_USER_CONFIG_PATH",
    "XLINE_AGENT_MODEL_CONFIG_PATH",
)


class BackupError(RuntimeError):
    pass


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _state_root() -> Path:
    configured = os.getenv("XLINE_STATE_DIR", "").strip()
    if configured:
        return Path(configured)
    try:
        from .database import xline_database

        return Path(xline_database.path).parent
    except Exception:
        return Path(tempfile.gettempdir()) / "xline-agent"


def _config_root() -> Path:
    configured = os.getenv("XLINE_CONFIG_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path.home() / ".config"


def _workspace_root() -> Path:
    for name in ("XLINE_WS_ROOT", "XLINE_WS_DIR"):
        configured = os.getenv(name, "").strip()
        if configured:
            return Path(configured)
    return Path(tempfile.gettempdir()) / "xline-workspace"


def _default_for_env(name: str) -> Path | None:
    state = _state_root()
    config = _config_root()
    workspace = _workspace_root()
    defaults = {
        "XLINE_CREATIVE_PROJECT_STORE": state / "creative_projects.json",
        "XLINE_AGENT_TASK_STORE": state / "tasks.json",
        "XLINE_AGENT_RUN_STORE": state / "agent_runs.json",
        "XLINE_AGENT_PLAN_STORE": state / "agent_plans.sqlite3",
        "XLINE_AGENT_AUDIT_STORE": state / "agent_audit.jsonl",
        "XLINE_AGENT_AUDIT_HEALTH_STORE": state / "agent_audit_health.json",
        "XLINE_AGENT_MEMORY_STORE": state / "conversation_memory.json",
        "XLINE_MISSION_LEDGER_STORE": state / "mission_ledger.json",
        "XLINE_DRAWING_VERSION_STORE": state / "drawing_versions.json",
        "XLINE_AGENT_ATTACHMENTS_DIR": state / "attachments",
        "XLINE_PLANNED_RESULTS_DIR": workspace / "planned_results",
        "XLINE_CAD_DIR": workspace / "cad",
        "XLINE_AGENT_USER_CONFIG_PATH": config / "xline-agent-users.json",
        "XLINE_AGENT_MODEL_CONFIG_PATH": config / "xline-agent.json",
    }
    return defaults.get(name)


def _configured_path(name: str) -> Path | None:
    raw = os.getenv(name, "").strip()
    return Path(raw) if raw else _default_for_env(name)


def _collect_sources(database=None) -> dict[str, Path | None]:
    sources: dict[str, Path | None] = {}
    try:
        if database is None:
            from .database import xline_database as database
        sources["database"] = Path(database.path)
    except Exception:
        raw_db = os.getenv("XLINE_DATABASE_PATH", "").strip()
        sources["database"] = Path(raw_db) if raw_db else None
    for name in _STATE_FILE_ENVS + _STATE_DIR_ENVS + _CONFIG_FILE_ENVS:
        sources[name] = _configured_path(name)
    return sources


def _relative_name(source: Path, index: int) -> str:
    name = source.name or f"item-{index}"
    return name.replace("\\", "_").replace("/", "_")


def _copytree(source: Path, destination: Path, backup_root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    destination.mkdir(parents=True, exist_ok=True)
    for item in sorted(source.rglob("*")):
        relative = item.relative_to(source)
        target = destination / relative
        if item.is_symlink():
            entries.append({
                "relative": target.relative_to(backup_root).as_posix(),
                "source": str(item),
                "type": "symlink",
                "skipped": True,
            })
            continue
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        entries.append({
            "relative": target.relative_to(backup_root).as_posix(),
            "source": str(item),
            "type": "file",
            "size_bytes": target.stat().st_size,
            "sha256": _sha256(target),
        })
    return entries


def _write_manifest(path: Path, payload: dict[str, Any]) -> str:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    digest = _sha256(path)
    (path.parent / "manifest.sha256").write_text(digest + "\n", encoding="ascii")
    return digest


def _verify_sqlite(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"ok": False, "error": "missing_database"}
    try:
        connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
        try:
            checks = [str(row[0]) for row in connection.execute("PRAGMA integrity_check").fetchall()]
        finally:
            connection.close()
    except sqlite3.Error as error:
        return {"ok": False, "error": str(error)}
    return {"ok": bool(checks and checks[0] == "ok"), "checks": checks}


def _chmod_tree(root: Path) -> None:
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    for item in root.rglob("*"):
        try:
            os.chmod(item, 0o600 if item.is_file() else 0o700)
        except OSError:
            pass


def _retention_count() -> int:
    try:
        return max(1, min(100, int(os.getenv(BACKUP_RETENTION_ENV, "5"))))
    except ValueError:
        return 5


def _prune_backups(root: Path, keep: int) -> list[str]:
    candidates = sorted(
        [item for item in root.iterdir() if item.is_dir() and item.name.startswith("backup-")],
        key=lambda item: item.name,
    )
    removed: list[str] = []
    for item in candidates[:-keep] if len(candidates) > keep else []:
        shutil.rmtree(item, ignore_errors=True)
        removed.append(item.name)
    return removed


class BackupManager:
    def create_backup(self, *, prefix: str = "backup", database=None, audit=None) -> dict[str, Any]:
        root = Path(os.getenv(BACKUP_ROOT_ENV, "").strip() or (_state_root() / "backups"))
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        final = root / f"{prefix}-{stamp}-{os.getpid()}"
        staging = Path(tempfile.mkdtemp(prefix=".backup-staging-", dir=root))
        entries: list[dict[str, Any]] = []
        sidecars: dict[str, Any] = {}
        database_info: dict[str, Any] = {}
        try:
            sources = _collect_sources(database)
            db_source = sources.get("database")
            if db_source is not None:
                db_target = staging / "xline.db"
                database_obj = database
                if database_obj is None:
                    from .database import xline_database as database_obj
                result = database_obj.backup(db_target)
                database_info = {
                    "source": str(db_source),
                    "relative": "xline.db",
                    "result": result,
                    "integrity": _verify_sqlite(db_target),
                }
                if db_target.exists():
                    entries.append({
                        "relative": "xline.db",
                        "source": str(db_source),
                        "type": "file",
                        "size_bytes": db_target.stat().st_size,
                        "sha256": _sha256(db_target),
                    })
                for suffix in ("-wal", "-shm"):
                    sidecar = Path(str(db_source) + suffix)
                    state = {
                        "source": str(sidecar),
                        "exists": sidecar.exists(),
                        "size_bytes": sidecar.stat().st_size if sidecar.exists() else 0,
                    }
                    if sidecar.exists():
                        # Keep the original WAL/SHM as archived evidence, not
                        # next to the consistent SQLite snapshot.  Copying them
                        # beside xline.db would replay unrelated transactions
                        # into an otherwise consistent backup.
                        relative = f"sidecars/xline.db{suffix}"
                        target = staging / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(sidecar, target)
                        state["sha256"] = _sha256(target)
                        state["relative"] = relative
                        entries.append({
                            "relative": relative,
                            "source": str(sidecar),
                            "type": "file",
                            "size_bytes": target.stat().st_size,
                            "sha256": state["sha256"],
                        })
                    sidecars[suffix.lstrip("-")] = state
            index = 0
            for name, source in sources.items():
                if name == "database" or source is None:
                    continue
                source = Path(source)
                if not source.exists():
                    continue
                index += 1
                relative = _relative_name(source, index)
                if source.is_dir():
                    target = staging / "state" / relative
                    copied = _copytree(source, target, staging)
                    entries.extend(copied)
                elif source.is_file():
                    target = staging / "state" / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    entries.append({
                        "relative": str(target.relative_to(staging)).replace("\\", "/"),
                        "source": str(source),
                        "type": "file",
                        "size_bytes": target.stat().st_size,
                        "sha256": _sha256(target),
                    })
            manifest = {
                "format": BACKUP_FORMAT,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "database": database_info,
                "sidecars": sidecars,
                "entries": entries,
                "source_root": str(_state_root()),
            }
            manifest_digest = _write_manifest(staging / "manifest.json", manifest)
            _chmod_tree(staging)
            if final.exists():
                shutil.rmtree(final, ignore_errors=True)
            staging.rename(final)
            removed = _prune_backups(root, _retention_count())
            result = {
                "ok": True,
                "format": BACKUP_FORMAT,
                "path": str(final / "xline.db") if (final / "xline.db").exists() else str(final / "manifest.json"),
                "backup_dir": str(final),
                "manifest_sha256": manifest_digest,
                "entries": len(entries),
                "database": database_info,
                "sidecars": sidecars,
                "pruned": removed,
            }
            if audit is not None:
                try:
                    audit.append("backup_created", "backup_manager", {"backup_dir": str(final)}, {"ok": True})
                except Exception:
                    pass
            return result
        except Exception as error:
            shutil.rmtree(staging, ignore_errors=True)
            raise BackupError(str(error)) from error


def _safe_entry_path(root: Path, relative: str) -> Path:
    """Resolve a manifest entry without allowing traversal or symlink escape."""
    candidate = Path(relative)
    if not relative or candidate.is_absolute() or ".." in candidate.parts:
        raise BackupError(f"unsafe relative path: {relative}")
    resolved_root = root.resolve()
    resolved = (root / candidate).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise BackupError(f"entry escapes backup root: {relative}")
    return resolved


def verify_backup(backup_dir: str | Path) -> dict[str, Any]:
    root = Path(backup_dir)
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return {"ok": False, "error": "missing_manifest"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {"ok": False, "error": f"invalid_manifest: {error}"}
    errors: list[str] = []
    checked = 0
    for entry in manifest.get("entries", []):
        relative = str(entry.get("relative", ""))
        if entry.get("type") == "symlink" or entry.get("skipped"):
            errors.append(f"symlink:{relative}")
            continue
        try:
            target = _safe_entry_path(root, relative)
        except BackupError:
            errors.append(f"unsafe_relative:{relative}")
            continue
        if not target.exists():
            errors.append(f"missing:{relative}")
            continue
        if entry.get("sha256") and _sha256(target) != entry["sha256"]:
            errors.append(f"sha256:{relative}")
        checked += 1
    db_integrity = _verify_sqlite(root / "xline.db")
    if not db_integrity.get("ok"):
        errors.append(f"database_integrity:{db_integrity.get('error', 'failed')}")
    expected_manifest = (root / "manifest.sha256")
    if expected_manifest.exists():
        expected = expected_manifest.read_text(encoding="ascii").strip()
        if expected != _sha256(manifest_path):
            errors.append("manifest_sha256")
    return {"ok": not errors, "checked": checked, "errors": errors, "database": db_integrity, "format": manifest.get("format")}


def restore_backup(
    backup_dir: str | Path,
    target_root: str | Path,
    *,
    dry_run: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    root = Path(backup_dir)
    target = Path(target_root)
    if not _env_flag(RESTORE_ALLOWED_ENV):
        raise BackupError("restore is disabled; set XLINE_RESTORE_ALLOWED=1 only in an isolated drill")
    allowed_root = os.getenv(RESTORE_ROOT_ENV, "").strip()
    if not allowed_root:
        raise BackupError("XLINE_RESTORE_ROOT is required for restore drills")
    if not _inside(Path(allowed_root), target):
        raise BackupError("restore target is outside the authorized restore root")
    backup_root = os.getenv(BACKUP_ROOT_ENV, "").strip()
    trusted_backup_root = Path(backup_root) if backup_root else root.parent
    if not (_inside(trusted_backup_root, root) or _inside(Path(allowed_root), root)):
        raise BackupError("backup source is outside the authorized backup/restore roots")
    verification = verify_backup(root)
    if not verification.get("ok"):
        return {"ok": False, "dry_run": dry_run, "verification": verification, "errors": ["backup_verification_failed"]}
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    plan = []
    for entry in manifest.get("entries", []):
        relative = str(entry.get("relative", ""))
        try:
            source = _safe_entry_path(root, relative)
        except BackupError:
            return {"ok": False, "dry_run": dry_run, "errors": [f"unsafe_relative:{relative}"]}
        if entry.get("type") == "symlink" or entry.get("skipped"):
            continue
        destination = target / relative
        if destination.exists() and not force:
            return {"ok": False, "dry_run": dry_run, "errors": [f"target_exists:{relative}"]}
        plan.append((source, destination))
    if dry_run:
        return {"ok": True, "dry_run": True, "would_restore": len(plan), "verification": verification}
    target.mkdir(parents=True, exist_ok=True)
    for source, destination in plan:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    shutil.copy2(root / "manifest.json", target / "manifest.json")
    if (root / "manifest.sha256").exists():
        shutil.copy2(root / "manifest.sha256", target / "manifest.sha256")
    restored = verify_backup(target)
    return {"ok": bool(restored.get("ok")), "dry_run": False, "restored": len(plan), "verification": restored}


backup_manager = BackupManager()
