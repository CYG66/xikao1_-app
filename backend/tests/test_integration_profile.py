"""Integration profile admission and storage isolation regressions."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import creative_projects
from app.database import XLineDatabase
from app.integration_profile import (
    IntegrationProfileError,
    apply_integration_profile,
    known_production_database_path,
    known_production_project_store_paths,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _valid_env(tmp_path: Path) -> dict[str, str]:
    root = tmp_path / "iso"
    root.mkdir()
    production = tmp_path / "production" / "xline.db"
    return {
        "XLINE_INTEGRATION_PROFILE": "1",
        "XLINE_INTEGRATION_ISOLATION_ROOT": str(root),
        "XLINE_DATABASE_PATH": str(root / "xline.db"),
        "XLINE_CREATIVE_PROJECT_STORE": str(root / "creative_projects.json"),
        "XLINE_PRODUCTION_DATABASE_PATH": str(production),
    }


def test_profile_off_is_a_noop():
    env: dict[str, str] = {}
    assert apply_integration_profile(env) is None
    assert env == {}


def test_profile_forces_offline_virtual_switches(tmp_path):
    env = _valid_env(tmp_path)
    config = apply_integration_profile(env)
    assert config is not None
    assert config["model_calls"] is False
    assert config["robot_execution"] is False
    assert env["XLINE_AGENT_PROVIDER"] == "local"
    assert env["XLINE_EMBEDDED_DISCOVERY"] == "0"
    assert env["XLINE_ENABLE_PRINTER"] == "0"
    assert env["XLINE_RUNTIME_PROFILE"] == "virtual_sim"
    assert env["XLINE_USE_TOTAL_STATION"] == "0"


@pytest.mark.parametrize("name", [
    "XLINE_INTEGRATION_ISOLATION_ROOT",
    "XLINE_DATABASE_PATH",
    "XLINE_CREATIVE_PROJECT_STORE",
    "XLINE_PRODUCTION_DATABASE_PATH",
])
def test_profile_rejects_missing_required_path(tmp_path, name):
    env = _valid_env(tmp_path)
    env.pop(name)
    with pytest.raises(IntegrationProfileError, match=name):
        apply_integration_profile(env)


def test_profile_rejects_active_database_equal_to_production(tmp_path):
    env = _valid_env(tmp_path)
    production = Path(env["XLINE_PRODUCTION_DATABASE_PATH"])
    env["XLINE_DATABASE_PATH"] = str(production)
    with pytest.raises(IntegrationProfileError, match="生产数据库"):
        apply_integration_profile(env)


def test_profile_rejects_active_database_outside_isolation_root(tmp_path):
    env = _valid_env(tmp_path)
    env["XLINE_DATABASE_PATH"] = str(tmp_path / "outside.db")
    with pytest.raises(IntegrationProfileError, match="隔离根"):
        apply_integration_profile(env)


def test_profile_rejects_active_json_outside_isolation_root(tmp_path):
    env = _valid_env(tmp_path)
    env["XLINE_CREATIVE_PROJECT_STORE"] = str(tmp_path / "outside.json")
    with pytest.raises(IntegrationProfileError, match="隔离根"):
        apply_integration_profile(env)


def test_profile_rejects_known_production_json(tmp_path):
    env = _valid_env(tmp_path)
    env["XLINE_CREATIVE_PROJECT_STORE"] = str(known_production_project_store_paths()[0])
    with pytest.raises(IntegrationProfileError, match="生产 JSON"):
        apply_integration_profile(env)


def test_known_production_database_is_the_platform_default(tmp_path):
    # The helper is intentionally platform-based, not derived from the active
    # test database path.
    assert known_production_database_path().name == "xline.db"


def test_app_import_fails_closed_when_profile_is_incomplete():
    env = os.environ.copy()
    env["XLINE_INTEGRATION_PROFILE"] = "1"
    env.pop("XLINE_INTEGRATION_ISOLATION_ROOT", None)
    completed = subprocess.run(
        [sys.executable, "-c", "import app"],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "XLINE_INTEGRATION_ISOLATION_ROOT" in completed.stderr


def test_empty_sqlite_does_not_import_json_projects(tmp_path, monkeypatch):
    root = tmp_path / "iso"
    root.mkdir()
    json_path = root / "creative_projects.json"
    json_path.write_text(json.dumps({"projects": [{
        "id": "historical-project",
        "name": "historical",
    }]}), encoding="utf-8")
    database = XLineDatabase(root / "empty.db")

    monkeypatch.setenv("XLINE_INTEGRATION_PROFILE", "1")
    monkeypatch.setenv("XLINE_CREATIVE_PROJECT_STORE", str(json_path))
    monkeypatch.setattr(creative_projects, "xline_database", database)

    store = creative_projects.CreativeProjectStore()
    assert store.list() == []
    assert store._json_fallback_enabled is False


def test_model_gateway_rejects_external_calls_under_profile(monkeypatch):
    from app import model_request_gateway as gateway

    monkeypatch.setenv("XLINE_INTEGRATION_PROFILE", "1")
    with pytest.raises(RuntimeError, match="禁止外部模型请求"):
        gateway.request_provider_tool_json(
            "deepseek",
            model="deepseek-chat",
            api_key="dummy",
            payload={},
            timeout=1.0,
        )


def test_agent_service_forces_local_mode_under_profile(tmp_path):
    env = os.environ.copy()
    env.update(_valid_env(tmp_path))
    env["XLINE_AGENT_PROVIDER"] = "deepseek"
    script = (
        "import json\n"
        "from app.agent_service import robot_agent\n"
        "print(json.dumps({'mode': robot_agent.mode, 'api_keys': robot_agent.api_keys}))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["mode"] == "local"
    assert payload["api_keys"] == {}


