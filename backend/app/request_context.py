from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator


_agent_user_id: ContextVar[str] = ContextVar(
    "agent_user_id", default="local-default"
)


def current_agent_user_id() -> str:
    return _agent_user_id.get()


def bind_agent_user_id(user_id: str | None) -> str:
    """Bind an owner for the current synchronous execution segment."""
    normalized = (user_id or "local-default").strip() or "local-default"
    _agent_user_id.set(normalized[:128])
    return normalized[:128]


@contextmanager
def agent_user_scope(user_id: str | None) -> Iterator[str]:
    """Bind the authenticated/request owner without storing it on a singleton."""
    normalized = (user_id or "local-default").strip() or "local-default"
    token = _agent_user_id.set(normalized[:128])
    try:
        yield normalized[:128]
    finally:
        _agent_user_id.reset(token)
