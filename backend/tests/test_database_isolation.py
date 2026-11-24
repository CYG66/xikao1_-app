import os
from pathlib import Path

import pytest

import conftest
from app.database import _default_path, _platform_default_path


@pytest.fixture(autouse=True)
def _restore_guard_environment():
    """Restore the whole environment after tests call ``pytest_configure``.

    The guard mutates ``os.environ`` directly, so monkeypatch alone cannot undo
    all writes.  A full snapshot prevents a rejected configuration from leaking
    root or store paths into later tests.
    """
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def _clear_guard_paths(monkeypatch):
    for name in set(conftest._PATH_ENVS) | {
        "XLINE_TEST_ISOLATION_ROOT",
        "XLINE_PRODUCTION_DATABASE_PATH",
    }:
        monkeypatch.delenv(name, raising=False)


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

    _clear_guard_paths(monkeypatch)
    monkeypatch.setenv("XLINE_DATABASE_PATH", str(tmp_path / "isolated.db"))
    conftest.pytest_configure(None)


def test_isolation_guard_honors_explicit_production_path(monkeypatch, tmp_path):
    production = tmp_path / "explicit-production.db"
    monkeypatch.setenv("XLINE_PRODUCTION_DATABASE_PATH", str(production))
    monkeypatch.setenv("XLINE_DATABASE_PATH", str(Path(production)))
    with pytest.raises(pytest.UsageError, match="known production database"):
        conftest.pytest_configure(None)


def test_isolation_root_inside_simulated_production_is_rejected_before_mkdir(
    monkeypatch, tmp_path
):
    _clear_guard_paths(monkeypatch)
    production = tmp_path / "simulated-production" / "xline.db"
    root = production.parent / "forbidden-session"
    database = tmp_path / "outside" / "xline.db"
    monkeypatch.setenv("XLINE_PRODUCTION_DATABASE_PATH", str(production))
    monkeypatch.setenv("XLINE_TEST_ISOLATION_ROOT", str(root))
    monkeypatch.setenv("XLINE_DATABASE_PATH", str(database))

    assert not root.exists()
    with pytest.raises(pytest.UsageError, match="known production state"):
        conftest.pytest_configure(object())
    assert not root.exists()


def test_implicit_database_path_is_checked_for_production_collision(
    monkeypatch, tmp_path
):
    _clear_guard_paths(monkeypatch)
    production = tmp_path / "simulated-production" / "xline.db"
    root = production.parent
    monkeypatch.setenv("XLINE_PRODUCTION_DATABASE_PATH", str(production))
    monkeypatch.setenv("XLINE_TEST_ISOLATION_ROOT", str(root))

    assert not root.exists()
    with pytest.raises(pytest.UsageError, match="known production database"):
        conftest.pytest_configure(object())
    assert not root.exists()


def test_explicit_store_path_is_rejected_before_root_mkdir(monkeypatch, tmp_path):
    _clear_guard_paths(monkeypatch)
    production = tmp_path / "simulated-production" / "xline.db"
    root = tmp_path / "safe-session" / "nested"
    monkeypatch.setenv("XLINE_PRODUCTION_DATABASE_PATH", str(production))
    monkeypatch.setenv("XLINE_TEST_ISOLATION_ROOT", str(root))
    monkeypatch.setenv(
        "XLINE_AGENT_TASK_STORE", str(tmp_path / "outside" / "tasks.json")
    )

    assert not root.exists()
    with pytest.raises(pytest.UsageError, match="outside the test isolation root"):
        conftest.pytest_configure(object())
    assert not root.exists()


def test_valid_explicit_root_still_sets_isolated_paths(monkeypatch, tmp_path):
    _clear_guard_paths(monkeypatch)
    production = tmp_path / "simulated-production" / "xline.db"
    root = tmp_path / "valid-session"
    database = root / "nested" / "xline.db"
    monkeypatch.setenv("XLINE_PRODUCTION_DATABASE_PATH", str(production))
    monkeypatch.setenv("XLINE_TEST_ISOLATION_ROOT", str(root))
    monkeypatch.setenv("XLINE_DATABASE_PATH", str(database))

    conftest.pytest_configure(object())

    assert root.is_dir()
    assert Path(os.environ["XLINE_DATABASE_PATH"]).resolve() == database.resolve()
    for name in conftest._PATH_ENVS:
        assert Path(os.environ[name]).resolve().is_relative_to(root.resolve()), name
