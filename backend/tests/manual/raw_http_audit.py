"""Fail-closed raw HTTP audit wrapper for the retest worker.

The wrapper is a real test-manual component, not a mock.  It writes the
response metadata and append-only request index after the provider response has
already been obtained.  If either write fails, the reservation must be failed
with the observed HTTP status and both the response and connection must be
closed before the original error is re-raised.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Callable


class _RawAuditResponse:
    def __init__(self, inner: Any, path: Path) -> None:
        self._inner = inner
        self._path = path
        self.status = getattr(inner, "status", None)
        self._p12_eval_reservation = getattr(inner, "_p12_eval_reservation", None)

    def readline(self, *args: Any, **kwargs: Any) -> bytes:
        data = self._inner.readline(*args, **kwargs)
        if data:
            with self._path.open("ab") as fh:
                fh.write(data)
        return data

    def read(self, *args: Any, **kwargs: Any) -> bytes:
        data = self._inner.read(*args, **kwargs)
        if data:
            with self._path.open("ab") as fh:
                fh.write(data)
        return data

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _close_quietly(target: Any) -> None:
    close = getattr(target, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def build_audited_stream_response(
    original_stream_response: Callable[..., Any],
    *,
    raw_dir: Path,
    root: Path,
    request: dict[str, Any],
    fail_eval: Callable[..., Any] | None = None,
) -> Callable[..., Any]:
    """Return the production audit wrapper with fail-closed write handling."""

    raw_dir = Path(raw_dir)
    root = Path(root)

    def audited_stream_response(*args: Any, **kwargs: Any) -> Any:
        connection, response = original_stream_response(*args, **kwargs)
        reservation = getattr(response, "_p12_eval_reservation", None)
        request_id = (
            getattr(reservation, "request_id", None)
            or f"unknown-{uuid.uuid4()}"
        )
        raw_path = raw_dir / f"{request_id}.http"
        meta_path = raw_dir / f"{request_id}.meta.json"
        payload = (args[0] if args else kwargs.get("payload") or {}) or {}
        status = getattr(response, "status", None)
        try:
            meta_path.write_text(
                json.dumps(
                    {
                        "schema": "cad-e2e-retest-02.raw-http.v1",
                        "request_id": request_id,
                        "case_id": os.getenv("P12_EVAL_CASE_ID"),
                        "step": request.get("step"),
                        "status": status,
                        "payload_model": payload.get("model"),
                        "path": str(raw_path),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            with (root / "model-http-index.jsonl").open(
                "a", encoding="utf-8"
            ) as fh:
                fh.write(
                    json.dumps(
                        {
                            "request_id": request_id,
                            "case_id": os.getenv(
                                "P12_EVAL_CASE_ID"
                            ),
                            "step": request.get("step"),
                            "status": status,
                            "raw_path": str(raw_path),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except Exception as error:
            settle_error: Exception | None = None
            try:
                if fail_eval is None:
                    from app.eval_request_guard import (
                        fail_eval_request as fail_eval_request_fn,
                    )

                    fail_eval_request_fn = fail_eval_request_fn
                else:
                    fail_eval_request_fn = fail_eval
                fail_eval_request_fn(
                    reservation,
                    error,
                    http_status=status,
                    # The response body has not been parsed yet.  Keep the
                    # request model separately and never infer an actual
                    # response model from it.
                    response={
                        "model": None,
                        "request_model": payload.get("model"),
                    },
                )
            except Exception as exc:  # persistence failure wins
                settle_error = exc
            finally:
                _close_quietly(response)
                _close_quietly(connection)
            if settle_error is not None:
                raise settle_error from error
            raise
        return connection, _RawAuditResponse(response, raw_path)

    return audited_stream_response
