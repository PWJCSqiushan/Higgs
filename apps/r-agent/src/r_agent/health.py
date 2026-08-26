"""File-based runtime health heartbeat with no listening admin port."""

from __future__ import annotations

import asyncio
import json
import os
import re
import stat
import threading
import time
from pathlib import Path

_SAFE_REASON = re.compile(r"[^A-Za-z0-9_.:-]+")


def _safe_reason(reason: str) -> str:
    clean = str(reason).strip()
    if not clean or len(clean) > 120 or _SAFE_REASON.search(clean):
        return "unspecified"
    return clean


class NapCatHealthReader:
    """Read the atomic marker written by the NapCat container healthcheck.

    The marker is deliberately content-free.  Its mtime supplies freshness,
    while the regular-file and no-symlink checks keep a writable shared volume
    from becoming an arbitrary file reader.  ``False`` is returned for every
    unavailable or invalid marker so callers can fail closed.
    """

    def __init__(self, path: Path, *, max_age_seconds: float = 60.0) -> None:
        if not 5 <= max_age_seconds <= 60:
            raise ValueError("NapCat health marker age must be between 5 and 60 seconds")
        self.path = Path(path).expanduser()
        self.max_age_seconds = max_age_seconds

    def read(self) -> tuple[bool, str]:
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return False, "missing"
        except OSError:
            return False, "unreadable"
        if stat.S_ISLNK(info.st_mode):
            return False, "symlink"
        if not stat.S_ISREG(info.st_mode):
            return False, "not_regular"
        age = time.time() - info.st_mtime
        if age < -5:
            return False, "future"
        if age > self.max_age_seconds:
            return False, "stale"

        flags = os.O_RDONLY
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.path, flags | nofollow)
        except OSError:
            return False, "unreadable"
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                return False, "not_regular"
            if opened.st_size > 16:
                return False, "invalid"
            marker = os.read(descriptor, 16)
        except OSError:
            return False, "unreadable"
        finally:
            os.close(descriptor)
        if marker != b"ok":
            return False, "invalid"
        return True, "ok"


class HealthReporter:
    def __init__(
        self,
        path: Path,
        *,
        interval_seconds: float = 30.0,
        napcat_health_path: Path | None = None,
        napcat_health_max_age_seconds: float = 60.0,
    ) -> None:
        if not 5 <= interval_seconds <= 300:
            raise ValueError("health interval must be between 5 and 300 seconds")
        self.path = path.expanduser().resolve()
        self.interval_seconds = interval_seconds
        self._napcat_health_reader = (
            NapCatHealthReader(
                napcat_health_path,
                max_age_seconds=napcat_health_max_age_seconds,
            )
            if napcat_health_path is not None
            else None
        )
        # This is intentionally unknown until the NapCat healthcheck writes a
        # valid marker.  ``container_alive`` remains as a compatibility alias
        # in the JSON payload, but it never represents the Agent process.
        self._napcat_container_alive: bool | None = None
        self._napcat_health_reason = (
            "not_configured" if self._napcat_health_reader is None else "missing"
        )
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

    def set_napcat_container_alive(self, alive: bool) -> None:
        """Set an externally verified NapCat health state for local probes."""
        with self._lock:
            self._napcat_container_alive = bool(alive)
            self._napcat_health_reason = "external_probe"
        self.write()

    def set_container_alive(self, alive: bool) -> None:
        """Backward-compatible alias for the NapCat container health signal."""
        self.set_napcat_container_alive(alive)

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

    @property
    def napcat_container_alive(self) -> bool | None:
        with self._lock:
            return self._napcat_container_alive

    @property
    def napcat_health_reason(self) -> str:
        with self._lock:
            return self._napcat_health_reason

    def write(self) -> None:
        marker = (
            self._napcat_health_reader.read() if self._napcat_health_reader is not None else None
        )
        with self._lock:
            if marker is not None:
                self._napcat_container_alive, self._napcat_health_reason = marker
            payload = {
                "schema": 5,
                "pid": os.getpid(),
                "container_alive": self._napcat_container_alive,
                "napcat_container_alive": self._napcat_container_alive,
                "napcat_health_reason": self._napcat_health_reason,
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
    require_napcat_container: bool = True,
) -> tuple[bool, str]:
    try:
        payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
        connected = payload.get("connected") is True
        updated = float(payload["updated_at_unix"])
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False, "health_file_invalid"
    reachable = payload.get("onebot_reachable", connected) is True
    if not connected or not reachable:
        return False, "onebot_disconnected"
    if time.time() - updated > max_age_seconds:
        return False, "heartbeat_stale"
    if require_napcat_container and payload.get("napcat_container_alive") is not True:
        return False, "napcat_container_not_alive"
    if not require_napcat_container and payload.get("napcat_container_alive") is False:
        return False, "napcat_container_not_alive"
    if require_qq_online and payload.get("account_match") is False:
        return False, "wrong_qq_account"
    if require_qq_online and payload.get("qq_online") is not True:
        return False, "qq_offline"
    return True, "ok"
