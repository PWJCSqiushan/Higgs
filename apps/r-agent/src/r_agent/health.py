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
        self._connected = False
        self._lock = threading.Lock()

    def set_connected(self, connected: bool) -> None:
        with self._lock:
            self._connected = connected
        self.write()

    def write(self) -> None:
        with self._lock:
            payload = {
                "schema": 1,
                "pid": os.getpid(),
                "connected": self._connected,
                "updated_at_unix": time.time(),
            }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    async def run_periodically(self) -> None:
        while True:
            await asyncio.to_thread(self.write)
            await asyncio.sleep(self.interval_seconds)


def check_health(path: Path, *, max_age_seconds: float = 90.0) -> tuple[bool, str]:
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
    return True, "ok"
