"""Shared per-group chat timeline for NapCat group understanding (Higgs 3.0 M1).

The timeline is short-term context, not memory: it lets Higgs see what the
whole group has been saying (including messages that did not trigger a
reply), who said it, what was quoted, and what Higgs itself said.  It is
retention-bound, never feeds long-term memory directly, and is rendered to
the model strictly as untrusted data with non-identifying speaker aliases.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from r_agent.events import ConversationKind, InboundEvent, QuotedMessage

SHANGHAI = ZoneInfo("Asia/Shanghai")
_TEXT_LIMIT = 1_000
_RENDER_TEXT_LIMIT = 200
_QUOTE_RENDER_LIMIT = 60


class GroupTimelineError(RuntimeError):
    """Timeline storage failed or received invalid data."""


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    channel: str
    account_id: str
    group_id: str
    message_id: str
    sender_id: str
    sender_name: str | None
    is_self: bool
    text: str
    reply_to_message_id: str | None
    mentioned_self: bool
    occurred_at_ms: int


def speaker_alias(account_id: str, group_id: str, sender_id: str) -> str:
    """Stable, short, non-reversible tag that disambiguates identical names."""
    digest = hashlib.sha256(f"higgs-speaker\0{account_id}\0{group_id}\0{sender_id}".encode())
    return digest.hexdigest()[:4]


def _bounded(text: str, limit: int) -> str:
    single = " ".join(text.split())
    return single if len(single) <= limit else single[: limit - 1] + "…"


class GroupTimeline:
    def __init__(
        self,
        path: Path,
        *,
        retention_days: int = 7,
        per_group_cap: int = 2_000,
    ) -> None:
        if not 1 <= retention_days <= 90:
            raise ValueError("retention_days must be between 1 and 90")
        if not 100 <= per_group_cap <= 50_000:
            raise ValueError("per_group_cap must be between 100 and 50000")
        self.path = path
        self.retention_days = retention_days
        self.per_group_cap = per_group_cap

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS group_timeline (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    sender_name TEXT,
                    is_self INTEGER NOT NULL CHECK(is_self IN (0, 1)),
                    text TEXT NOT NULL,
                    reply_to_message_id TEXT,
                    mentioned_self INTEGER NOT NULL CHECK(mentioned_self IN (0, 1)),
                    occurred_at_ms INTEGER NOT NULL,
                    UNIQUE(channel, account_id, group_id, message_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_group_timeline_recent
                ON group_timeline(channel, account_id, group_id, occurred_at_ms DESC, id DESC)
                """
            )

    @staticmethod
    def _row(row: sqlite3.Row) -> TimelineEntry:
        return TimelineEntry(
            channel=str(row["channel"]),
            account_id=str(row["account_id"]),
            group_id=str(row["group_id"]),
            message_id=str(row["message_id"]),
            sender_id=str(row["sender_id"]),
            sender_name=row["sender_name"],
            is_self=bool(row["is_self"]),
            text=str(row["text"]),
            reply_to_message_id=row["reply_to_message_id"],
            mentioned_self=bool(row["mentioned_self"]),
            occurred_at_ms=int(row["occurred_at_ms"]),
        )

    def _insert(self, entry: TimelineEntry) -> bool:
        if not entry.message_id or not entry.group_id or not entry.sender_id:
            raise GroupTimelineError("timeline entry is missing identifiers")
        text = entry.text.strip()[:_TEXT_LIMIT]
        if not text:
            return False
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO group_timeline(
                    channel, account_id, group_id, message_id, sender_id, sender_name,
                    is_self, text, reply_to_message_id, mentioned_self, occurred_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.channel,
                    entry.account_id,
                    entry.group_id,
                    entry.message_id,
                    entry.sender_id,
                    entry.sender_name,
                    int(entry.is_self),
                    text,
                    entry.reply_to_message_id,
                    int(entry.mentioned_self),
                    entry.occurred_at_ms,
                ),
            )
            inserted = cursor.rowcount == 1
            if inserted:
                conn.execute(
                    """
                    DELETE FROM group_timeline
                    WHERE channel = ? AND account_id = ? AND group_id = ? AND id NOT IN (
                        SELECT id FROM group_timeline
                        WHERE channel = ? AND account_id = ? AND group_id = ?
                        ORDER BY occurred_at_ms DESC, id DESC LIMIT ?
                    )
                    """,
                    (
                        entry.channel,
                        entry.account_id,
                        entry.group_id,
                        entry.channel,
                        entry.account_id,
                        entry.group_id,
                        self.per_group_cap,
                    ),
                )
            return inserted

    def record_inbound(self, event: InboundEvent) -> bool:
        """Record one accepted group message, whether or not Higgs will reply."""
        if event.conversation_kind is not ConversationKind.GROUP or not event.group_id:
            return False
        return self._insert(
            TimelineEntry(
                channel=event.channel,
                account_id=event.account_id,
                group_id=event.group_id,
                message_id=event.message_id,
                sender_id=event.sender_id,
                sender_name=event.sender_name,
                is_self=False,
                text=event.timeline_text,
                reply_to_message_id=event.reply_message_id,
                mentioned_self=event.mentioned,
                occurred_at_ms=event.occurred_at_ms,
            )
        )

    def record_outbound(
        self,
        event: InboundEvent,
        *,
        text: str,
        provider_message_id: str | None,
        now_ms: int | None = None,
    ) -> bool:
        """Record what Higgs said in reply to ``event`` in the same group."""
        if event.conversation_kind is not ConversationKind.GROUP or not event.group_id:
            return False
        timestamp = int(time.time() * 1000) if now_ms is None else now_ms
        message_id = provider_message_id or f"self:{event.message_id}"
        return self._insert(
            TimelineEntry(
                channel=event.channel,
                account_id=event.account_id,
                group_id=event.group_id,
                message_id=message_id,
                sender_id=event.account_id,
                sender_name="Higgs",
                is_self=True,
                text=text,
                reply_to_message_id=event.message_id,
                mentioned_self=False,
                occurred_at_ms=max(timestamp, event.occurred_at_ms),
            )
        )

    def get(
        self, *, channel: str, account_id: str, group_id: str, message_id: str
    ) -> TimelineEntry | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT * FROM group_timeline
                WHERE channel = ? AND account_id = ? AND group_id = ? AND message_id = ?
                """,
                (channel, account_id, group_id, message_id),
            ).fetchone()
        return self._row(row) if row is not None else None

    def recent(
        self,
        *,
        channel: str,
        account_id: str,
        group_id: str,
        until_ms: int | None = None,
        limit: int = 30,
        max_age_ms: int = 6 * 3_600_000,
    ) -> list[TimelineEntry]:
        """Return up to ``limit`` entries at or before ``until_ms``, oldest first."""
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        upper = until_ms if until_ms is not None else int(time.time() * 1000)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM group_timeline
                WHERE channel = ? AND account_id = ? AND group_id = ?
                  AND occurred_at_ms <= ? AND occurred_at_ms >= ?
                ORDER BY occurred_at_ms DESC, id DESC LIMIT ?
                """,
                (channel, account_id, group_id, upper, upper - max_age_ms, limit),
            ).fetchall()
        return [self._row(row) for row in reversed(rows)]

    def others_after(self, event: InboundEvent, *, sender_id: str) -> int:
        """Count messages other members sent after ``event`` arrived (arrival order).

        OneBot timestamps only have second precision, so ordering uses the
        local insertion sequence instead of ``occurred_at_ms``.
        """
        if not event.group_id:
            return 0
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM group_timeline
                WHERE channel = ? AND account_id = ? AND group_id = ?
                  AND sender_id != ? AND is_self = 0
                  AND id > (
                    SELECT id FROM group_timeline
                    WHERE channel = ? AND account_id = ? AND group_id = ? AND message_id = ?
                  )
                """,
                (
                    event.channel,
                    event.account_id,
                    event.group_id,
                    sender_id,
                    event.channel,
                    event.account_id,
                    event.group_id,
                    event.message_id,
                ),
            ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def as_quoted(self, entry: TimelineEntry) -> QuotedMessage:
        return QuotedMessage(
            message_id=entry.message_id,
            sender_id=entry.sender_id,
            sender_name=entry.sender_name,
            text=entry.text,
            is_self=entry.is_self,
        )

    def purge_expired(self, *, now_ms: int | None = None) -> int:
        current = int(time.time() * 1000) if now_ms is None else now_ms
        cutoff = current - self.retention_days * 86_400_000
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute("DELETE FROM group_timeline WHERE occurred_at_ms < ?", (cutoff,))
            return int(cursor.rowcount)


def speaker_label(
    *,
    account_id: str,
    group_id: str,
    sender_id: str,
    sender_name: str | None,
    is_self: bool,
    owner_ids: frozenset[str],
) -> str:
    if is_self:
        return "Higgs(你自己)"
    alias = speaker_alias(account_id, group_id, sender_id)
    name = sender_name or "群友"
    role = "·主人" if sender_id in owner_ids else ""
    return f"{name}#{alias}{role}"


def render_timeline(
    entries: list[TimelineEntry],
    *,
    current: InboundEvent,
    owner_ids: frozenset[str],
    max_chars: int = 3_000,
) -> list[str]:
    """Render entries as bounded data lines, newest kept when over budget.

    The current event (and anything merged into it) is excluded so the model
    sees it exactly once, in the dedicated "current message" block.
    """
    if not current.group_id:
        return []
    by_id = {entry.message_id: entry for entry in entries}
    excluded = {current.message_id, *current.merged_message_ids}
    lines: list[str] = []
    for entry in entries:
        if entry.message_id in excluded:
            continue
        clock = datetime.fromtimestamp(entry.occurred_at_ms / 1000, SHANGHAI).strftime("%H:%M")
        label = speaker_label(
            account_id=entry.account_id,
            group_id=entry.group_id,
            sender_id=entry.sender_id,
            sender_name=entry.sender_name,
            is_self=entry.is_self,
            owner_ids=owner_ids,
        )
        quote = ""
        if entry.reply_to_message_id:
            target = by_id.get(entry.reply_to_message_id)
            if target is not None:
                target_label = speaker_label(
                    account_id=target.account_id,
                    group_id=target.group_id,
                    sender_id=target.sender_id,
                    sender_name=target.sender_name,
                    is_self=target.is_self,
                    owner_ids=owner_ids,
                )
                quote = f"(回复 {target_label}:「{_bounded(target.text, _QUOTE_RENDER_LIMIT)}」)"
            else:
                quote = "(回复一条较早的消息)"
        lines.append(f"[{clock}] {label}{quote}: {_bounded(entry.text, _RENDER_TEXT_LIMIT)}")
    total = 0
    kept: list[str] = []
    for line in reversed(lines):
        total += len(line) + 1
        if total > max_chars:
            break
        kept.append(line)
    return list(reversed(kept))


def render_current(
    event: InboundEvent,
    *,
    owner_ids: frozenset[str],
) -> list[str]:
    """Describe exactly whom Higgs is answering and what they quoted."""
    if not event.group_id:
        return []
    label = speaker_label(
        account_id=event.account_id,
        group_id=event.group_id,
        sender_id=event.sender_id,
        sender_name=event.sender_name,
        is_self=False,
        owner_ids=owner_ids,
    )
    lines = [f"- 发言人：{label}"]
    if event.quoted is not None:
        quoted_label = speaker_label(
            account_id=event.account_id,
            group_id=event.group_id,
            sender_id=event.quoted.sender_id,
            sender_name=event.quoted.sender_name,
            is_self=event.quoted.is_self or event.quoted.sender_id == event.account_id,
            owner_ids=owner_ids,
        )
        lines.append(f"- 对方引用了 {quoted_label} 的消息：「{_bounded(event.quoted.text, 300)}」")
    return lines
