from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))

from auth_token_admin import write_private_text  # noqa: E402


def test_new_token_file_is_private_from_creation(tmp_path: Path):
    target = tmp_path / "valid.token"
    write_private_text(target, "secret-token\n")

    assert target.read_text(encoding="utf-8") == "secret-token\n"
    if os.name == "posix":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    else:
        # Windows path applies an owner-only ACL; the token file must exist and
        # must not rely on the process umask.
        assert target.exists()


def test_existing_token_file_is_never_truncated(tmp_path: Path):
    target = tmp_path / "existing.token"
    target.write_text("existing\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_private_text(target, "replacement\n")

    assert target.read_text(encoding="utf-8") == "existing\n"


def test_permission_or_write_failure_leaves_no_token_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    target = tmp_path / "failed.token"

    def fail_fsync(_fd: int) -> None:
        raise PermissionError("simulated private-write failure")

    monkeypatch.setattr(os, "fsync", fail_fsync)
    with pytest.raises(PermissionError):
        write_private_text(target, "secret-token\n")

    assert not target.exists()
