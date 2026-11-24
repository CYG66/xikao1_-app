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


def _write_private(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


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
        _write_private(Path(args.output), token + "\n")
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
