"""Scoped, retention-bound short-term dialogue history."""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from r_agent.events import InboundEvent


class ConversationError(RuntimeError):
    """Base error for dialogue history operations."""


class ConversationConflictError(ConversationError):
    """The same inbound message was assigned a different outcome."""


class ConversationValidationError(ConversationError):
    """Dialogue data is missing or exceeds a safety bound."""


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    turn_id: str
    channel: str
    account_id: str
    conversation_kind: str
    conversation_id: str
    principal_id: str
    inbound_message_id: str
    user_text: str
    assistant_text: str | None
    outcome: str
    created_at_ms: int


class ConversationStore:
    OUTCOMES = frozenset({"drafted", "sent", "model_failed", "send_failed"})

    def __init__(self, path: Path) -> None:
        self.path = path

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
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    turn_id TEXT PRIMARY KEY,
                    channel TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    conversation_kind TEXT NOT NULL
                        CHECK(conversation_kind IN ('private','group')),
                    conversation_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    inbound_message_id TEXT NOT NULL,
                    user_text TEXT NOT NULL,
                    assistant_text TEXT,
                    outcome TEXT NOT NULL CHECK(outcome IN (
                        'drafted','sent','model_failed','send_failed'
                    )),
                    created_at_ms INTEGER NOT NULL,
                    UNIQUE(channel, account_id, inbound_message_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversation_recent
                ON conversation_turns(
                    channel, account_id, conversation_kind, conversation_id,
                    principal_id, outcome, created_at_ms DESC, turn_id DESC
                )
                """
            )

    @staticmethod
    def _clean(value: str, *, field: str, limit: int) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ConversationValidationError(f"{field} is required")
        if len(cleaned) > limit:
            raise ConversationValidationError(f"{field} exceeds {limit} characters")
        return cleaned

    @staticmethod
    def _row_to_turn(row: sqlite3.Row) -> ConversationTurn:
        return ConversationTurn(
            turn_id=str(row["turn_id"]),
            channel=str(row["channel"]),
            account_id=str(row["account_id"]),
            conversation_kind=str(row["conversation_kind"]),
            conversation_id=str(row["conversation_id"]),
            principal_id=str(row["principal_id"]),
            inbound_message_id=str(row["inbound_message_id"]),
            user_text=str(row["user_text"]),
            assistant_text=(
                str(row["assistant_text"]) if row["assistant_text"] is not None else None
            ),
            outcome=str(row["outcome"]),
            created_at_ms=int(row["created_at_ms"]),
        )

    def record(
        self,
        event: InboundEvent,
        *,
        principal_id: str,
        outcome: str,
        assistant_text: str | None,
        now_ms: int | None = None,
    ) -> ConversationTurn:
        clean_principal = self._clean(principal_id, field="principal_id", limit=128)
        clean_user = self._clean(event.text, field="user_text", limit=16_000)
        if outcome not in self.OUTCOMES:
            raise ConversationValidationError("unsupported conversation outcome")
        clean_assistant: str | None = None
        if assistant_text is not None:
            clean_assistant = self._clean(
                assistant_text,
                field="assistant_text",
                limit=4_000,
            )
        if outcome in {"drafted", "sent", "send_failed"} and clean_assistant is None:
            raise ConversationValidationError("assistant_text is required for this outcome")
        if outcome == "model_failed" and clean_assistant is not None:
            raise ConversationValidationError("model_failed cannot contain assistant_text")

        timestamp = int(time.time() * 1000) if now_ms is None else now_ms
        if not isinstance(timestamp, int) or isinstance(timestamp, bool) or timestamp < 0:
            raise ConversationValidationError("now_ms must be a non-negative integer")
        turn_id = str(uuid.uuid4())
        expected = (
            event.conversation_kind.value,
            event.conversation_id,
            clean_principal,
            clean_user,
            clean_assistant,
            outcome,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO conversation_turns(
                    turn_id, channel, account_id, conversation_kind,
                    conversation_id, principal_id, inbound_message_id,
                    user_text, assistant_text, outcome, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_id,
                    event.channel,
                    event.account_id,
                    *expected[:3],
                    event.message_id,
                    *expected[3:],
                    timestamp,
                ),
            )
            row = conn.execute(
                """
                SELECT * FROM conversation_turns
                WHERE channel = ? AND account_id = ? AND inbound_message_id = ?
                """,
                (event.channel, event.account_id, event.message_id),
            ).fetchone()
        if row is None:
            raise ConversationError("conversation turn could not be persisted")
        actual = (
            str(row["conversation_kind"]),
            str(row["conversation_id"]),
            str(row["principal_id"]),
            str(row["user_text"]),
            str(row["assistant_text"]) if row["assistant_text"] is not None else None,
            str(row["outcome"]),
        )
        if actual != expected:
            raise ConversationConflictError(
                "inbound message already has a different conversation outcome"
            )
        return self._row_to_turn(row)

    def recent(
        self,
        *,
        channel: str,
        account_id: str,
        conversation_kind: str,
        conversation_id: str,
        principal_id: str,
        outcome: str,
        limit: int = 8,
    ) -> list[ConversationTurn]:
        if outcome not in {"drafted", "sent"}:
            raise ConversationValidationError("history outcome must be drafted or sent")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise ConversationValidationError("history limit must be between 1 and 20")
        params = (
            self._clean(channel, field="channel", limit=32),
            self._clean(account_id, field="account_id", limit=64),
            self._clean(conversation_kind, field="conversation_kind", limit=16),
            self._clean(conversation_id, field="conversation_id", limit=256),
            self._clean(principal_id, field="principal_id", limit=128),
            outcome,
            limit,
        )
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM (
                    SELECT rowid AS insertion_seq, * FROM conversation_turns
                    WHERE channel = ? AND account_id = ?
                      AND conversation_kind = ? AND conversation_id = ?
                      AND principal_id = ? AND outcome = ?
                    ORDER BY created_at_ms DESC, rowid DESC
                    LIMIT ?
                )
                ORDER BY created_at_ms ASC, insertion_seq ASC
                """,
                params,
            ).fetchall()
        return [self._row_to_turn(row) for row in rows]

    def recent_unanswered(
        self,
        *,
        channel: str,
        account_id: str,
        conversation_kind: str,
        conversation_id: str,
        principal_id: str,
        before_ms: int,
        max_age_ms: int = 600_000,
        limit: int = 2,
    ) -> list[ConversationTurn]:
        """Return recent model-failed questions so a follow-up can recover them."""

        if not isinstance(before_ms, int) or isinstance(before_ms, bool) or before_ms < 0:
            raise ConversationValidationError("before_ms must be a non-negative integer")
        if not 1_000 <= max_age_ms <= 3_600_000:
            raise ConversationValidationError("max_age_ms must be between 1000 and 3600000")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 4:
            raise ConversationValidationError("limit must be between 1 and 4")
        params = (
            self._clean(channel, field="channel", limit=32),
            self._clean(account_id, field="account_id", limit=64),
            self._clean(conversation_kind, field="conversation_kind", limit=16),
            self._clean(conversation_id, field="conversation_id", limit=256),
            self._clean(principal_id, field="principal_id", limit=128),
            max(0, before_ms - max_age_ms),
            before_ms,
            limit,
        )
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM (
                    SELECT rowid AS insertion_seq, * FROM conversation_turns
                    WHERE channel = ? AND account_id = ?
                      AND conversation_kind = ? AND conversation_id = ?
                      AND principal_id = ? AND outcome = 'model_failed'
                      AND created_at_ms BETWEEN ? AND ?
                    ORDER BY created_at_ms DESC, rowid DESC
                    LIMIT ?
                )
                ORDER BY created_at_ms ASC, insertion_seq ASC
                """,
                params,
            ).fetchall()
        return [self._row_to_turn(row) for row in rows]

    def purge_expired(self, retention_days: int, *, now_ms: int | None = None) -> int:
        if not 1 <= retention_days <= 30:
            raise ConversationValidationError("retention_days must be between 1 and 30")
        current = int(time.time() * 1000) if now_ms is None else now_ms
        cutoff = current - retention_days * 86_400_000
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM conversation_turns WHERE created_at_ms < ?",
                (cutoff,),
            )
            return int(cursor.rowcount)

    def delete_principal(self, principal_id: str) -> int:
        clean_principal = self._clean(principal_id, field="principal_id", limit=128)
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM conversation_turns WHERE principal_id = ?",
                (clean_principal,),
            )
            return int(cursor.rowcount)
