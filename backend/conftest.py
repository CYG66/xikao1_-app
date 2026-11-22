"""Hard test-database isolation guard.

Tests must never inherit the application default database.  This file is at
the backend root so every pytest invocation with the backend as rootdir
(including the release regression runner) is stopped before collection unless
the caller supplied an explicit, non-production database path.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


def _production_database_path() -> Path:
    configured = os.getenv("XLINE_PRODUCTION_DATABASE_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(tempfile.gettempdir()) / "xline-agent" / "xline.db").resolve()


def pytest_configure(config) -> None:
    raw = os.getenv("XLINE_DATABASE_PATH", "").strip()
    if not raw:
        raise pytest.UsageError(
            "XLINE_DATABASE_PATH must be set explicitly for tests; "
            "refusing to fall back to the production database."
        )
    path = Path(raw).expanduser().resolve()
    if path == _production_database_path():
        raise pytest.UsageError(
            "XLINE_DATABASE_PATH resolves to the known production database; "
            "tests must use a separate isolated database."
        )
