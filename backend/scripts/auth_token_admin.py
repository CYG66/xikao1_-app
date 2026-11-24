"""Offline issuance and verification for XLine control tokens.

This tool never prints the token itself to stdout.  It writes the token to a
caller-selected file with browser-safe permissions and emits only the audit
metadata (subject, role, scopes, expiry, jti, fingerprint).

Token revocation in the frozen backend is service-wide: rotate XLINE_AUTH_SECRET,
restart the single worker and re-issue tokens.  The old tokens then fail
signature verification.  Per-jti revocation is not available in this baseline;
that limitation is recorded in the RELEASE-AUTH-E2E-01 lifecycle document.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

# Run from backend/ so `app` imports resolve for direct script execution.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.security import decode_token, issue_token  # noqa: E402


def _read_secret(secret_file: str | None, secret_env: str) -> str:
    if secret_file:
        value = Path(secret_file).read_text(encoding="utf-8").strip()
    else:
        value = os.getenv(secret_env, "").strip()
    if len(value) < 32:
        raise SystemExit("auth secret must be supplied via --secret-file or XLINE_AUTH_SECRET (>=32 chars)")
    return value


def _fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def _windows_current_user_sid() -> str:
    """Return the current process token's user SID without extra dependencies."""
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    class TokenUser(ctypes.Structure):
        _fields_ = [("User", SidAndAttributes)]

    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HANDLE]
    kernel32.LocalFree.restype = wintypes.HANDLE

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)
    ):
        raise PermissionError(f"cannot open process token: {ctypes.get_last_error()}")
    try:
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if size.value == 0:
            raise PermissionError(f"cannot size token user: {ctypes.get_last_error()}")
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(
            token, 1, buffer, size, ctypes.byref(size)
        ):
            raise PermissionError(f"cannot read token user: {ctypes.get_last_error()}")
        user = ctypes.cast(buffer, ctypes.POINTER(TokenUser)).contents
        sid_text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(
            user.User.Sid, ctypes.byref(sid_text)
        ):
            raise PermissionError(f"cannot format user SID: {ctypes.get_last_error()}")
        try:
            return str(sid_text.value)
        finally:
            kernel32.LocalFree(sid_text)
    finally:
        kernel32.CloseHandle(token)


def _windows_create_private_fd(path: Path) -> int:
    """Create a new file whose protected DACL contains only the current user.

    The DACL is applied to the open handle before any token bytes are written.
    If DACL application fails, the empty file is removed and the error is
    propagated; token content is never written under inherited permissions.
    """
    import ctypes
    import msvcrt
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HANDLE]
    kernel32.LocalFree.restype = wintypes.HANDLE
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = (
        wintypes.BOOL
    )
    advapi32.GetSecurityDescriptorDacl.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.BOOL),
    ]
    advapi32.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    advapi32.SetSecurityInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    advapi32.SetSecurityInfo.restype = wintypes.DWORD

    sid = _windows_current_user_sid()
    descriptor = ctypes.c_void_p()
    descriptor_size = wintypes.DWORD()
    sddl = f"D:P(A;;FA;;;{sid})"
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl,
        1,
        ctypes.byref(descriptor),
        ctypes.byref(descriptor_size),
    ):
        raise PermissionError(
            f"cannot build private DACL: {ctypes.get_last_error()}"
        )

    handle = wintypes.HANDLE()
    created = False
    try:
        present = wintypes.BOOL()
        dacl = ctypes.c_void_p()
        defaulted = wintypes.BOOL()
        if not advapi32.GetSecurityDescriptorDacl(
            descriptor,
            ctypes.byref(present),
            ctypes.byref(dacl),
            ctypes.byref(defaulted),
        ):
            raise PermissionError(
                f"cannot read private DACL: {ctypes.get_last_error()}"
            )

        # CREATE_NEW + GENERIC_WRITE + WRITE_DAC.  The DACL is set while the
        # handle is open, before fdopen/write can expose token bytes.
        handle = kernel32.CreateFileW(
            str(path),
            0x40000000 | 0x00040000,
            0,
            None,
            1,
            0x80,
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if handle == invalid_handle:
            error = ctypes.get_last_error()
            if error in (80, 183):
                raise FileExistsError(path)
            raise PermissionError(f"cannot create token file: {error}")
        created = True

        # PROTECTED_DACL_SECURITY_INFORMATION removes inherited ACEs.
        rc = advapi32.SetSecurityInfo(
            handle, 1, 0x00000004 | 0x80000000, None, None, dacl, None
        )
        if rc != 0:
            raise PermissionError(f"cannot set private token DACL: {rc}")
        fd = msvcrt.open_osfhandle(handle, os.O_WRONLY)
        handle = wintypes.HANDLE()
        return fd
    except BaseException:
        if handle and handle != ctypes.c_void_p(-1).value:
            kernel32.CloseHandle(handle)
        if created:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        raise
    finally:
        kernel32.LocalFree(descriptor)


def write_private_text(path: Path, value: str) -> None:
    """Atomically create a private text file; never widen permissions first.

    POSIX uses mode 0600 at creation.  Windows opens the new file with WRITE_DAC,
    applies a protected owner-only DACL on the handle before writing, and removes
    the empty file if any permission or write step fails.  An existing path is
    never truncated.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = -1
    created = False
    try:
        if os.name == "nt":
            fd = _windows_create_private_fd(path)
        else:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(path, flags, stat.S_IRUSR | stat.S_IWUSR)
        created = True
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            fd = -1
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != "nt":
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        if created:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        raise



def _append_audit(path: str | None, event: dict[str, object]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _metadata(token: str, secret: str) -> dict[str, object]:
    principal = decode_token(token, secret=secret)
    return {
        "subject": principal.subject,
        "role": principal.role,
        "scopes": sorted(principal.scopes),
        "token_id": principal.token_id,
        "expires_at": principal.expires_at,
        "fingerprint": _fingerprint(token),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="XLine control token lifecycle")
    subparsers = parser.add_subparsers(dest="command", required=True)

    issue = subparsers.add_parser("issue", help="issue a short-lived token to a private file")
    issue.add_argument("--subject", required=True)
    issue.add_argument("--role", default="operator", choices=["admin", "operator", "readonly"])
    issue.add_argument("--ttl-seconds", type=int, default=3600)
    issue.add_argument("--output", required=True, help="private token file; never stdout")
    issue.add_argument("--audit-log", default="")
    issue.add_argument("--secret-file", default="")
    issue.add_argument("--secret-env", default="XLINE_AUTH_SECRET")
    issue.add_argument("--token-id", default="")

    verify = subparsers.add_parser("verify", help="verify a token without printing it")
    verify.add_argument("--token-file", required=True)
    verify.add_argument("--secret-file", default="")
    verify.add_argument("--secret-env", default="XLINE_AUTH_SECRET")

    args = parser.parse_args()
    secret = _read_secret(args.secret_file, args.secret_env)

    if args.command == "issue":
        token = issue_token(
            args.subject,
            secret=secret,
            role=args.role,
            ttl_seconds=args.ttl_seconds,
            token_id=args.token_id or None,
        )
        write_private_text(Path(args.output), token + "\n")
        metadata = _metadata(token, secret)
        event = {
            "event": "issued",
            "at": datetime.now(timezone.utc).isoformat(),
            "token_file": str(Path(args.output)),
            **metadata,
        }
        _append_audit(args.audit_log, event)
        print(json.dumps(event, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "verify":
        token = Path(args.token_file).read_text(encoding="utf-8").strip()
        metadata = _metadata(token, secret)
        event = {
            "event": "verified",
            "at": datetime.now(timezone.utc).isoformat(),
            "token_file": str(Path(args.token_file)),
            **metadata,
        }
        print(json.dumps(event, ensure_ascii=False, sort_keys=True))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
