"""P0-05 backup, verification, corruption detection and isolated restore drill."""
from __future__ import annotations

import json
import sqlite3

import pytest

from app.audit_store import AgentAuditStore
from app.backup_manager import BackupManager, verify_backup, restore_backup, BackupError
from app.database import XLineDatabase


@pytest.fixture()
def stores(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    workspace = tmp_path / "workspace"
    (workspace / "planned_results").mkdir(parents=True)
    (workspace / "cad").mkdir(parents=True)
    (state / "attachments").mkdir()
    (state / "attachments" / "part.step").write_text("solid part", encoding="utf-8")
    (workspace / "planned_results" / "plan.json").write_text('{"ok": true}', encoding="utf-8")
    (workspace / "cad" / "drawing.json").write_text('{"lines": []}', encoding="utf-8")
    (config / "xline-agent.json").write_text('{"provider": "local"}', encoding="utf-8")
    monkeypatch.setenv("XLINE_STATE_DIR", str(state))
    monkeypatch.setenv("XLINE_CONFIG_DIR", str(config))
    monkeypatch.setenv("XLINE_WS_ROOT", str(workspace))
    monkeypatch.setenv("XLINE_DATABASE_PATH", str(state / "xline.db"))
    monkeypatch.setenv("XLINE_AGENT_ATTACHMENTS_DIR", str(state / "attachments"))
    monkeypatch.setenv("XLINE_PLANNED_RESULTS_DIR", str(workspace / "planned_results"))
    monkeypatch.setenv("XLINE_CAD_DIR", str(workspace / "cad"))
    monkeypatch.setenv("XLINE_AGENT_MODEL_CONFIG_PATH", str(config / "xline-agent.json"))
    database = XLineDatabase(state / "xline.db")
    database.record_audit(
        {
            "id": "audit-1",
            "event_id": "audit-1",
            "type": "tool_executed",
            "actor": "backup-test",
            "payload": {},
            "result": {"ok": True},
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    )
    audit = AgentAuditStore(state / "agent_audit.jsonl")
    audit.append("tool_executed", "backup-test", {}, {"ok": True})
    return database, audit, state, workspace


def test_full_store_backup_verify_corruption_and_restore(stores, tmp_path, monkeypatch):
    database, audit, state, workspace = stores
    backup_root = tmp_path / "backups"
    restore_root = tmp_path / "restore-root"
    deliver_root = restore_root / "drill"
    monkeypatch.setenv("XLINE_BACKUP_ROOT", str(backup_root))
    monkeypatch.setenv("XLINE_RESTORE_ALLOWED", "1")
    monkeypatch.setenv("XLINE_RESTORE_ROOT", str(restore_root))
    manager = BackupManager()
    result = manager.create_backup(database=database, audit=audit)

    assert result["ok"] is True
    assert result["database"]["integrity"]["ok"] is True
    backup_dir = result["backup_dir"]
    manifest = json.loads((tmp_path / "backups" / result["backup_dir"].split("\\")[-1] / "manifest.json").read_text(encoding="utf-8"))
    assert "state/attachments/part.step" in [entry["relative"] for entry in manifest["entries"]]
    assert any(item.startswith("state/planned_results") for item in [entry["relative"] for entry in manifest["entries"]])
    # The snapshot may carry an empty WAL created by SQLite itself, but no
    # non-empty original WAL is replayed into the consistent snapshot.
    active_wal = tmp_path / "backups" / result["backup_dir"].split("\\")[-1] / "xline.db-wal"
    if active_wal.exists():
        assert active_wal.stat().st_size == 0
    if manifest["sidecars"].get("wal", {}).get("exists"):
        assert manifest["sidecars"]["wal"]["relative"] == "sidecars/xline.db-wal"
        assert "sidecars/xline.db-wal" in [entry["relative"] for entry in manifest["entries"]]

    verified = verify_backup(backup_dir)
    assert verified["ok"] is True, verified
    assert verified["checked"] >= 4

    copied = backup_dir + "/state/attachments/part.step"
    with open(copied, "w", encoding="utf-8") as handle:
        handle.write("tampered")
    broken = verify_backup(backup_dir)
    assert broken["ok"] is False
    assert any(item.startswith("sha256:") for item in broken["errors"])

    restore_source = manager.create_backup(prefix="restore", database=database, audit=audit)["backup_dir"]
    dry = restore_backup(restore_source, deliver_root, dry_run=True)
    assert dry["ok"] is True
    assert dry["dry_run"] is True
    assert not deliver_root.exists()

    restored = restore_backup(restore_source, deliver_root, dry_run=False)
    assert restored["ok"] is True, restored
    assert (deliver_root / "xline.db").exists()
    assert (deliver_root / "state" / "attachments" / "part.step").exists()
    assert (deliver_root / "state" / "attachments" / "part.step").read_text(encoding="utf-8") == "solid part"
    with sqlite3.connect(deliver_root / "xline.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 1
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert verify_backup(deliver_root)["ok"] is True


def test_restore_requires_explicit_authorization_and_isolated_root(stores, tmp_path, monkeypatch):
    database, audit, _, _ = stores
    backup_root = tmp_path / "backups"
    monkeypatch.setenv("XLINE_BACKUP_ROOT", str(backup_root))
    manager = BackupManager()
    result = manager.create_backup(database=database, audit=audit)
    with pytest.raises(BackupError):
        restore_backup(result["backup_dir"], tmp_path / "target", dry_run=True)
    monkeypatch.setenv("XLINE_RESTORE_ALLOWED", "1")
    monkeypatch.setenv("XLINE_RESTORE_ROOT", str(tmp_path / "allowed"))
    with pytest.raises(BackupError):
        restore_backup(result["backup_dir"], tmp_path / "target", dry_run=True)


def test_backup_verification_rejects_traversal_and_symlink_entries(tmp_path):
    root = tmp_path / "backup"
    root.mkdir()
    manifest = {
        "format": "xline-backup-v1",
        "entries": [
            {"relative": "../escape.txt", "type": "file", "sha256": "0" * 64},
            {"relative": "state/link", "type": "symlink", "skipped": True},
        ],
        "database": {},
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = verify_backup(root)
    assert result["ok"] is False
    assert any(item.startswith("unsafe_relative:") for item in result["errors"])
    assert "symlink:state/link" in result["errors"]
