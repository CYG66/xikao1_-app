import pytest

from app.database import _default_path


def test_test_context_refuses_implicit_default_database(monkeypatch):
    monkeypatch.delenv("XLINE_DATABASE_PATH", raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_database_isolation.py::guard")
    with pytest.raises(RuntimeError, match="XLINE_DATABASE_PATH must be set explicitly"):
        _default_path()
