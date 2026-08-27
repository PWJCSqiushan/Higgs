"""Persistent, content-free QQ send budget and operational risk ledger."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RiskLimits:
    conversation_per_minute: int = 2
    global_per_minute: int = 6
    non_owner_per_hour: int = 20
    non_owner_per_day: int = 80
    owner_conversation_per_minute: int = 4
    owner_per_hour: int = 40
    owner_per_day: int = 120
    global_per_hour: int = 60
    global_per_day: int = 200

    def __post_init__(self) -> None:
        values = tuple(getattr(self, field) for field in self.__dataclass_fields__)
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in values
        ):
            raise ValueError("risk limits must be positive integers")
        if self.conversation_per_minute > self.global_per_minute:
            raise ValueError("conversation minute limit cannot exceed the global limit")
        if self.owner_conversation_per_minute > self.global_per_minute:
            raise ValueError("owner conversation minute limit cannot exceed the global limit")
        if self.non_owner_per_hour > self.global_per_hour:
            raise ValueError("non-owner hour limit cannot exceed the global limit")
        if self.owner_per_hour > self.global_per_hour:
            raise ValueError("owner hour limit cannot exceed the global limit")
        if self.non_owner_per_day > self.global_per_day:
            raise ValueError("non-owner day limit cannot exceed the global limit")
        if self.owner_per_day > self.global_per_day:
            raise ValueError("owner day limit cannot exceed the global limit")


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    allowed: bool
    reason: str
    reservation_id: int | None = None
    retry_after_seconds: int = 0


class RiskLedger:
    """Store only salted identifiers and bounded operational metadata, never message text."""

    _COUNTED_OUTCOMES = ("reserved", "sent", "unknown")
    _EVENT_TYPES = frozenset(
        {
            "reply",
            "reminder",
            "proactive",
            "inbound",
            "login",
            "logout",
            "kicked_offline",
            "qr_scan",
            "version",
            "transport",
            "rate_limit",
        }
    )
    _OUTCOMES = frozenset({"observed", "reserved", "sent", "failed", "unknown", "limited"})

    def __init__(self, path: Path, *, limits: RiskLimits | None = None) -> None:
        self.path = path
        self.limits = limits or RiskLimits()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS risk_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO risk_meta(key, value) VALUES ('hash_salt', ?)
                """,
                (secrets.token_hex(32),),
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS risk_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    actor_class TEXT NOT NULL CHECK(actor_class IN ('owner','non_owner','system')),
                    account_hash TEXT,
                    conversation_hash TEXT,
                    source_hash TEXT,
                    reason_code TEXT,
                    client_version TEXT,
                    transport_version TEXT,
                    egress_asn TEXT,
                    created_at_ms INTEGER NOT NULL
                )
                """
            )
            columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(risk_events)").fetchall()
            }
            if "source_hash" not in columns:
                conn.execute("ALTER TABLE risk_events ADD COLUMN source_hash TEXT")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_risk_time
                ON risk_events(created_at_ms, event_type, outcome)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_risk_conversation_time
                ON risk_events(conversation_hash, created_at_ms, outcome)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_risk_source_time
                ON risk_events(source_hash, created_at_ms, event_type)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS risk_conversation_state (
                    conversation_hash TEXT PRIMARY KEY,
                    latest_direction TEXT NOT NULL
                        CHECK(latest_direction IN ('inbound','outbound')),
                    changed_at_ms INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS risk_source_state (
                    conversation_hash TEXT PRIMARY KEY,
                    suspected_robot_until_ms INTEGER NOT NULL,
                    reason_code TEXT NOT NULL,
                    changed_at_ms INTEGER NOT NULL
                )
                """
            )

    def _hash(self, value: str | None) -> str | None:
        if value is None:
            return None
        with self._connect() as conn:
            salt = str(
                conn.execute("SELECT value FROM risk_meta WHERE key='hash_salt'").fetchone()[0]
            )
        return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()[:24]

    def _source_hash(self, conversation_id: str, source_id: str | None) -> str:
        """Hash one source while retaining conversation-wide send budgets."""

        source_key = (
            conversation_id
            if source_id is None
            else f"group-source\x00{conversation_id}\x00{source_id}"
        )
        value = self._hash(source_key)
        assert value is not None
        return value

    @staticmethod
    def _bounded_code(value: str | None, *, maximum: int = 120) -> str | None:
        if value is None:
            return None
        clean = "_".join(value.strip().split())[:maximum]
        return clean or None

    def record_event(
        self,
        event_type: str,
        *,
        outcome: str = "observed",
        actor_class: str = "system",
        account_id: str | None = None,
        conversation_id: str | None = None,
        reason_code: str | None = None,
        client_version: str | None = None,
        transport_version: str | None = None,
        egress_asn: str | None = None,
        now_ms: int | None = None,
    ) -> int:
        if event_type not in self._EVENT_TYPES:
            raise ValueError("unsupported risk event type")
        if outcome not in self._OUTCOMES:
            raise ValueError("unsupported risk outcome")
        if actor_class not in {"owner", "non_owner", "system"}:
            raise ValueError("unsupported actor class")
        now = int(time.time() * 1000) if now_ms is None else now_ms
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO risk_events(
                    event_type, outcome, actor_class, account_hash, conversation_hash,
                    reason_code, client_version, transport_version, egress_asn, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_type,
                    outcome,
                    actor_class,
                    self._hash(account_id),
                    self._hash(conversation_id),
                    self._bounded_code(reason_code),
                    self._bounded_code(client_version, maximum=64),
                    self._bounded_code(transport_version, maximum=64),
                    self._bounded_code(egress_asn, maximum=32),
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def note_inbound(
        self,
        conversation_id: str,
        *,
        actor_class: str = "non_owner",
        account_id: str | None = None,
        source_id: str | None = None,
        now_ms: int | None = None,
    ) -> bool:
        """Record no message text and return whether the source may be learned from.

        Twelve inbound messages in one minute from one non-owner source is treated as
        automation-like traffic. Group callers bind the source to the sender, so normal
        traffic from several humans cannot collectively trip a 24-hour cooldown.
        """
        now = int(time.time() * 1000) if now_ms is None else now_ms
        conversation_hash = self._hash(conversation_id)
        assert conversation_hash is not None
        source_hash = self._source_hash(conversation_id, source_id)
        account_hash = self._hash(account_id)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO risk_events(
                    event_type, outcome, actor_class, account_hash,
                    conversation_hash, source_hash, created_at_ms
                ) VALUES ('inbound', 'observed', ?, ?, ?, ?, ?)
                """,
                (actor_class, account_hash, conversation_hash, source_hash, now),
            )
            conn.execute(
                """
                INSERT INTO risk_conversation_state(
                    conversation_hash, latest_direction, changed_at_ms)
                VALUES (?, 'inbound', ?)
                ON CONFLICT(conversation_hash) DO UPDATE SET
                    latest_direction='inbound', changed_at_ms=excluded.changed_at_ms
                WHERE excluded.changed_at_ms >= risk_conversation_state.changed_at_ms
                """,
                (conversation_hash, now),
            )
            if actor_class != "owner":
                recent = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) FROM risk_events
                        WHERE event_type='inbound' AND source_hash=?
                          AND created_at_ms>=?
                        """,
                        (source_hash, now - 60_000),
                    ).fetchone()[0]
                )
                if recent >= 12:
                    conn.execute(
                        """
                        INSERT INTO risk_source_state(
                            conversation_hash, suspected_robot_until_ms,
                            reason_code, changed_at_ms
                        ) VALUES (?, ?, 'high_frequency_inbound', ?)
                        ON CONFLICT(conversation_hash) DO UPDATE SET
                            suspected_robot_until_ms=excluded.suspected_robot_until_ms,
                            reason_code=excluded.reason_code,
                            changed_at_ms=excluded.changed_at_ms
                        """,
                        (source_hash, now + 86_400_000, now),
                    )
        return self.learning_allowed(conversation_id, source_id=source_id, now_ms=now)

    def learning_allowed(
        self,
        conversation_id: str,
        *,
        source_id: str | None = None,
        now_ms: int | None = None,
    ) -> bool:
        now = int(time.time() * 1000) if now_ms is None else now_ms
        source_hash = self._source_hash(conversation_id, source_id)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT suspected_robot_until_ms FROM risk_source_state
                WHERE conversation_hash=?
                """,
                (source_hash,),
            ).fetchone()
        return row is None or int(row[0]) <= now

    def can_proactively_send(self, conversation_id: str) -> bool:
        conversation_hash = self._hash(conversation_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT latest_direction FROM risk_conversation_state WHERE conversation_hash=?",
                (conversation_hash,),
            ).fetchone()
        return row is not None and str(row[0]) == "inbound"

    def record_online_transition(
        self,
        *,
        online: bool,
        reason: str,
        now_ms: int | None = None,
    ) -> bool:
        """Persist only real QQ state transitions, not every successful probe."""
        now = int(time.time() * 1000) if now_ms is None else now_ms
        state = "online" if online else "offline"
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT value FROM risk_meta WHERE key='qq_state'").fetchone()
            if row is not None and str(row[0]) == state:
                return False
            conn.execute(
                """
                INSERT INTO risk_meta(key, value) VALUES ('qq_state', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (state,),
            )
            event_type = "login" if online else "logout"
            if not online and "kick" in reason.casefold():
                event_type = "kicked_offline"
            conn.execute(
                """
                INSERT INTO risk_events(
                    event_type, outcome, actor_class, reason_code, created_at_ms
                ) VALUES (?, 'observed', 'system', ?, ?)
                """,
                (event_type, self._bounded_code(reason), now),
            )
        return True

    def _count(
        self,
        conn: sqlite3.Connection,
        *,
        since_ms: int,
        actor_class: str | None = None,
        conversation_hash: str | None = None,
    ) -> int:
        clauses = ["created_at_ms >= ?", "outcome IN ('reserved','sent','unknown')"]
        params: list[object] = [since_ms]
        if actor_class is not None:
            clauses.append("actor_class = ?")
            params.append(actor_class)
        if conversation_hash is not None:
            clauses.append("conversation_hash = ?")
            params.append(conversation_hash)
        row = conn.execute(
            f"SELECT COUNT(*) FROM risk_events WHERE {' AND '.join(clauses)}", params
        ).fetchone()
        return int(row[0])

    def reserve_send(
        self,
        *,
        event_type: str,
        actor_class: str,
        account_id: str,
        conversation_id: str,
        source_id: str | None = None,
        now_ms: int | None = None,
    ) -> BudgetDecision:
        if event_type not in {"reply", "reminder", "proactive"}:
            raise ValueError("event type is not send-capable")
        if actor_class not in {"owner", "non_owner", "system"}:
            raise ValueError("unsupported actor class")
        now = int(time.time() * 1000) if now_ms is None else now_ms
        conversation_hash = self._hash(conversation_id)
        source_hash = self._source_hash(conversation_id, source_id)
        account_hash = self._hash(account_id)
        assert conversation_hash is not None
        actor_budget = "owner" if actor_class == "owner" else "non_owner"
        limits = self.limits
        checks = (
            (
                "conversation_minute",
                self._count,
                now - 60_000,
                limits.owner_conversation_per_minute
                if actor_budget == "owner"
                else limits.conversation_per_minute,
                actor_budget,
                conversation_hash,
                60,
            ),
            ("global_minute", self._count, now - 60_000, limits.global_per_minute, None, None, 60),
            (
                "actor_hour",
                self._count,
                now - 3_600_000,
                limits.owner_per_hour if actor_budget == "owner" else limits.non_owner_per_hour,
                actor_budget,
                None,
                3600,
            ),
            ("global_hour", self._count, now - 3_600_000, limits.global_per_hour, None, None, 3600),
            (
                "actor_day",
                self._count,
                now - 86_400_000,
                limits.owner_per_day if actor_budget == "owner" else limits.non_owner_per_day,
                actor_budget,
                None,
                86_400,
            ),
            (
                "global_day",
                self._count,
                now - 86_400_000,
                limits.global_per_day,
                None,
                None,
                86_400,
            ),
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if actor_budget == "non_owner":
                source = conn.execute(
                    """
                    SELECT suspected_robot_until_ms FROM risk_source_state
                    WHERE conversation_hash=?
                    """,
                    (source_hash,),
                ).fetchone()
                if source is not None and int(source[0]) > now:
                    return BudgetDecision(
                        False,
                        "suspected_robot_source",
                        retry_after_seconds=max(1, (int(source[0]) - now + 999) // 1000),
                    )
            if event_type == "proactive":
                direction = conn.execute(
                    """
                    SELECT latest_direction FROM risk_conversation_state
                    WHERE conversation_hash=?
                    """,
                    (conversation_hash,),
                ).fetchone()
                if direction is None or str(direction[0]) != "inbound":
                    return BudgetDecision(False, "self_continuation_blocked")
            for reason, counter, since, limit, actor, conversation, retry in checks:
                if (
                    counter(
                        conn,
                        since_ms=since,
                        actor_class=actor,
                        conversation_hash=conversation,
                    )
                    >= limit
                ):
                    conn.execute(
                        """
                        INSERT INTO risk_events(
                            event_type, outcome, actor_class, account_hash,
                            conversation_hash, source_hash, reason_code, created_at_ms
                        ) VALUES ('rate_limit', 'limited', ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            actor_budget,
                            account_hash,
                            conversation_hash,
                            source_hash,
                            reason,
                            now,
                        ),
                    )
                    return BudgetDecision(False, reason, retry_after_seconds=retry)
            cursor = conn.execute(
                """
                INSERT INTO risk_events(
                    event_type, outcome, actor_class, account_hash,
                    conversation_hash, source_hash, created_at_ms
                ) VALUES (?, 'reserved', ?, ?, ?, ?, ?)
                """,
                (
                    event_type,
                    actor_budget,
                    account_hash,
                    conversation_hash,
                    source_hash,
                    now,
                ),
            )
            return BudgetDecision(True, "reserved", int(cursor.lastrowid))

    def finish_send(self, reservation_id: int, *, outcome: str) -> None:
        if outcome not in {"sent", "failed", "unknown"}:
            raise ValueError("send outcome must be sent, failed, or unknown")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT conversation_hash FROM risk_events WHERE id=? AND outcome='reserved'",
                (reservation_id,),
            ).fetchone()
            if row is None:
                return
            conn.execute(
                "UPDATE risk_events SET outcome=? WHERE id=? AND outcome='reserved'",
                (outcome, reservation_id),
            )
            if outcome in {"sent", "unknown"}:
                conn.execute(
                    """
                    INSERT INTO risk_conversation_state(
                        conversation_hash, latest_direction, changed_at_ms
                    )
                    SELECT conversation_hash, 'outbound', created_at_ms
                    FROM risk_events WHERE id=?
                    ON CONFLICT(conversation_hash) DO UPDATE SET
                        latest_direction='outbound', changed_at_ms=excluded.changed_at_ms
                    WHERE excluded.changed_at_ms >= risk_conversation_state.changed_at_ms
                    """,
                    (reservation_id,),
                )

    def stats(self, *, now_ms: int | None = None) -> dict[str, int]:
        now = int(time.time() * 1000) if now_ms is None else now_ms
        with self._connect() as conn:
            sent_day = int(
                conn.execute(
                    "SELECT COUNT(*) FROM risk_events WHERE created_at_ms>=? AND outcome='sent'",
                    (now - 86_400_000,),
                ).fetchone()[0]
            )
            failed_day = int(
                conn.execute(
                    "SELECT COUNT(*) FROM risk_events WHERE created_at_ms>=? AND outcome='failed'",
                    (now - 86_400_000,),
                ).fetchone()[0]
            )
            limited_day = int(
                conn.execute(
                    "SELECT COUNT(*) FROM risk_events WHERE created_at_ms>=? AND outcome='limited'",
                    (now - 86_400_000,),
                ).fetchone()[0]
            )
            peak = int(
                conn.execute(
                    """
                    SELECT COALESCE(MAX(total), 0) FROM (
                        SELECT COUNT(*) AS total FROM risk_events
                        WHERE created_at_ms>=? AND outcome='sent'
                        GROUP BY CAST(created_at_ms / 1800000 AS INTEGER)
                    )
                    """,
                    (now - 86_400_000,),
                ).fetchone()[0]
            )
            robot_sources = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM risk_source_state
                    WHERE suspected_robot_until_ms>?
                    """,
                    (now,),
                ).fetchone()[0]
            )
            kicked = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM risk_events
                    WHERE event_type='kicked_offline' AND created_at_ms>=?
                    """,
                    (now - 86_400_000,),
                ).fetchone()[0]
            )
        return {
            "sent_24h": sent_day,
            "failed_24h": failed_day,
            "limited_24h": limited_day,
            "peak_half_hour_24h": peak,
            "suspected_robot_sources": robot_sources,
            "kicked_offline_24h": kicked,
        }
