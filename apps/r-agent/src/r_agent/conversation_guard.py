# ruff: noqa: E501
"""Persistent non-owner conversation circuit breaker."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GuardDecision:
    allowed: bool
    retry_after_seconds: int = 0


class ConversationCircuitBreaker:
    def __init__(
        self,
        path: Path,
        *,
        limit: int = 8,
        window_seconds: int = 1800,
        cooldown_seconds: int = 3600,
    ) -> None:
        self.path = path
        self.limit = limit
        self.window_ms = window_seconds * 1000
        self.cooldown_ms = cooldown_seconds * 1000

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_guard_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_guard_conversation_time
                ON conversation_guard_events(conversation_id, created_at_ms)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_guard_cooldowns (
                    conversation_id TEXT PRIMARY KEY,
                    until_ms INTEGER NOT NULL,
                    triggered_at_ms INTEGER NOT NULL
                )
                """
            )

    def check_and_reserve(
        self,
        conversation_id: str,
        *,
        is_owner: bool,
        now_ms: int | None = None,
    ) -> GuardDecision:
        if is_owner:
            return GuardDecision(True)
        now = int(time.time() * 1000) if now_ms is None else now_ms
        with sqlite3.connect(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT until_ms FROM conversation_guard_cooldowns WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if row is not None and int(row[0]) > now:
                return GuardDecision(False, max(1, (int(row[0]) - now + 999) // 1000))
            conn.execute(
                "DELETE FROM conversation_guard_events WHERE created_at_ms < ?",
                (now - self.window_ms,),
            )
            count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM conversation_guard_events WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()[0]
            )
            if count >= self.limit:
                until = now + self.cooldown_ms
                conn.execute(
                    """
                    INSERT INTO conversation_guard_cooldowns(conversation_id, until_ms, triggered_at_ms)
                    VALUES (?, ?, ?)
                    ON CONFLICT(conversation_id) DO UPDATE SET
                        until_ms=excluded.until_ms, triggered_at_ms=excluded.triggered_at_ms
                    """,
                    (conversation_id, until, now),
                )
                return GuardDecision(False, self.cooldown_ms // 1000)
            conn.execute(
                "INSERT INTO conversation_guard_events(conversation_id, created_at_ms) VALUES (?, ?)",
                (conversation_id, now),
            )
        return GuardDecision(True)

    def source_status(self, *, now_ms: int | None = None) -> dict[str, int]:
        now = int(time.time() * 1000) if now_ms is None else now_ms
        with sqlite3.connect(self.path) as conn:
            active = int(
                conn.execute(
                    "SELECT COUNT(*) FROM conversation_guard_cooldowns WHERE until_ms > ?",
                    (now,),
                ).fetchone()[0]
            )
            recent = int(
                conn.execute(
                    "SELECT COUNT(*) FROM conversation_guard_events WHERE created_at_ms >= ?",
                    (now - self.window_ms,),
                ).fetchone()[0]
            )
        return {"active_cooldowns": active, "recent_non_owner_replies": recent}
