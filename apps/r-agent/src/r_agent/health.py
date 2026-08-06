"""File-based runtime health heartbeat with no listening admin port."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from pathlib import Path


class HealthReporter:
    def __init__(self, path: Path, *, interval_seconds: float = 30.0) -> None:
        if not 5 <= interval_seconds <= 300:
            raise ValueError("health interval must be between 5 and 300 seconds")
        self.path = path.expanduser().resolve()
        self.interval_seconds = interval_seconds
        self._transport_connected = False
        self._qq_online = False
        self._qq_state = "pending"
        self._qq_reason = "startup"
        self._lock = threading.Lock()

    def set_connected(self, connected: bool) -> None:
        """Backward-compatible alias for transport state."""
        self.set_transport_connected(connected)

    def set_transport_connected(self, connected: bool) -> None:
        with self._lock:
            self._transport_connected = connected
            if not connected:
                self._qq_online = False
                self._qq_state = "pending"
                self._qq_reason = "transport_disconnected"
        self.write()

    def set_qq_online(self, online: bool, *, reason: str = "probe") -> None:
        """Backward-compatible boolean setter."""
        self.set_qq_state("verified" if online else "rejected", reason=reason)

    def set_qq_state(self, state: str, *, reason: str = "probe") -> None:
        if state not in {"pending", "verified", "rejected"}:
            raise ValueError("QQ state must be pending, verified, or rejected")
        with self._lock:
            self._qq_state = state
            self._qq_online = state == "verified"
            self._qq_reason = reason[:120]
        self.write()

    @property
    def qq_online(self) -> bool:
        with self._lock:
            return self._qq_online

    def write(self) -> None:
        with self._lock:
            payload = {
                "schema": 3,
                "pid": os.getpid(),
                "connected": self._transport_connected,
                "transport_connected": self._transport_connected,
                "qq_online": self._qq_online,
                "qq_state": self._qq_state,
                "qq_reason": self._qq_reason,
                "updated_at_unix": time.time(),
            }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    async def run_periodically(self) -> None:
        while True:
            await asyncio.to_thread(self.write)
            await asyncio.sleep(self.interval_seconds)


def check_health(
    path: Path,
    *,
    max_age_seconds: float = 90.0,
    require_qq_online: bool = False,
) -> tuple[bool, str]:
    try:
        payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
        connected = payload.get("connected") is True
        updated = float(payload["updated_at_unix"])
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False, "health_file_invalid"
    if not connected:
        return False, "onebot_disconnected"
    if time.time() - updated > max_age_seconds:
        return False, "heartbeat_stale"
    if require_qq_online and payload.get("qq_online") is not True:
        return False, "qq_offline"
    return True, "ok"
