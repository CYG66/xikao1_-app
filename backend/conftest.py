"""Fail-closed test isolation guard for every persistent store and hardware entry.

The original guard only protected ``XLINE_DATABASE_PATH``.  Release-blocker-01
extends it so a test run cannot read or write task/run/plan/audit/CAD/attachment
stores or accidentally start a real model/hardware path.  All paths are placed
under one temporary root; any explicit path outside it, or any path that
resolves to the known production database, aborts collection.
"""
from __future__ import annotations

import os
import socket
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _deny_external_network(monkeypatch):
    """Offline-by-default guard for model/provider and remote HTTP sockets.

    Tests that use local fake servers may still use loopback.  A test that
    genuinely needs an external socket must explicitly opt in with
    ``XLINE_ALLOW_EXTERNAL_TEST_NETWORK=1``; the default is fail-closed.
    """
    if os.getenv("XLINE_ALLOW_EXTERNAL_TEST_NETWORK", "").strip() == "1":
        return
    originals = {
        "connect": socket.socket.connect,
        "connect_ex": socket.socket.connect_ex,
    }

    def _allowed(self, address) -> bool:
        if getattr(self, "family", None) == getattr(socket, "AF_UNIX", -1):
            return True
        host = address[0] if isinstance(address, tuple) else address
        text = str(host).strip().strip("[]").lower()
        if text in {"localhost", "127.0.0.1", "::1", "0.0.0.0", ""}:
            return True
        try:
            import ipaddress

            if ipaddress.ip_address(text).is_loopback or ipaddress.ip_address(text).is_unspecified:
                return True
        except ValueError:
            pass
        return False

    def _guard(name):
        original = originals[name]

        def guarded(self, address, *args):
            if not _allowed(self, address):
                raise OSError(
                    "external network is disabled in the isolated test suite; "
                    "use a mock/local server or explicitly opt in"
                )
            return original(self, address, *args)

        return guarded

    monkeypatch.setattr(socket.socket, "connect", _guard("connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", _guard("connect_ex"))


def _platform_default_path() -> Path:
    """Resolve the production default path without importing the app.

    Importing ``app.database`` here would construct the module-level
    ``xline_database`` and initialize the default database before the isolation
    guard runs.  Keep this calculation local and side-effect free.
    """
    if os.name == "nt":
        root = Path(tempfile.gettempdir())
    else:
        state_home = os.getenv("XDG_STATE_HOME", "").strip()
        root = Path(state_home) if state_home else Path.home() / ".local" / "state"
    return root / "xline-agent" / "xline.db"


_PATH_ENVS = (
    "XLINE_DATABASE_PATH",
    "XLINE_CREATIVE_PROJECT_STORE",
    "XLINE_AGENT_TASK_STORE",
    "XLINE_AGENT_RUN_STORE",
    "XLINE_AGENT_PLAN_STORE",
    "XLINE_AGENT_AUDIT_STORE",
    "XLINE_AGENT_AUDIT_HEALTH_STORE",
    "XLINE_AGENT_MEMORY_STORE",
    "XLINE_MISSION_LEDGER_STORE",
    "XLINE_DRAWING_VERSION_STORE",
    "XLINE_AGENT_ATTACHMENTS_DIR",
    "XLINE_PLANNED_RESULTS_DIR",
    "XLINE_CAD_DIR",
    "XLINE_AGENT_USER_CONFIG_PATH",
    "XLINE_AGENT_MODEL_CONFIG_PATH",
    "XLINE_BACKUP_ROOT",
    "XLINE_RESTORE_ROOT",
)

_DEFAULT_NAMES = {
    "XLINE_CREATIVE_PROJECT_STORE": ("state", "creative_projects.json"),
    "XLINE_AGENT_TASK_STORE": ("state", "tasks.json"),
    "XLINE_AGENT_RUN_STORE": ("state", "agent_runs.json"),
    "XLINE_AGENT_PLAN_STORE": ("state", "agent_plans.sqlite3"),
    "XLINE_AGENT_AUDIT_STORE": ("state", "agent_audit.jsonl"),
    "XLINE_AGENT_AUDIT_HEALTH_STORE": ("state", "agent_audit_health.json"),
    "XLINE_AGENT_MEMORY_STORE": ("state", "conversation_memory.json"),
    "XLINE_MISSION_LEDGER_STORE": ("state", "mission_ledger.json"),
    "XLINE_DRAWING_VERSION_STORE": ("state", "drawing_versions.json"),
    "XLINE_AGENT_ATTACHMENTS_DIR": ("state", "attachments"),
    "XLINE_PLANNED_RESULTS_DIR": ("workspace", "planned_results"),
    "XLINE_CAD_DIR": ("workspace", "cad"),
    "XLINE_AGENT_USER_CONFIG_PATH": ("config", "xline-agent-users.json"),
    "XLINE_AGENT_MODEL_CONFIG_PATH": ("config", "xline-agent.json"),
    "XLINE_BACKUP_ROOT": ("state", "backups"),
    "XLINE_RESTORE_ROOT": ("restore",),
}


def _production_database_path() -> Path:
    configured = os.getenv("XLINE_PRODUCTION_DATABASE_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return _platform_default_path().expanduser().resolve()


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root)
        return True
    except ValueError:
        return False


def _guard_candidate(name: str, candidate: Path, root: Path, production: Path) -> None:
    production_root = production.parent
    if candidate == production or _inside(production_root, candidate):
        raise pytest.UsageError(
            f"{name} resolves into the known production state; tests must use the isolated root"
        )
    if not _inside(root, candidate):
        raise pytest.UsageError(
            f"{name} is outside the test isolation root; refusing to touch {candidate}"
        )


def _guard_paths(root: Path, production: Path, database: Path | None = None) -> None:
    for name in _PATH_ENVS:
        if name == "XLINE_DATABASE_PATH" and database is not None:
            continue
        raw = os.getenv(name, "").strip()
        if not raw:
            continue
        _guard_candidate(name, Path(raw).expanduser().resolve(), root, production)
    if database is not None:
        _guard_candidate("XLINE_DATABASE_PATH (effective)", database, root, production)


def _guard_isolation_root(root: Path, production: Path) -> None:
    """Reject a root inside the production state tree before any mkdir."""
    if _inside(production.parent, root):
        raise pytest.UsageError(
            "XLINE_TEST_ISOLATION_ROOT resolves into the known production state; "
            "tests must use a separate isolated root"
        )
    if root.exists() and not root.is_dir():
        raise pytest.UsageError(
            f"XLINE_TEST_ISOLATION_ROOT is not a directory: refusing to use {root}"
        )


def pytest_configure(config) -> None:
    production = _production_database_path()
    raw_database = os.getenv("XLINE_DATABASE_PATH", "").strip()
    raw_root = os.getenv("XLINE_TEST_ISOLATION_ROOT", "").strip()
    if not raw_database and not raw_root:
        raise pytest.UsageError(
            "XLINE_DATABASE_PATH or XLINE_TEST_ISOLATION_ROOT must be set explicitly for tests; "
            "refusing to fall back to the production database."
        )
    if raw_root:
        root = Path(raw_root).expanduser().resolve()
    else:
        root = Path(raw_database).expanduser().resolve().parent

    # Compute and validate the effective database path even when the caller
    # supplied only an isolation root.  No directory is created yet.
    database = (
        Path(raw_database).expanduser().resolve()
        if raw_database
        else root / "xline.db"
    )
    if database == production or _inside(production.parent, database):
        raise pytest.UsageError(
            "XLINE_DATABASE_PATH resolves to the known production database; "
            "tests must use a separate isolated database."
        )
    _guard_isolation_root(root, production)
    if not _inside(root, database):
        if config is None:
            # Legacy unit tests call this hook directly with a temporary database
            # outside the session root; keep their explicit database check but
            # do not redirect an already-running suite.
            root = database.parent
            _guard_isolation_root(root, production)
        else:
            raise pytest.UsageError("XLINE_DATABASE_PATH is outside the test isolation root")

    # Validate every explicit store before creating anything on disk.
    _guard_paths(root, production, database)
    root.mkdir(parents=True, exist_ok=True)
    if not raw_database:
        os.environ["XLINE_DATABASE_PATH"] = str(database)
    os.environ["XLINE_TEST_ISOLATION_ROOT"] = str(root)
    os.environ["XLINE_INTEGRATION_ISOLATION_ROOT"] = str(root)
    os.environ["XLINE_PRODUCTION_DATABASE_PATH"] = str(production)
    os.environ["XLINE_STATE_DIR"] = str(root / "state")
    os.environ["XLINE_CONFIG_DIR"] = str(root / "config")
    os.environ["XLINE_WS_ROOT"] = str(root / "workspace")
    os.environ["XLINE_ENABLE_PRINTER"] = "0"
    os.environ["XLINE_PRINTER_AUTHORIZED"] = "0"
    os.environ["XLINE_HARDWARE_RUNTIME_ENABLE"] = "0"
    os.environ["XLINE_RUNTIME_PROFILE"] = "virtual_sim"
    os.environ["XLINE_USE_TOTAL_STATION"] = "0"
    os.environ["XLINE_EMBEDDED_DISCOVERY"] = "0"
    os.environ["XLINE_CREATIVE_PROJECT_JSON_IMPORT"] = "disabled"
    os.environ["XLINE_STARTUP_RECOVERY_MODE"] = "disabled"
    os.environ["XLINE_CONTROL_AUTH_MODE"] = "disabled"
    os.environ["XLINE_DEPLOYMENT_PROFILE"] = "test"

    for name, parts in _DEFAULT_NAMES.items():
        if not os.getenv(name, "").strip():
            os.environ[name] = str(root.joinpath(*parts))
    if not os.getenv("XLINE_AGENT_AUDIT_HEALTH_STORE", "").strip():
        os.environ["XLINE_AGENT_AUDIT_HEALTH_STORE"] = str(root / "state" / "agent_audit_health.json")
    if not os.getenv("XLINE_BACKUP_ROOT", "").strip():
        os.environ["XLINE_BACKUP_ROOT"] = str(root / "state" / "backups")
    if not os.getenv("XLINE_RESTORE_ROOT", "").strip():
        os.environ["XLINE_RESTORE_ROOT"] = str(root / "restore")
