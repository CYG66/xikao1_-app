from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Iterator


class UserRequestLimitError(RuntimeError):
    pass


class UserRequestLimiter:
    """Bound model calls per request owner without serializing all users."""

    def __init__(self) -> None:
        self.limit = self._read_int(
            "XLINE_AGENT_USER_MAX_CONCURRENT_REQUESTS", 2, minimum=1, maximum=16
        )
        self.acquire_timeout = self._read_float(
            "XLINE_AGENT_USER_QUEUE_TIMEOUT_SECONDS", 2.0, minimum=0.1, maximum=60.0
        )
        self._lock = threading.Lock()
        self._semaphores: dict[str, threading.BoundedSemaphore] = {}

    @staticmethod
    def _read_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
        try:
            value = int(os.getenv(name, str(default)))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    @staticmethod
    def _read_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
        try:
            value = float(os.getenv(name, str(default)))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    def _semaphore_for(self, user_id: str) -> threading.BoundedSemaphore:
        with self._lock:
            semaphore = self._semaphores.get(user_id)
            if semaphore is None:
                semaphore = threading.BoundedSemaphore(self.limit)
                self._semaphores[user_id] = semaphore
            return semaphore

    @contextmanager
    def acquire(self, user_id: str) -> Iterator[None]:
        semaphore = self._semaphore_for(user_id)
        if not semaphore.acquire(timeout=self.acquire_timeout):
            raise UserRequestLimitError(
                "当前用户的 AI 请求仍在处理中，请等待上一条回复完成后再试。"
            )
        try:
            yield
        finally:
            semaphore.release()


user_request_limiter = UserRequestLimiter()
