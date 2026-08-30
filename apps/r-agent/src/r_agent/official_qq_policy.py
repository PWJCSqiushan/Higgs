"""Small in-process gates shared by the official QQ adapters.

The durable Agent/sidecar protocol remains the source of truth for identity
and authorization.  These gates only bound channel volume and repeated local
failures; they never widen an allowlist and reset to the closed state after a
process restart.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable


class OfficialChannelGate:
    """Sliding-window rate limit plus a bounded failure circuit."""

    def __init__(
        self,
        *,
        rate_per_minute: int,
        failure_limit: int,
        cooldown_seconds: int,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        if rate_per_minute < 1:
            raise ValueError("channel rate must be positive")
        if failure_limit < 1:
            raise ValueError("channel failure limit must be positive")
        if cooldown_seconds < 1:
            raise ValueError("channel cooldown must be positive")
        self.rate_per_minute = rate_per_minute
        self.failure_limit = failure_limit
        self.cooldown_ms = cooldown_seconds * 1000
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._events: deque[int] = deque()
        self._failures = 0
        self._open_until_ms = 0
        self._lock = threading.Lock()

    def _now(self, now_ms: int | None) -> int:
        return self._clock_ms() if now_ms is None else now_ms

    def allow(self, *, now_ms: int | None = None) -> bool:
        now = self._now(now_ms)
        with self._lock:
            if now < self._open_until_ms:
                return False
            if self._open_until_ms:
                self._open_until_ms = 0
                self._failures = 0
            cutoff = now - 60_000
            while self._events and self._events[0] <= cutoff:
                self._events.popleft()
            if len(self._events) >= self.rate_per_minute:
                return False
            self._events.append(now)
            return True

    def record_failure(self, *, now_ms: int | None = None) -> None:
        now = self._now(now_ms)
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_limit:
                self._open_until_ms = now + self.cooldown_ms

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0

    def is_open(self, *, now_ms: int | None = None) -> bool:
        now = self._now(now_ms)
        with self._lock:
            return now < self._open_until_ms


__all__ = ["OfficialChannelGate"]
