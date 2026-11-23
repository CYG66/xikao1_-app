from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from app.audit_store import AgentAuditStore
from app.database import XLineDatabase
from app.startup_guard import (
    StartupAdmissionError,
    assert_startup_admitted,
    startup_recovery_authorized,
)
from startup_preflight import PreflightFailure, build_report, validate_preflight


def _write_sqlite(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE IF NOT EXISTS probe (id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()


def _valid_env(tmp_path: Path) -> dict[str, str]:
    state = tmp_path / "state"
    config = tmp_path / "config"
    workspace = tmp_path / "workspace"
    for directory in (state, config, workspace):
        directory.mkdir(parents=True, exist_ok=True)
    db = state / "xline.db"
    plan = state / "agent_plans.sqlite3"
    _write_sqlite(db)
    _write_sqlite(plan)
    for name in ("tasks.json", "agent_runs.json", "agent_audit.jsonl"):
        (state / name).write_text("", encoding="utf-8")
    return {
        "XLINE_DEPLOYMENT_PROFILE": "production",
        "XLINE_STATE_DIR": str(state),
        "XLINE_CONFIG_DIR": str(config),
        "XLINE_WS_ROOT": str(workspace),
        "XLINE_RUNTIME_PROFILE": "xline_ws3",
        "XLINE_DATABASE_PATH": str(db),
        "XLINE_CREATIVE_PROJECT_STORE": str(state / "creative_projects.json"),
        "XLINE_AGENT_TASK_STORE": str(state / "tasks.json"),
        "XLINE_AGENT_RUN_STORE": str(state / "agent_runs.json"),
        "XLINE_AGENT_PLAN_STORE": str(plan),
        "XLINE_AGENT_AUDIT_STORE": str(state / "agent_audit.jsonl"),
        "XLINE_AGENT_MEMORY_STORE": str(state / "conversation_memory.json"),
        "XLINE_MISSION_LEDGER_STORE": str(state / "mission_ledger.json"),
        "XLINE_DRAWING_VERSION_STORE": str(state / "drawing_versions.json"),
        "XLINE_AGENT_ATTACHMENTS_DIR": str(state / "attachments"),
        "XLINE_PLANNED_RESULTS_DIR": str(workspace / "planned_results"),
        "XLINE_CAD_DIR": str(workspace / "cad"),
        "XLINE_AGENT_USER_CONFIG_PATH": str(config / "xline-agent-users.json"),
        "XLINE_AGENT_MODEL_CONFIG_PATH": str(config / "xline-agent.json"),
        "XLINE_STARTUP_RECOVERY_MODE": "disabled",
        "XLINE_CREATIVE_PROJECT_JSON_IMPORT": "disabled",
    }


def test_preflight_accepts_explicit_isolated_layout_and_creates_nothing(tmp_path):
    env = _valid_env(tmp_path)
    before = {str(path) for path in tmp_path.rglob("*")}
    report = validate_preflight(env, allow_temp_root=True)
    after = {str(path) for path in tmp_path.rglob("*")}
    assert report["ok"] is True
    assert before == after
    assert report["read_only"] is True
    assert report["policy"]["recovery_mode"] == "disabled"
    assert report["policy"]["json_import"] == "disabled"


def test_preflight_rejects_missing_required_store(tmp_path):
    env = _valid_env(tmp_path)
    env.pop("XLINE_AGENT_AUDIT_STORE")
    report = build_report(env, allow_temp_root=True)
    assert report["ok"] is False
    assert any(item["code"].startswith("MISSING_XLINE_AGENT_AUDIT_STORE") for item in report["issues"])


def test_preflight_rejects_integration_profile(tmp_path):
    env = _valid_env(tmp_path)
    env["XLINE_INTEGRATION_PROFILE"] = "1"
    report = build_report(env, allow_temp_root=True)
    assert report["ok"] is False
    assert any(item["code"] == "INTEGRATION_PROFILE" for item in report["issues"])


def test_preflight_rejects_relative_and_outside_root_paths(tmp_path):
    env = _valid_env(tmp_path)
    env["XLINE_AGENT_RUN_STORE"] = "relative-agent-runs.json"
    report = build_report(env, allow_temp_root=True)
    assert report["ok"] is False
    assert any(item["code"].startswith("NOT_ABSOLUTE_") for item in report["issues"])

    env = _valid_env(tmp_path)
    env["XLINE_DATABASE_PATH"] = str(tmp_path / "config" / "outside.db")
    _write_sqlite(Path(env["XLINE_DATABASE_PATH"]))
    report = build_report(env, allow_temp_root=True)
    assert report["ok"] is False
    assert any(item["code"].startswith("OUTSIDE_ROOT_") for item in report["issues"])


def test_preflight_requires_explicit_cad_output_directory(tmp_path):
    env = _valid_env(tmp_path)
    env.pop("XLINE_CAD_DIR")
    report = build_report(env, allow_temp_root=True)
    assert report["ok"] is False
    assert any(item["code"] == "MISSING_XLINE_CAD_DIR" for item in report["issues"])


def test_preflight_rejects_cad_output_outside_workspace(tmp_path):
    env = _valid_env(tmp_path)
    outside = tmp_path / "outside-cad"
    outside.mkdir()
    env["XLINE_CAD_DIR"] = str(outside)
    report = build_report(env, allow_temp_root=True)
    assert report["ok"] is False
    assert any(item["code"] == "OUTSIDE_ROOT_XLINE_CAD_DIR"
               for item in report["issues"])


def test_preflight_rejects_symlinked_cad_output(tmp_path):
    env = _valid_env(tmp_path)
    workspace = Path(env["XLINE_WS_ROOT"])
    target = tmp_path / "real-cad"
    target.mkdir()
    link = workspace / "linked-cad"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is not permitted on this host")
    env["XLINE_CAD_DIR"] = str(link)
    report = build_report(env, allow_temp_root=True)
    assert report["ok"] is False
    assert any(item["code"] == "SYMLINK_XLINE_CAD_DIR"
               for item in report["issues"])


def test_preflight_rejects_symlinked_cad_output_parent(tmp_path):
    env = _valid_env(tmp_path)
    workspace = Path(env["XLINE_WS_ROOT"])
    outside = tmp_path / "outside-parent"
    outside.mkdir()
    link = workspace / "linked-parent"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is not permitted on this host")
    env["XLINE_CAD_DIR"] = str(link / "cad")
    report = build_report(env, allow_temp_root=True)
    assert report["ok"] is False
    assert any(item["code"] == "SYMLINK_COMPONENT_XLINE_CAD_DIR"
               for item in report["issues"])


def test_preflight_rejects_non_sqlite_database_file(tmp_path):
    env = _valid_env(tmp_path)
    Path(env["XLINE_DATABASE_PATH"]).write_text("not a database", encoding="utf-8")
    report = build_report(env, allow_temp_root=True)
    assert report["ok"] is False
    assert any(item["code"].startswith("SQLITE_HEADER_") for item in report["issues"])


def test_preflight_rejects_temp_state_root_in_production(tmp_path):
    env = _valid_env(tmp_path)
    report = build_report(env, allow_temp_root=False)
    assert report["ok"] is False
    assert any(item["code"] == "STATE_ROOT_TEMP" for item in report["issues"])


def test_preflight_rejects_symlinked_store(tmp_path):
    env = _valid_env(tmp_path)
    state = Path(env["XLINE_STATE_DIR"])
    target = state / "real-audit.jsonl"
    target.write_text("", encoding="utf-8")
    link = state / "linked-audit.jsonl"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is not permitted on this host")
    env["XLINE_AGENT_AUDIT_STORE"] = str(link)
    report = build_report(env, allow_temp_root=True)
    assert report["ok"] is False
    assert any(item["code"] == "SYMLINK_XLINE_AGENT_AUDIT_STORE"
               for item in report["issues"])


def test_startup_guard_fails_closed_without_preflight_flag():
    with pytest.raises(StartupAdmissionError):
        assert_startup_admitted({"XLINE_DEPLOYMENT_PROFILE": "production"})
    assert_startup_admitted(
        {
            "XLINE_DEPLOYMENT_PROFILE": "production",
            "XLINE_STARTUP_PREFLIGHT_OK": "1",
        }
    )
    assert_startup_admitted({})


def test_startup_recovery_is_disabled_for_production_by_default():
    assert startup_recovery_authorized(
        {
            "XLINE_DEPLOYMENT_PROFILE": "production",
            "XLINE_STARTUP_RECOVERY_MODE": "disabled",
        }
    ) is False
    assert startup_recovery_authorized(
        {
            "XLINE_DEPLOYMENT_PROFILE": "production",
            "XLINE_STARTUP_RECOVERY_MODE": "authorized",
        }
    ) is True
    assert startup_recovery_authorized({}) is True


def test_project_bundle_upsert_never_deletes_unlisted_projects(tmp_path):
    database = XLineDatabase(tmp_path / "xline.db")
    database.save_project_bundle(
        [
            {"id": "p1", "status": "ready_for_design", "updated_at": "1"},
            {"id": "p2", "status": "ready_for_design", "updated_at": "1"},
        ]
    )
    database.save_project_bundle(
        [{"id": "p1", "status": "designing", "updated_at": "2"}]
    )
    with sqlite3.connect(database.path) as connection:
        rows = connection.execute(
            "SELECT project_id, status FROM projects ORDER BY project_id"
        ).fetchall()
    assert rows == [("p1", "designing"), ("p2", "ready_for_design")]


def test_empty_bundle_is_noop_and_requires_explicit_empty_replacement(tmp_path):
    database = XLineDatabase(tmp_path / "xline.db")
    database.save_project_bundle(
        [{"id": "p1", "status": "ready_for_design", "updated_at": "1"}]
    )
    database.save_project_bundle([])
    with sqlite3.connect(database.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
    with pytest.raises(ValueError, match="allow_empty_replace"):
        database.save_project_bundle([], replace_all=True)


def test_nonproduction_full_replacement_remains_available_for_offline_migration(tmp_path):
    database = XLineDatabase(tmp_path / "xline.db")
    database.save_project_bundle(
        [
            {"id": "p1", "status": "ready_for_design", "updated_at": "1"},
            {"id": "p2", "status": "ready_for_design", "updated_at": "1"},
        ]
    )
    database.save_project_bundle(
        [{"id": "p2", "status": "ready_for_design", "updated_at": "2"}],
        replace_all=True,
    )
    with sqlite3.connect(database.path) as connection:
        rows = connection.execute(
            "SELECT project_id, updated_at FROM projects ORDER BY project_id"
        ).fetchall()
    assert rows == [("p2", "2")]


def test_explicit_delete_removes_only_the_named_project(tmp_path):
    database = XLineDatabase(tmp_path / "xline.db")
    database.save_project_bundle(
        [
            {"id": "p1", "status": "ready_for_design", "updated_at": "1"},
            {"id": "p2", "status": "ready_for_design", "updated_at": "1"},
            {"id": "p3", "status": "ready_for_design", "updated_at": "1"},
        ]
    )
    database.save_project_bundle([], deleted_project_ids=["p2"])
    with sqlite3.connect(database.path) as connection:
        rows = connection.execute(
            "SELECT project_id FROM projects ORDER BY project_id"
        ).fetchall()
    assert rows == [("p1",), ("p3",)]


def test_production_rejects_nonempty_and_empty_full_replacement(tmp_path, monkeypatch):
    monkeypatch.setenv("XLINE_DEPLOYMENT_PROFILE", "production")
    monkeypatch.setenv("XLINE_STARTUP_PREFLIGHT_OK", "1")
    database = XLineDatabase(tmp_path / "xline.db")
    database.save_project_bundle(
        [{"id": "p1", "status": "ready_for_design", "updated_at": "1"}]
    )
    with pytest.raises(RuntimeError, match="replace_all=True is prohibited"):
        database.save_project_bundle(
            [{"id": "p2", "status": "ready_for_design", "updated_at": "2"}],
            replace_all=True,
        )
    with pytest.raises(RuntimeError, match="replace_all=True is prohibited"):
        database.save_project_bundle(
            [], replace_all=True, allow_empty_replace=True
        )
    with sqlite3.connect(database.path) as connection:
        rows = connection.execute(
            "SELECT project_id FROM projects ORDER BY project_id"
        ).fetchall()
    assert rows == [("p1",)]


def test_delete_project_removes_its_planning_row(tmp_path):
    database = XLineDatabase(tmp_path / "xline.db")
    database.save_project_bundle([{
        "id": "p1",
        "status": "ready_for_design",
        "updated_at": "1",
        "planning": {"status": "ready"},
    }])
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM planning_tasks WHERE project_id = 'p1'"
        ).fetchone()[0] == 1
    database.delete_project("p1")
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM projects WHERE project_id = 'p1'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM planning_tasks WHERE project_id = 'p1'"
        ).fetchone()[0] == 0


def test_overlapping_upsert_and_delete_is_rejected(tmp_path):
    database = XLineDatabase(tmp_path / "xline.db")
    database.save_project_bundle(
        [{"id": "p1", "status": "ready_for_design", "updated_at": "1"}]
    )
    with pytest.raises(ValueError, match="both upserted and deleted"):
        database.save_project_bundle(
            [{"id": "p1", "status": "designing", "updated_at": "2"}],
            deleted_project_ids=["p1"],
        )


def test_audit_sqlite_authority_and_jsonl_mirror_share_id(tmp_path, monkeypatch):
    database = XLineDatabase(tmp_path / "xline.db")
    monkeypatch.setattr("app.audit_store.xline_database", database)
    path = tmp_path / "audit.jsonl"
    store = AgentAuditStore(path)
    record = store.append("tool_executed", "example", {"value": 1}, {"ok": True})
    with sqlite3.connect(database.path) as connection:
        event_id = connection.execute(
            "SELECT event_id FROM audit_logs"
        ).fetchone()[0]
    assert event_id == record["id"]
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[0])["id"] == record["id"]
    assert store.health_status()["degraded"] is False


def test_audit_sqlite_failure_is_visible_but_jsonl_still_written(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.audit_store.xline_database.record_audit",
        lambda _record: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    path = tmp_path / "audit.jsonl"
    store = AgentAuditStore(path)
    record = store.append("tool_executed", "example", {}, {"ok": True})
    health = store.health_status()
    assert record["id"]
    assert path.read_text(encoding="utf-8").strip()
    assert health["degraded"] is True
    assert health["sqlite_failures"] == 1
    assert health["jsonl_failures"] == 0
    assert health["last_error"]["ledger"] == "sqlite"


def test_audit_degraded_is_sticky_until_explicit_reconciliation(tmp_path, monkeypatch):
    database = XLineDatabase(tmp_path / "xline.db")
    monkeypatch.setattr("app.audit_store.xline_database", database)
    original = database.record_audit
    calls = {"count": 0}

    def flaky(record):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("db down once")
        return original(record)

    monkeypatch.setattr("app.audit_store.xline_database.record_audit", flaky)
    path = tmp_path / "audit.jsonl"
    store = AgentAuditStore(path)
    store.append("tool_executed", "first", {}, {"ok": True})
    store.append("tool_executed", "second", {}, {"ok": True})
    health = store.health_status()
    assert calls["count"] == 2
    assert health["append_count"] == 2
    assert health["sqlite_failures"] == 1
    assert health["jsonl_failures"] == 0
    assert health["degraded"] is True
    assert health["reconciliation_required"] is True
    assert health["degraded_since"]
    assert health["last_error"]["record_id"]
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    with sqlite3.connect(database.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 1
    store.mark_reconciled("reviewed JSONL/SQLite divergence and accepted the missing row")
    health = store.health_status()
    assert health["degraded"] is False
    assert health["reconciliation_required"] is False
    assert health["sqlite_failures"] == 1
    assert health["last_reconciled_at"]
    with pytest.raises(ValueError, match="note is required"):
        store.mark_reconciled("  ")


def test_audit_jsonl_failure_is_visible_but_sqlite_still_written(tmp_path, monkeypatch):
    database = XLineDatabase(tmp_path / "xline.db")
    monkeypatch.setattr("app.audit_store.xline_database", database)
    store = AgentAuditStore(tmp_path)
    store.path = tmp_path  # a directory is not an appendable file
    record = store.append("tool_executed", "example", {}, {"ok": True})
    health = store.health_status()
    assert record["id"]
    with sqlite3.connect(database.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 1
    assert health["degraded"] is True
    assert health["jsonl_failures"] >= 1
    assert health["sqlite_failures"] == 0
    assert health["last_error"]["ledger"] == "jsonl"
