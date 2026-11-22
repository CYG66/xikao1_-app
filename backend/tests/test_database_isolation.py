from pathlib import Path

import pytest

import conftest
from app.database import _default_path, _platform_default_path


def test_test_context_refuses_implicit_default_database(monkeypatch):
    monkeypatch.delenv("XLINE_DATABASE_PATH", raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_database_isolation.py::guard")
    with pytest.raises(RuntimeError, match="XLINE_DATABASE_PATH must be set explicitly"):
        _default_path()


def test_platform_default_path_is_shared_for_windows_and_linux(tmp_path):
    temp = tmp_path / "temp"
    home = tmp_path / "home"
    state = tmp_path / "state"
    assert _platform_default_path(platform_name="nt", temp_dir=temp) == (
        temp / "xline-agent" / "xline.db"
    )
    assert _platform_default_path(platform_name="posix", home_dir=home) == (
        home / ".local" / "state" / "xline-agent" / "xline.db"
    )
    assert _platform_default_path(
        platform_name="posix", home_dir=home, xdg_state_home=state
    ) == state / "xline-agent" / "xline.db"


def test_isolation_guard_rejects_the_same_platform_default_path(monkeypatch, tmp_path):
    production = tmp_path / "state" / "xline-agent" / "xline.db"
    monkeypatch.setattr(conftest, "_platform_default_path", lambda: production)
    monkeypatch.delenv("XLINE_PRODUCTION_DATABASE_PATH", raising=False)
    monkeypatch.setenv("XLINE_DATABASE_PATH", str(production))
    with pytest.raises(pytest.UsageError, match="known production database"):
        conftest.pytest_configure(None)

    monkeypatch.setenv("XLINE_DATABASE_PATH", str(tmp_path / "isolated.db"))
    conftest.pytest_configure(None)


def test_isolation_guard_honors_explicit_production_path(monkeypatch, tmp_path):
    production = tmp_path / "explicit-production.db"
    monkeypatch.setenv("XLINE_PRODUCTION_DATABASE_PATH", str(production))
    monkeypatch.setenv("XLINE_DATABASE_PATH", str(Path(production)))
    with pytest.raises(pytest.UsageError, match="known production database"):
        conftest.pytest_configure(None)
