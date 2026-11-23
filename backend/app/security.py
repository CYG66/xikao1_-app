"""Fail-closed control-plane authentication and authorization.

The rover backend has several hardware and persistence entry points that must
never rely on a caller-supplied ``client_id`` or ``confirmed=True``.  This
module provides one place for:

* signed, expiring session tokens with an authenticated subject;
* role/scope checks for HTTP and WebSocket routes;
* request replay rejection for state-changing control calls;
* body/query ``client_id`` rebinding to the authenticated subject.

Authentication is mandatory for production.  It is intentionally disabled only
for the isolated integration/test profile, where model calls and hardware
execution are also forced off.  Production startup refuses to continue unless
``XLINE_AUTH_SECRET`` and at least one signed token are configured.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
import uuid
from urllib.parse import quote
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Sequence

AUTH_MODE_ENV = "XLINE_CONTROL_AUTH_MODE"
AUTH_SECRET_ENV = "XLINE_AUTH_SECRET"
AUTH_TOKEN_ENV = "XLINE_CONTROL_AUTH_TOKEN"
AUTH_ADMIN_TOKEN_ENV = "XLINE_ADMIN_AUTH_TOKEN"
AUTH_REQUEST_ID_HEADER = "x-xline-request-id"
AUTH_TOKEN_HEADER = "x-xline-token"

_TRUE_VALUES = {"1", "true", "yes", "on"}
_TOKEN_PREFIX = "xla1"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_MIN_SECRET_LENGTH = 32
_SCOPE_ALL = frozenset(
    {"read", "control", "hardware", "mission", "printer", "agent", "wifi", "database"}
)

_ROLE_SCOPES: dict[str, frozenset[str]] = {
    "admin": _SCOPE_ALL,
    "operator": frozenset(
        {"read", "control", "hardware", "mission", "printer", "agent"}
    ),
    "readonly": frozenset({"read"}),
}


class AuthError(RuntimeError):
    """Authentication/authorization failure with an HTTP-compatible status."""

    def __init__(self, message: str, *, status_code: int = 401, code: str = "unauthorized") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class AuthPrincipal:
    subject: str
    role: str
    scopes: frozenset[str]
    token_id: str
    expires_at: int

    def has_scope(self, scope: str | None) -> bool:
        return scope is None or scope in self.scopes


_current_principal: ContextVar[AuthPrincipal | None] = ContextVar(
    "xline_auth_principal", default=None
)


def current_principal() -> AuthPrincipal | None:
    return _current_principal.get()


def _env(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def _flag(value: str | None) -> bool:
    return bool(value and value.strip().lower() in _TRUE_VALUES)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _signing_material(secret: str, body: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), f"{_TOKEN_PREFIX}.{body}".encode("ascii"), hashlib.sha256).digest()


def issue_token(
    subject: str,
    *,
    secret: str,
    role: str = "operator",
    ttl_seconds: int = 3600,
    scopes: Sequence[str] | None = None,
    now: int | None = None,
    token_id: str | None = None,
) -> str:
    """Create a signed, expiring token for an authenticated subject."""
    cleaned_subject = str(subject).strip()
    if not cleaned_subject:
        raise ValueError("subject is required")
    if role not in _ROLE_SCOPES:
        raise ValueError(f"unsupported role: {role}")
    if len(secret) < _MIN_SECRET_LENGTH:
        raise ValueError("auth secret must be at least 32 characters")
    issued = int(time.time() if now is None else now)
    ttl = max(1, min(int(ttl_seconds), 30 * 24 * 3600))
    effective_scopes = frozenset(scopes) if scopes is not None else _ROLE_SCOPES[role]
    if not effective_scopes <= _ROLE_SCOPES[role]:
        raise ValueError("scopes exceed the selected role")
    payload = {
        "sub": cleaned_subject[:128],
        "role": role,
        "scopes": sorted(effective_scopes),
        "iat": issued,
        "exp": issued + ttl,
        "jti": (token_id or uuid.uuid4().hex)[:128],
    }
    body = _b64encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))
    signature = _b64encode(_signing_material(secret, body))
    return f"{_TOKEN_PREFIX}.{body}.{signature}"


def decode_token(token: str, *, secret: str, now: int | None = None) -> AuthPrincipal:
    """Verify signature and expiry, then return the authenticated principal."""
    if len(secret) < _MIN_SECRET_LENGTH:
        raise AuthError("authentication is not configured", status_code=503, code="auth_not_configured")
    parts = str(token or "").split(".")
    if len(parts) != 3 or parts[0] != _TOKEN_PREFIX:
        raise AuthError("invalid token", code="invalid_token")
    body, supplied = parts[1], parts[2]
    expected = _b64encode(_signing_material(secret, body))
    if not hmac.compare_digest(supplied, expected):
        raise AuthError("invalid token signature", code="invalid_token")
    try:
        payload = json.loads(_b64decode(body).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AuthError("invalid token payload", code="invalid_token") from error
    if not isinstance(payload, dict) or payload.get("v", 1) != 1:
        raise AuthError("invalid token payload", code="invalid_token")
    subject = str(payload.get("sub", "")).strip()
    role = str(payload.get("role", "")).strip()
    if not subject or role not in _ROLE_SCOPES:
        raise AuthError("invalid token identity", code="invalid_token")
    try:
        expires_at = int(payload["exp"])
        issued_at = int(payload["iat"])
    except (KeyError, TypeError, ValueError) as error:
        raise AuthError("invalid token lifetime", code="invalid_token") from error
    current = int(time.time() if now is None else now)
    if expires_at <= current:
        raise AuthError("token expired", code="token_expired")
    if issued_at > current + 60:
        raise AuthError("token issued in the future", code="invalid_token")
    raw_scopes = payload.get("scopes")
    if not isinstance(raw_scopes, list) or not all(isinstance(item, str) for item in raw_scopes):
        raise AuthError("invalid token scopes", code="invalid_token")
    scopes = frozenset(str(item) for item in raw_scopes)
    if not scopes <= _ROLE_SCOPES[role]:
        raise AuthError("token scopes exceed role", code="invalid_token")
    return AuthPrincipal(
        subject=subject[:128],
        role=role,
        scopes=scopes,
        token_id=str(payload.get("jti", ""))[:128],
        expires_at=expires_at,
    )


class ReplayGuard:
    """Process-local request-id replay cache for state-changing calls."""

    def __init__(self, ttl_seconds: int = 600) -> None:
        self.ttl_seconds = max(30, int(ttl_seconds))
        self._lock = threading.Lock()
        self._seen: dict[str, float] = {}

    def consume(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._seen = {item: expiry for item, expiry in self._seen.items() if expiry > now}
            if key in self._seen:
                raise AuthError("duplicate request id", status_code=409, code="replay_rejected")
            self._seen[key] = now + self.ttl_seconds

    def clear(self) -> None:
        with self._lock:
            self._seen.clear()


replay_guard = ReplayGuard()


class AuthManager:
    def __init__(self, environ: MutableMapping[str, str] | None = None) -> None:
        self._environ = environ
        self._lock = threading.RLock()

    def _env(self) -> Mapping[str, str]:
        return _env(self._environ)

    def mode(self) -> str:
        configured = str(self._env().get(AUTH_MODE_ENV, "")).strip().lower()
        if configured:
            return configured
        return "enforced" if str(self._env().get("XLINE_DEPLOYMENT_PROFILE", "")).strip().lower() == "production" else "disabled"

    def enforced(self) -> bool:
        return self.mode() == "enforced"

    def secret(self) -> str:
        return str(self._env().get(AUTH_SECRET_ENV, "")).strip()

    def configured_tokens(self) -> list[str]:
        values = [
            str(self._env().get(AUTH_TOKEN_ENV, "")).strip(),
            str(self._env().get(AUTH_ADMIN_TOKEN_ENV, "")).strip(),
        ]
        return [item for item in values if item]

    def assert_ready(self) -> None:
        if not self.enforced():
            if str(self._env().get("XLINE_DEPLOYMENT_PROFILE", "")).strip().lower() == "production":
                raise AuthError(
                    "production requires XLINE_CONTROL_AUTH_MODE=enforced",
                    status_code=503,
                    code="auth_not_configured",
                )
            return
        secret = self.secret()
        if len(secret) < _MIN_SECRET_LENGTH:
            raise AuthError(
                "production control-plane authentication requires XLINE_AUTH_SECRET (>=32 chars)",
                status_code=503,
                code="auth_not_configured",
            )
        tokens = self.configured_tokens()
        if not tokens:
            raise AuthError(
                "production control-plane authentication requires at least one signed token",
                status_code=503,
                code="auth_not_configured",
            )
        for token in tokens:
            decode_token(token, secret=secret)
        if str(self._env().get("XLINE_DEPLOYMENT_PROFILE", "")).strip().lower() == "production" and not self.enforced():
            raise AuthError(
                "production requires XLINE_CONTROL_AUTH_MODE=enforced",
                status_code=503,
                code="auth_not_configured",
            )

    def authenticate(self, token: str | None) -> AuthPrincipal:
        if not self.enforced():
            raise AuthError("authentication is disabled", status_code=503, code="auth_disabled")
        if not token:
            raise AuthError("missing authentication token", code="missing_token")
        return decode_token(token, secret=self.secret())

    def principal_from_headers(self, headers: Mapping[str, str] | Sequence[tuple[str, str]]) -> AuthPrincipal:
        if isinstance(headers, Mapping):
            normalized = {str(key).lower(): str(value) for key, value in headers.items()}
        else:
            normalized = {
                str(key).lower(): str(value)
                for key, value in headers
            }
        token = ""
        authorization = normalized.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        if not token:
            token = normalized.get(AUTH_TOKEN_HEADER, "").strip()
        if not token:
            protocols = normalized.get("sec-websocket-protocol", "")
            for item in protocols.split(","):
                candidate = item.strip()
                if candidate.startswith("xline-auth."):
                    token = candidate[len("xline-auth.") :].strip()
                    break
        return self.authenticate(token)

    def require_scope(self, principal: AuthPrincipal, scope: str | None) -> None:
        if not principal.has_scope(scope):
            raise AuthError(
                "authenticated subject lacks the required scope",
                status_code=403,
                code="forbidden_scope",
            )


auth_manager = AuthManager()


def required_scope(method: str, path: str) -> str | None:
    """Return the scope required before a route can produce side effects."""
    method = str(method).upper()
    if path == "/health" or method == "OPTIONS":
        return None
    if path in {"/docs", "/openapi.json", "/redoc"}:
        return "read"
    if path in {"/", "/ws/rosbridge"}:
        return "control"
    if path == "/ws/status":
        return "read"
    if path.startswith("/api/network/status") or path.startswith("/api/network/wifi/verify"):
        return "read"
    if path.startswith("/api/network"):
        return "wifi"
    if path.startswith("/api/database"):
        return "database"
    if (
        path.startswith("/api/cmd_vel")
        or path.startswith("/api/emergency-stop")
        or path.startswith("/api/printer")
        or path.startswith("/api/ln150")
        or path.startswith("/api/mission/control")
    ):
        return "control"
    if path.startswith("/api/monitor/diagnose"):
        return "agent"
    if method in {"GET", "HEAD"}:
        if path.startswith("/api/"):
            return "read"
        return None
    if path.startswith("/api/agent") or path.startswith("/api/projects") or path.startswith("/api/drawings") or path.startswith("/api/missions"):
        return "agent"
    if path.startswith("/api/"):
        return "read"
    return None


def request_id_is_generated(method: str, path: str) -> bool:
    scope = required_scope(method, path)
    return bool(scope and scope not in {"read"} and method.upper() in {"POST", "PUT", "PATCH", "DELETE"})


def _header_map(scope: Mapping[str, Any]) -> dict[str, str]:
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


def _set_header(scope: MutableMapping[str, Any], name: str, value: str) -> None:
    raw_name = name.encode("latin-1").lower()
    headers = [(key, item) for key, item in scope.get("headers", []) if key.lower() != raw_name]
    headers.append((raw_name, value.encode("latin-1")))
    scope["headers"] = headers


async def _send_http_error(send, status_code: int, code: str, detail: str) -> None:
    body = json.dumps({"ok": False, "code": code, "detail": detail}, ensure_ascii=False).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status_code,
        "headers": [(b"content-type", b"application/json; charset=utf-8"), (b"content-length", str(len(body)).encode("ascii"))],
    })
    await send({"type": "http.response.body", "body": body})


def _rewrite_query(scope: MutableMapping[str, Any], subject: str) -> None:
    raw = scope.get("query_string", b"").decode("utf-8", errors="ignore")
    if not raw:
        return
    pairs = []
    changed = False
    for item in raw.split("&"):
        if "=" in item:
            key, value = item.split("=", 1)
        else:
            key, value = item, ""
        if key == "client_id":
            value = quote(subject, safe="")
            changed = True
        pairs.append(f"{key}={value}")
    if changed:
        scope["query_string"] = "&".join(pairs).encode("utf-8")


class ControlAuthMiddleware:
    """Pure ASGI middleware so WebSocket handshakes are covered too."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        method = str(scope.get("method", "GET")).upper()
        scope_required = required_scope(method, path)
        if scope_required is None:
            await self.app(scope, receive, send)
            return

        if not auth_manager.enforced():
            scope.setdefault("state", {})["auth"] = None
            await self.app(scope, receive, send)
            return

        headers = _header_map(scope)
        try:
            principal = auth_manager.principal_from_headers(headers)
            auth_manager.require_scope(principal, scope_required)
            if request_id_is_generated(method, path):
                request_id = headers.get(AUTH_REQUEST_ID_HEADER, "").strip()
                if not _REQUEST_ID_RE.fullmatch(request_id):
                    raise AuthError(
                        "state-changing requests require a valid X-XLine-Request-Id",
                        status_code=401,
                        code="missing_request_id",
                    )
                replay_guard.consume(f"{principal.subject}:{request_id}")
        except AuthError as error:
            if scope.get("type") == "websocket":
                await send({"type": "websocket.close", "code": 1008, "reason": error.code[:120]})
            else:
                await _send_http_error(send, error.status_code, error.code, str(error))
            return

        scope.setdefault("state", {})["auth"] = principal
        _rewrite_query(scope, principal.subject)
        _current_principal.set(principal)

        if scope.get("type") == "http":
            headers = _header_map(scope)
            content_type = headers.get("content-type", "").lower()
            try:
                length = int(headers.get("content-length", "0") or "0")
            except ValueError:
                length = 0
            if (
                content_type.startswith("application/json")
                and 0 < length <= 4_000_000
                and method in {"POST", "PUT", "PATCH", "DELETE"}
            ):
                messages = []
                while True:
                    message = await receive()
                    messages.append(message)
                    if not message.get("more_body", False):
                        break
                body = b"".join(item.get("body", b"") for item in messages)
                try:
                    payload = json.loads(body.decode("utf-8"))
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                    payload = None
                if isinstance(payload, dict) and "client_id" in payload:
                    payload["client_id"] = principal.subject
                    rewritten = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    _set_header(scope, "content-length", str(len(rewritten)))
                    sent = {"done": False}

                    async def replay_receive():
                        if not sent["done"]:
                            sent["done"] = True
                            return {"type": "http.request", "body": rewritten, "more_body": False}
                        return {"type": "http.request", "body": b"", "more_body": False}

                    try:
                        await self.app(scope, replay_receive, send)
                    finally:
                        _current_principal.set(None)
                    return

        try:
            await self.app(scope, receive, send)
        finally:
            _current_principal.set(None)


def authenticated_client_id(request, fallback: str | None = None) -> str | None:
    # Tests and internal callers sometimes pass the identity directly instead
    # of a Request; keep that path working without weakening authenticated
    # requests, where Request.state.auth always wins.
    if isinstance(request, str):
        return request
    principal = getattr(getattr(request, "state", None), "auth", None)
    if principal is not None:
        return principal.subject
    return fallback
