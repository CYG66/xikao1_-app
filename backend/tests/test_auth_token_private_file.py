from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))

from auth_token_admin import write_private_text  # noqa: E402


def test_issue_cli_never_prints_the_token(tmp_path: Path):
    script = BACKEND / "scripts" / "auth_token_admin.py"
    target = tmp_path / "issued.token"
    env = {**os.environ, "XLINE_AUTH_SECRET": "d-line-test-secret-" + "x" * 32}
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "issue",
            "--subject",
            "d-line-review",
            "--ttl-seconds",
            "600",
            "--output",
            str(target),
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(BACKEND),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    token = target.read_text(encoding="utf-8").strip()
    assert token
    assert token not in proc.stdout
    assert token not in proc.stderr
    event = json.loads(proc.stdout)
    assert event["subject"] == "d-line-review"
    assert event["fingerprint"] == event["fingerprint"].lower()
    if os.name == "posix":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    else:
        acl = subprocess.check_output(["icacls", str(target)], text=True)
        assert "(I)" not in acl
        assert ":(F)" in acl


def test_new_token_file_is_private_from_creation(tmp_path: Path):
    target = tmp_path / "valid.token"
    write_private_text(target, "secret-token\n")

    assert target.read_text(encoding="utf-8") == "secret-token\n"
    if os.name == "posix":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    else:
        # The Windows DACL is protected and contains only the current user;
        # inherited SYSTEM/Administrators ACEs must be absent.
        acl = subprocess.check_output(["icacls", str(target)], text=True)
        assert "(I)" not in acl
        assert ":(F)" in acl


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
