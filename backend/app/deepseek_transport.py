"""Low-level DeepSeek HTTP transport with bounded streaming reads."""

from __future__ import annotations

import http.client
import json
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from .agent_service_config import PROVIDERS


class DeepSeekTransport:
    def __init__(
        self,
        *,
        api_key: str,
        timeout_for: Callable[[str, float], float],
    ) -> None:
        self._api_key = api_key
        self._timeout_for = timeout_for

    def _resolve_socket(
        self,
        connection: http.client.HTTPSConnection | None,
        response: http.client.HTTPResponse | None = None,
    ):
        """Return the live socket regardless of http.client attribute layout.

        On newer CPython (3.12+) ``HTTPSConnection.sock`` is frequently None
        after ``getresponse()``; the readable socket then lives under
        ``response.fp.raw._sock``.  Falling back to it keeps the read timeout
        actually applied instead of silently leaving the connect-timeout
        default (which aborts slow large completions).
        """
        sock = (
            getattr(connection, "sock", None)
            if connection is not None
            else None
        )
        if sock is None and response is not None:
            fp = getattr(response, "fp", None)
            if fp is not None:
                raw = getattr(fp, "raw", None)
                if raw is not None:
                    sock = getattr(raw, "_sock", None)
        return sock

    def set_socket_timeout(
        self,
        connection: http.client.HTTPSConnection | None,
        deadline: float,
        response: http.client.HTTPResponse | None = None,
    ) -> None:
        sock = self._resolve_socket(connection, response)
        if sock is None:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("DeepSeek request deadline exceeded")
        sock.settimeout(
            min(self._timeout_for("read", 30.0), remaining)
        )

    def read_body(
        self,
        response: http.client.HTTPResponse,
        connection: http.client.HTTPSConnection | None,
        deadline: float,
    ) -> str:
        chunks: list[bytes] = []
        while True:
            self.set_socket_timeout(connection, deadline, response=response)
            chunk = response.read(64 * 1024)
            if time.monotonic() >= deadline:
                raise TimeoutError("DeepSeek response deadline exceeded")
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace")

    def open(
        self, payload: dict[str, Any]
    ) -> tuple[http.client.HTTPSConnection, http.client.HTTPResponse]:
        parsed = urlparse(PROVIDERS["deepseek"][1])
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": (
                "text/event-stream" if payload.get("stream") else "application/json"
            ),
            "Connection": "close",
        }
        for attempt in range(2):
            connection: http.client.HTTPSConnection | None = None
            try:
                connection = http.client.HTTPSConnection(
                    parsed.hostname,
                    parsed.port or 443,
                    timeout=self._timeout_for("connect", 10.0),
                )
                connection.request(
                    "POST", "/chat/completions", body=body, headers=headers
                )
                response = connection.getresponse()
                self.set_socket_timeout(
                    connection,
                    time.monotonic() + self._timeout_for("read", 30.0),
                    response=response,
                )
                return connection, response
            except (OSError, http.client.HTTPException) as error:
                if connection is not None:
                    connection.close()
                if attempt == 1:
                    raise RuntimeError(f"无法连接 DeepSeek：{error}") from error
        raise RuntimeError("无法连接 DeepSeek")

    @staticmethod
    def unpack(
        result: Any,
    ) -> tuple[http.client.HTTPSConnection | None, http.client.HTTPResponse]:
        if isinstance(result, tuple) and len(result) == 2:
            return result[0], result[1]
        return None, result

    @staticmethod
    def close(
        connection: http.client.HTTPSConnection | None,
        response: Any,
    ) -> None:
        for resource in (response, connection):
            close = getattr(resource, "close", None)
            if callable(close):
                try:
                    close()
                except OSError:
                    pass
