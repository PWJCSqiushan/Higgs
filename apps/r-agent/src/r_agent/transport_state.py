"""Persistent, redacted transport observability for the live QQ adapter.

The state database deliberately stores only transport facts and bounded reason
codes.  It never stores account identifiers, credentials, message payloads, or
provider responses.  A single process owns this store at runtime, but each
operation uses a short SQLite transaction so a restart leaves an auditable
transition history behind.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

_SAFE_CODE = re.compile(r"[^A-Za-z0-9_.:-]+")
_STATES = {"pending", "verified", "rejected"}
_RECEIPT_STATES = {"ok", "failed", "unknown"}
_UNSET = object()


class TransportStateError(RuntimeError):
    """A transport state operation failed or received invalid data."""


def _now_ms() -> int:
    return int(time.time() * 1000)


def _code(value: str | None, *, default: str = "", maximum: int = 120) -> str:
    """Return a bounded, log-safe code rather than arbitrary input text."""

    if value is None:
        return default
    clean = str(value).strip()
    if not clean or len(clean) > maximum or _SAFE_CODE.search(clean):
        return default
    return clean


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    return bool(value)


@dataclass(frozen=True, slots=True)
class TransportSnapshot:
    """Current anonymous health dimensions and incident timing."""

    channel: str
    state: str
    incident_id: int
    state_started_at_ms: int
    duration_ms: int
    napcat_container_alive: bool | None
    onebot_reachable: bool
    qq_online: bool
    account_match: bool | None
    last_action_state: str
    last_action_reason: str
    last_action_at_ms: int | None
    last_health_state: str
    last_health_reason: str
    last_health_at_ms: int | None
    kick_reason: str | None
    recovery_result: str | None
    recovery_at_ms: int | None
    updated_at_ms: int

    @property
    def container_alive(self) -> bool | None:
        """Backward-compatible alias for the NapCat container signal."""

        return self.napcat_container_alive

    @property
    def fault_duration_ms(self) -> int:
        """Compatibility alias for consumers that call it fault duration."""

        return self.duration_ms if self.state != "verified" else 0

    def as_dict(self, *, now_ms: int | None = None) -> dict[str, object]:
        """Return a JSON-friendly redacted representation."""

        now = _now_ms() if now_ms is None else now_ms
        duration = max(0, now - self.state_started_at_ms)
        return {
            "channel": self.channel,
            "state": self.state,
            "incident_id": self.incident_id,
            "state_started_at_ms": self.state_started_at_ms,
            "duration_ms": duration,
            "container_alive": self.napcat_container_alive,
            "napcat_container_alive": self.napcat_container_alive,
            "onebot_reachable": self.onebot_reachable,
            "qq_online": self.qq_online,
            "account_match": self.account_match,
            "last_action_state": self.last_action_state,
            "last_action_reason": self.last_action_reason,
            "last_action_at_ms": self.last_action_at_ms,
            "last_health_state": self.last_health_state,
            "last_health_reason": self.last_health_reason,
            "last_health_at_ms": self.last_health_at_ms,
            "kick_reason": self.kick_reason,
            "recovery_result": self.recovery_result,
            "recovery_at_ms": self.recovery_at_ms,
            "updated_at_ms": self.updated_at_ms,
        }


@dataclass(frozen=True, slots=True)
class TransportTransition:
    """A completed or active state interval."""

    transition_id: int
    channel: str
    from_state: str | None
    to_state: str
    reason: str
    incident_id: int
    started_at_ms: int
    ended_at_ms: int | None
    duration_ms: int | None


class TransportStateStore:
    """SQLite-backed transport state with redacted transition history."""

    DEFAULT_CHANNEL = "onebot"
    SCHEMA_VERSION = 2

    def __init__(self, path: Path, *, channel: str = DEFAULT_CHANNEL) -> None:
        clean_channel = _code(channel, default=self.DEFAULT_CHANNEL, maximum=40).casefold()
        if not clean_channel:
            raise TransportStateError("transport channel is invalid")
        self.path = path.expanduser().resolve()
        self.channel = clean_channel
        self._lock = threading.RLock()

    def initialize(self) -> None:
        """Create the state and transition tables, without recording secrets."""

        now = _now_ms()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, closing(sqlite3.connect(self.path, timeout=10)) as conn:
            conn.execute("PRAGMA busy_timeout = 10000")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS transport_state (
                    channel TEXT PRIMARY KEY,
                    state TEXT NOT NULL CHECK(state IN ('pending', 'verified', 'rejected')),
                    incident_id INTEGER NOT NULL DEFAULT 0,
                    state_started_at_ms INTEGER NOT NULL,
                    -- Retained for old readers; the canonical field below is
                    -- explicitly named to prevent confusing it with Agent liveness.
                    container_alive INTEGER,
                    napcat_container_alive INTEGER,
                    onebot_reachable INTEGER NOT NULL DEFAULT 0,
                    qq_online INTEGER NOT NULL DEFAULT 0,
                    account_match INTEGER,
                    last_action_state TEXT NOT NULL DEFAULT 'unknown',
                    last_action_reason TEXT NOT NULL DEFAULT '',
                    last_action_at_ms INTEGER,
                    last_health_state TEXT NOT NULL DEFAULT 'unknown',
                    last_health_reason TEXT NOT NULL DEFAULT '',
                    last_health_at_ms INTEGER,
                    kick_reason TEXT,
                    recovery_result TEXT,
                    recovery_at_ms INTEGER,
                    incident_alerted_at_ms INTEGER,
                    recovery_alerted_at_ms INTEGER,
                    updated_at_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transport_transitions (
                    transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    incident_id INTEGER NOT NULL,
                    started_at_ms INTEGER NOT NULL,
                    ended_at_ms INTEGER,
                    duration_ms INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_transport_transitions_channel_time
                    ON transport_transitions(channel, started_at_ms DESC);
                """
            )
            columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(transport_state)").fetchall()
            }
            if "napcat_container_alive" not in columns:
                conn.execute(
                    "ALTER TABLE transport_state ADD COLUMN napcat_container_alive INTEGER"
                )
                # Rows written by schema v1 used ``container_alive`` for the
                # Agent reporter process.  Do not reinterpret those values as
                # NapCat health; the next real marker/probe will populate both.
                conn.execute(
                    "UPDATE transport_state SET container_alive = NULL, "
                    "napcat_container_alive = NULL"
                )
            conn.execute(
                """
                INSERT OR IGNORE INTO transport_state(
                    channel, state, incident_id, state_started_at_ms,
                    updated_at_ms
                ) VALUES (?, 'pending', 0, ?, ?)
                """,
                (self.channel, now, now),
            )
            conn.execute(
                """
                INSERT INTO transport_transitions(
                    channel, from_state, to_state, reason, incident_id, started_at_ms
                )
                SELECT ?, NULL, 'pending', 'startup', 0, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM transport_transitions WHERE channel = ?
                )
                """,
                (self.channel, now, self.channel),
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    @staticmethod
    def _row_snapshot(row: sqlite3.Row, *, now_ms: int | None = None) -> TransportSnapshot:
        now = _now_ms() if now_ms is None else now_ms
        return TransportSnapshot(
            channel=str(row["channel"]),
            state=str(row["state"]),
            incident_id=int(row["incident_id"]),
            state_started_at_ms=int(row["state_started_at_ms"]),
            duration_ms=max(0, now - int(row["state_started_at_ms"])),
            napcat_container_alive=_optional_bool(
                row["napcat_container_alive"]
                if "napcat_container_alive" in row
                else row["container_alive"]
            ),
            onebot_reachable=bool(row["onebot_reachable"]),
            qq_online=bool(row["qq_online"]),
            account_match=_optional_bool(row["account_match"]),
            last_action_state=str(row["last_action_state"]),
            last_action_reason=str(row["last_action_reason"]),
            last_action_at_ms=(
                int(row["last_action_at_ms"]) if row["last_action_at_ms"] is not None else None
            ),
            last_health_state=str(row["last_health_state"]),
            last_health_reason=str(row["last_health_reason"]),
            last_health_at_ms=(
                int(row["last_health_at_ms"]) if row["last_health_at_ms"] is not None else None
            ),
            kick_reason=str(row["kick_reason"]) if row["kick_reason"] else None,
            recovery_result=(str(row["recovery_result"]) if row["recovery_result"] else None),
            recovery_at_ms=(
                int(row["recovery_at_ms"]) if row["recovery_at_ms"] is not None else None
            ),
            updated_at_ms=int(row["updated_at_ms"]),
        )

    def snapshot(self, *, now_ms: int | None = None) -> TransportSnapshot:
        self.initialize()
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM transport_state WHERE channel = ?", (self.channel,)
            ).fetchone()
        if row is None:
            raise TransportStateError("transport state row is missing")
        return self._row_snapshot(row, now_ms=now_ms)

    def record_transition(
        self,
        state: str,
        *,
        reason: str,
        now_ms: int | None = None,
        container_alive: bool | None | object = _UNSET,
        napcat_container_alive: bool | None | object = _UNSET,
        onebot_reachable: bool | None = None,
        qq_online: bool | None = None,
        account_match: bool | None = None,
        kick_reason: str | None = None,
        health_receipt: tuple[str, str] | None = None,
    ) -> TransportSnapshot:
        """Record dimensions and close/open an interval when state changes.

        ``health_receipt`` is ``(state, reason)`` and accepts only ``ok``,
        ``failed`` or ``unknown``.  Event hints such as a kick should omit it
        so the latest active probe remains distinguishable from a notification.
        """

        if state not in _STATES:
            raise TransportStateError("transport state is invalid")
        now = _now_ms() if now_ms is None else int(now_ms)
        bounded_reason = _code(reason, default="unspecified")
        bounded_kick = _code(kick_reason, default="") or None
        receipt_state: str | None = None
        receipt_reason = ""
        if health_receipt is not None:
            receipt_state, raw_receipt_reason = health_receipt
            if receipt_state not in _RECEIPT_STATES:
                raise TransportStateError("health receipt state is invalid")
            receipt_reason = _code(raw_receipt_reason, default=bounded_reason)

        self.initialize()
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM transport_state WHERE channel = ?", (self.channel,)
            ).fetchone()
            if row is None:
                raise TransportStateError("transport state row is missing")
            previous_state = str(row["state"])
            previous_online = bool(row["qq_online"])
            incident_id = int(row["incident_id"])
            state_started = int(row["state_started_at_ms"])
            if previous_state != state:
                duration = max(0, now - state_started)
                conn.execute(
                    """
                    UPDATE transport_transitions
                    SET ended_at_ms = ?, duration_ms = ?
                    WHERE transition_id = (
                        SELECT transition_id FROM transport_transitions
                        WHERE channel = ? AND ended_at_ms IS NULL
                        ORDER BY transition_id DESC LIMIT 1
                    )
                    """,
                    (now, duration, self.channel),
                )
                entered_rejected = state == "rejected" and previous_state != "rejected"
                if (previous_online and not bool(qq_online)) or entered_rejected:
                    incident_id += 1
                conn.execute(
                    """
                    INSERT INTO transport_transitions(
                        channel, from_state, to_state, reason, incident_id, started_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.channel,
                        previous_state,
                        state,
                        bounded_reason,
                        incident_id,
                        now,
                    ),
                )
                state_started = now

            # A verified state is authoritative only when account matching was
            # confirmed; callers can still use a pending/rejected state while
            # the transport itself remains reachable.
            values: dict[str, object] = {
                "state": state,
                "incident_id": incident_id,
                "state_started_at_ms": state_started,
                "updated_at_ms": now,
            }
            if (
                container_alive is not _UNSET
                and napcat_container_alive is not _UNSET
                and container_alive != napcat_container_alive
            ):
                raise TransportStateError("NapCat container signals disagree")
            signal = (
                napcat_container_alive if napcat_container_alive is not _UNSET else container_alive
            )
            if signal is not _UNSET:
                normalized_signal = None if signal is None else int(bool(signal))
                values["container_alive"] = normalized_signal
                values["napcat_container_alive"] = normalized_signal
            if onebot_reachable is not None:
                values["onebot_reachable"] = int(onebot_reachable)
            if qq_online is not None:
                values["qq_online"] = int(qq_online)
            values["account_match"] = int(account_match) if account_match is not None else None
            if bounded_kick is not None or state != "verified":
                values["kick_reason"] = bounded_kick
            if previous_state != "verified" and state == "verified":
                values["recovery_result"] = "recovered"
                values["recovery_at_ms"] = now
                values["recovery_alerted_at_ms"] = None
            elif previous_state == "verified" and state != "verified":
                values["recovery_result"] = None
                values["recovery_at_ms"] = None
                values["incident_alerted_at_ms"] = None
            if receipt_state is not None:
                values.update(
                    {
                        "last_action_state": receipt_state,
                        "last_action_reason": receipt_reason,
                        "last_action_at_ms": now,
                        "last_health_state": receipt_state,
                        "last_health_reason": receipt_reason,
                        "last_health_at_ms": now,
                    }
                )
            assignments = ", ".join(f"{key} = ?" for key in values)
            conn.execute(
                f"UPDATE transport_state SET {assignments} WHERE channel = ?",
                (*values.values(), self.channel),
            )
            conn.commit()
        return self.snapshot(now_ms=now)

    def status(self, *, now_ms: int | None = None) -> dict[str, object]:
        """Return the same redacted status shape used by owner commands."""

        return self.snapshot(now_ms=now_ms).as_dict(now_ms=now_ms)

    def record_health_receipt(
        self,
        state: str,
        *,
        reason: str,
        now_ms: int | None = None,
    ) -> TransportSnapshot:
        """Persist a redacted active-probe/action receipt without changing state."""

        if state not in _RECEIPT_STATES:
            raise TransportStateError("health receipt state is invalid")
        now = _now_ms() if now_ms is None else int(now_ms)
        bounded_reason = _code(reason, default="unspecified")
        self.initialize()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE transport_state
                SET last_action_state = ?, last_action_reason = ?, last_action_at_ms = ?,
                    last_health_state = ?, last_health_reason = ?, last_health_at_ms = ?,
                    updated_at_ms = ?
                WHERE channel = ?
                """,
                (
                    state,
                    bounded_reason,
                    now,
                    state,
                    bounded_reason,
                    now,
                    now,
                    self.channel,
                ),
            )
            conn.commit()
        return self.snapshot(now_ms=now)

    def record_recovery(
        self,
        result: str,
        *,
        reason: str = "recovery",
        now_ms: int | None = None,
    ) -> TransportSnapshot:
        """Record an operator/reconnect recovery result as a bounded code."""

        now = _now_ms() if now_ms is None else int(now_ms)
        bounded_result = _code(result, default="unknown", maximum=80)
        bounded_reason = _code(reason, default="recovery")
        self.initialize()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE transport_state
                SET recovery_result = ?, recovery_at_ms = ?, last_health_reason = ?,
                    last_health_at_ms = ?, updated_at_ms = ?
                WHERE channel = ?
                """,
                (
                    bounded_result,
                    now,
                    bounded_reason,
                    now,
                    now,
                    self.channel,
                ),
            )
            conn.commit()
        return self.snapshot(now_ms=now)

    def claim_alert(self, kind: str, incident_id: int, *, now_ms: int | None = None) -> bool:
        """Atomically claim one incident/recovery alert for a process or restart."""

        if kind not in {"incident", "recovery"}:
            raise TransportStateError("alert kind is invalid")
        column = "incident_alerted_at_ms" if kind == "incident" else "recovery_alerted_at_ms"
        now = _now_ms() if now_ms is None else int(now_ms)
        self.initialize()
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT incident_id, {column} FROM transport_state WHERE channel = ?",
                (self.channel,),
            ).fetchone()
            if row is None or int(row["incident_id"]) != incident_id or row[column] is not None:
                return False
            conn.execute(
                f"UPDATE transport_state SET {column} = ?, updated_at_ms = ? "
                "WHERE channel = ? AND "
                f"{column} IS NULL",
                (now, now, self.channel),
            )
            claimed = conn.total_changes > 0
            conn.commit()
        return claimed

    def transitions(self, *, limit: int = 50) -> tuple[TransportTransition, ...]:
        if not 1 <= limit <= 500:
            raise TransportStateError("transition limit is invalid")
        self.initialize()
        with self._lock, closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT transition_id, channel, from_state, to_state, reason, incident_id,
                       started_at_ms, ended_at_ms, duration_ms
                FROM transport_transitions
                WHERE channel = ?
                ORDER BY transition_id DESC LIMIT ?
                """,
                (self.channel, limit),
            ).fetchall()
        return tuple(
            TransportTransition(
                transition_id=int(row["transition_id"]),
                channel=str(row["channel"]),
                from_state=str(row["from_state"]) if row["from_state"] else None,
                to_state=str(row["to_state"]),
                reason=str(row["reason"]),
                incident_id=int(row["incident_id"]),
                started_at_ms=int(row["started_at_ms"]),
                ended_at_ms=int(row["ended_at_ms"]) if row["ended_at_ms"] is not None else None,
                duration_ms=int(row["duration_ms"]) if row["duration_ms"] is not None else None,
            )
            for row in rows
        )
