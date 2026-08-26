"""File-based runtime health heartbeat with no listening admin port."""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from pathlib import Path

_SAFE_REASON = re.compile(r"[^A-Za-z0-9_.:-]+")


def _safe_reason(reason: str) -> str:
    clean = str(reason).strip()
    if not clean or len(clean) > 120 or _SAFE_REASON.search(clean):
        return "unspecified"
    return clean


class HealthReporter:
    def __init__(self, path: Path, *, interval_seconds: float = 30.0) -> None:
        if not 5 <= interval_seconds <= 300:
            raise ValueError("health interval must be between 5 and 300 seconds")
        self.path = path.expanduser().resolve()
        self.interval_seconds = interval_seconds
        # ``container_alive`` means that this reporter process is alive.  A
        # stale heartbeat still makes the container unhealthy, so this field
        # is useful for an operator without pretending we can inspect Docker
        # from inside the agent container.
        self._container_alive = True
        self._transport_connected = False
        self._onebot_reachable = False
        self._qq_online = False
        self._qq_state = "pending"
        self._qq_reason = "startup"
        self._account_match: bool | None = None
        self._last_action_state = "unknown"
        self._last_action_reason = "startup"
        self._last_action_at_unix: float | None = None
        self._kick_reason: str | None = None
        self._lock = threading.Lock()

    def set_connected(self, connected: bool) -> None:
        """Backward-compatible alias for transport state."""
        self.set_transport_connected(connected)

    def set_transport_connected(self, connected: bool) -> None:
        with self._lock:
            self._transport_connected = connected
            self._onebot_reachable = connected
            if not connected:
                self._qq_online = False
                self._qq_state = "pending"
                self._qq_reason = "transport_disconnected"
                self._account_match = None
        self.write()

    def set_container_alive(self, alive: bool) -> None:
        """Override the process-derived container liveness for an external probe."""
        with self._lock:
            self._container_alive = bool(alive)
        self.write()

    def record_action_receipt(
        self,
        state: str,
        *,
        reason: str = "probe",
        at_unix: float | None = None,
    ) -> None:
        """Store a bounded probe/action outcome in the heartbeat file."""
        if state not in {"ok", "failed", "unknown"}:
            raise ValueError("action receipt state must be ok, failed, or unknown")
        with self._lock:
            self._last_action_state = state
            self._last_action_reason = _safe_reason(reason)
            self._last_action_at_unix = time.time() if at_unix is None else at_unix
        self.write()

    def set_account_match(self, match: bool | None) -> None:
        with self._lock:
            self._account_match = None if match is None else bool(match)
        self.write()

    def set_kick_reason(self, reason: str | None) -> None:
        with self._lock:
            self._kick_reason = _safe_reason(reason) if reason else None
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
            self._qq_reason = _safe_reason(reason)
        self.write()

    @property
    def qq_online(self) -> bool:
        with self._lock:
            return self._qq_online

    def write(self) -> None:
        with self._lock:
            payload = {
                "schema": 4,
                "pid": os.getpid(),
                "container_alive": self._container_alive,
                "connected": self._transport_connected,
                "transport_connected": self._transport_connected,
                "onebot_reachable": self._onebot_reachable,
                "qq_online": self._qq_online,
                "qq_state": self._qq_state,
                "qq_reason": self._qq_reason,
                "account_match": self._account_match,
                "last_action_state": self._last_action_state,
                "last_action_reason": self._last_action_reason,
                "last_action_at_unix": self._last_action_at_unix,
                "kick_reason": self._kick_reason,
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
    if payload.get("container_alive") is False:
        return False, "container_not_alive"
    reachable = payload.get("onebot_reachable", connected) is True
    if not connected or not reachable:
        return False, "onebot_disconnected"
    if time.time() - updated > max_age_seconds:
        return False, "heartbeat_stale"
    if require_qq_online and payload.get("qq_online") is not True:
        return False, "qq_offline"
    if require_qq_online and payload.get("account_match") is False:
        return False, "wrong_qq_account"
    return True, "ok"
