"""Append-only normalized conversation journal."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from r_agent.events import InboundEvent
from r_agent.identity import Principal


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS inbound_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    conversation_kind TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    group_id TEXT,
                    text TEXT NOT NULL,
                    mentioned INTEGER NOT NULL,
                    attachments_json TEXT NOT NULL,
                    occurred_at_ms INTEGER NOT NULL,
                    ingested_at_ms INTEGER NOT NULL,
                    UNIQUE(channel, account_id, message_id)
                )
                """
            )

    def append(self, event: InboundEvent, principal: Principal) -> bool:
        attachments = [
            {"kind": item.kind, "file_name": item.file_name} for item in event.attachments
        ]
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO inbound_events(
                    channel, account_id, message_id, principal_id,
                    conversation_kind, conversation_id, group_id, text,
                    mentioned, attachments_json, occurred_at_ms, ingested_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.channel,
                    event.account_id,
                    event.message_id,
                    principal.principal_id,
                    event.conversation_kind.value,
                    event.conversation_id,
                    event.group_id,
                    event.text,
                    int(event.mentioned),
                    json.dumps(attachments, ensure_ascii=False),
                    event.occurred_at_ms,
                    int(time.time() * 1000),
                ),
            )
            return cursor.rowcount == 1

    def purge_expired(self, retention_days: int, *, now_ms: int | None = None) -> int:
        current = now_ms if now_ms is not None else int(time.time() * 1000)
        cutoff = current - retention_days * 86_400_000
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                "DELETE FROM inbound_events WHERE occurred_at_ms < ?",
                (cutoff,),
            )
            return int(cursor.rowcount)

    def count(self) -> int:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM inbound_events").fetchone()
            return int(row[0]) if row else 0

    def delete_principal(self, principal_id: str) -> int:
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                "DELETE FROM inbound_events WHERE principal_id = ?",
                (principal_id,),
            )
            return int(cursor.rowcount)
