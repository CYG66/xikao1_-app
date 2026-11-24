"""P0-06 proof that the test session is fully isolated and fail-closed."""
from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

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


def test_every_persistent_store_is_inside_the_temporary_root():
    # Honour the explicit session root when CI separates state, config and
    # workspace into sibling directories. Otherwise derive it from the database.
    explicit_root = os.environ.get("XLINE_TEST_ISOLATION_ROOT", "").strip()
    database = Path(os.environ["XLINE_DATABASE_PATH"]).resolve()
    root = Path(explicit_root).resolve() if explicit_root else database.parent
    # A prior test may replace the session database without updating the
    # explicit root; in that case the database parent is the active root.
    if database != root and root not in database.parents:
        root = database.parent
    assert root.exists()
    for name in _PATH_ENVS:
        raw = os.environ.get(name, "").strip()
        assert raw, name
        path = Path(raw).resolve()
        assert path == root or root in path.parents, f"{name} escapes isolation: {path}"


def test_hardware_and_external_network_are_default_off():
    assert os.environ["XLINE_HARDWARE_RUNTIME_ENABLE"] == "0"
    assert os.environ["XLINE_ENABLE_PRINTER"] == "0"
    assert os.environ["XLINE_PRINTER_AUTHORIZED"] == "0"
    assert os.environ["XLINE_RUNTIME_PROFILE"] == "virtual_sim"
    assert os.environ["XLINE_CONTROL_AUTH_MODE"] == "disabled"

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OSError, match="external network is disabled"):
            sock.connect(("8.8.8.8", 53))
    finally:
        sock.close()
