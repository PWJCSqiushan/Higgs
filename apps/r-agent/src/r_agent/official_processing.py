"""Durable Agent-side processing for official QQ inbound events."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from r_agent.access import IngressDecision
from r_agent.events import AttachmentRef, ConversationKind, InboundEvent
from r_agent.ingest import IngestResult
from r_agent.phase2_reply import PreparedReply, ReplyDecision, ReplyPlan

_log = logging.getLogger(__name__)


class OfficialProcessingError(RuntimeError):
    """Durable official processing state is invalid or unavailable."""


@dataclass(frozen=True, slots=True)
class OfficialWorkItem:
    batch_id: str
    state: str
    event: InboundEvent
    result: IngestResult
    prepared: PreparedReply | None
    final_plan: ReplyPlan | None
    attempts: int


def _event_to_json(event: InboundEvent) -> str:
    payload = asdict(event)
    payload["conversation_kind"] = event.conversation_kind.value
    payload["attachments"] = [asdict(item) for item in event.attachments]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _event_from_json(raw: str) -> InboundEvent:
    try:
        payload = json.loads(raw)
        attachments = tuple(AttachmentRef(**item) for item in payload.pop("attachments", []))
        payload["conversation_kind"] = ConversationKind(payload["conversation_kind"])
        return InboundEvent(**payload, attachments=attachments)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OfficialProcessingError("stored official event is invalid") from exc


def _result_to_json(result: IngestResult) -> str:
    return json.dumps(
        {
            "decision": result.decision.value,
            "stored": result.stored,
            "duplicate": result.duplicate,
        },
        separators=(",", ":"),
    )


def _result_from_json(raw: str) -> IngestResult:
    try:
        payload = json.loads(raw)
        return IngestResult(
            decision=IngressDecision(payload["decision"]),
            stored=bool(payload["stored"]),
            duplicate=bool(payload["duplicate"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OfficialProcessingError("stored official ingest result is invalid") from exc


def _merge_events(current: InboundEvent, incoming: InboundEvent) -> InboundEvent:
    if (
        current.channel,
        current.account_id,
        current.conversation_id,
        current.sender_id,
    ) != (
        incoming.channel,
        incoming.account_id,
        incoming.conversation_id,
        incoming.sender_id,
    ):
        raise OfficialProcessingError("cannot merge events from different sources")
    text = "\n".join(value for value in (current.text, incoming.text) if value).strip()
    attachments = (*current.attachments, *incoming.attachments)[:32]
    return replace(
        incoming,
        text=text,
        mentioned=current.mentioned or incoming.mentioned,
        replied_to_account=current.replied_to_account or incoming.replied_to_account,
        reply_message_id=incoming.reply_message_id or current.reply_message_id,
        attachments=attachments,
    )


class OfficialProcessingStore:
    """SQLite queue with explicit pre-provider and post-provider recovery states."""

    STATES = frozenset({"pending", "preparing", "prepared", "sending", "finalizing", "complete"})

    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self, *, now_ms: int | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        now = int(time.time() * 1000) if now_ms is None else now_ms
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS official_processing_batches (
                    batch_id TEXT PRIMARY KEY,
                    queue_key TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN (
                        'pending','preparing','prepared','sending','finalizing','complete'
                    )),
                    event_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    quiet_until_ms INTEGER NOT NULL,
                    retry_at_ms INTEGER NOT NULL DEFAULT 0,
                    prepared_decision TEXT,
                    prepared_text TEXT,
                    reservation_id INTEGER,
                    final_decision TEXT,
                    final_text TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error_code TEXT,
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_official_processing_ready
                ON official_processing_batches(state, retry_at_ms, quiet_until_ms, created_at_ms)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS official_processing_events (
                    channel TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL REFERENCES official_processing_batches(batch_id),
                    created_at_ms INTEGER NOT NULL,
                    PRIMARY KEY(channel, account_id, message_id)
                )
                """
            )
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE official_processing_batches
                SET state='pending', quiet_until_ms=?, retry_at_ms=?,
                    last_error_code='recovered_preparing', updated_at_ms=?
                WHERE state='preparing'
                """,
                (now, now, now),
            )
            conn.execute(
                """
                UPDATE official_processing_batches
                SET state='prepared', retry_at_ms=?,
                    last_error_code='recovered_sending', updated_at_ms=?
                WHERE state='sending'
                """,
                (now, now),
            )

    @staticmethod
    def _queue_key(event: InboundEvent) -> str:
        material = "\0".join(
            (event.channel, event.account_id, event.conversation_id, event.sender_id)
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def enqueue(
        self,
        event: InboundEvent,
        result: IngestResult,
        *,
        quiet_seconds: float,
        now_ms: int | None = None,
    ) -> bool:
        if event.channel.casefold() != "qq_official":
            raise OfficialProcessingError("only official QQ events may be queued")
        if result.decision is not IngressDecision.ACCEPT:
            return False
        if not 0.5 <= quiet_seconds <= 10:
            raise OfficialProcessingError("quiet_seconds must be between 0.5 and 10")
        now = int(time.time() * 1000) if now_ms is None else now_ms
        quiet_until = now + int(quiet_seconds * 1000)
        durable_result = IngestResult(
            decision=IngressDecision.ACCEPT,
            stored=True,
            duplicate=result.duplicate,
        )
        queue_key = self._queue_key(event)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            duplicate = conn.execute(
                """
                SELECT 1 FROM official_processing_events
                WHERE channel=? AND account_id=? AND message_id=?
                """,
                event.source_key,
            ).fetchone()
            if duplicate is not None:
                return False
            row = conn.execute(
                """
                SELECT batch_id, event_json FROM official_processing_batches
                WHERE queue_key=? AND state='pending'
                ORDER BY created_at_ms DESC LIMIT 1
                """,
                (queue_key,),
            ).fetchone()
            if row is None:
                batch_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO official_processing_batches(
                        batch_id, queue_key, state, event_json, result_json,
                        quiet_until_ms, retry_at_ms, created_at_ms, updated_at_ms
                    ) VALUES (?, ?, 'pending', ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        batch_id,
                        queue_key,
                        _event_to_json(event),
                        _result_to_json(durable_result),
                        quiet_until,
                        now,
                        now,
                    ),
                )
            else:
                batch_id = str(row["batch_id"])
                merged = _merge_events(_event_from_json(str(row["event_json"])), event)
                conn.execute(
                    """
                    UPDATE official_processing_batches
                    SET event_json=?, result_json=?, quiet_until_ms=?, updated_at_ms=?
                    WHERE batch_id=? AND state='pending'
                    """,
                    (
                        _event_to_json(merged),
                        _result_to_json(durable_result),
                        quiet_until,
                        now,
                        batch_id,
                    ),
                )
            conn.execute(
                """
                INSERT INTO official_processing_events(
                    channel, account_id, message_id, batch_id, created_at_ms
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (*event.source_key, batch_id, now),
            )
        return True

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> OfficialWorkItem:
        prepared = None
        if row["prepared_decision"] is not None:
            prepared = PreparedReply(
                decision=ReplyDecision(str(row["prepared_decision"])),
                text=str(row["prepared_text"]) if row["prepared_text"] is not None else None,
                reservation_id=(
                    int(row["reservation_id"]) if row["reservation_id"] is not None else None
                ),
            )
        final_plan = None
        if row["final_decision"] is not None:
            final_plan = ReplyPlan(
                ReplyDecision(str(row["final_decision"])),
                str(row["final_text"]) if row["final_text"] is not None else None,
            )
        return OfficialWorkItem(
            batch_id=str(row["batch_id"]),
            state=str(row["state"]),
            event=_event_from_json(str(row["event_json"])),
            result=_result_from_json(str(row["result_json"])),
            prepared=prepared,
            final_plan=final_plan,
            attempts=int(row["attempts"]),
        )

    def claim_ready(self, *, now_ms: int | None = None) -> OfficialWorkItem | None:
        now = int(time.time() * 1000) if now_ms is None else now_ms
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM official_processing_batches
                WHERE retry_at_ms <= ? AND (
                    state IN ('prepared','finalizing')
                    OR (state='pending' AND quiet_until_ms <= ?)
                )
                ORDER BY CASE state
                    WHEN 'finalizing' THEN 0 WHEN 'prepared' THEN 1 ELSE 2 END,
                    created_at_ms
                LIMIT 1
                """,
                (now, now),
            ).fetchone()
            if row is None:
                return None
            previous = str(row["state"])
            next_state = {"pending": "preparing", "prepared": "sending"}.get(previous, previous)
            conn.execute(
                """
                UPDATE official_processing_batches
                SET state=?, attempts=attempts+1, updated_at_ms=?
                WHERE batch_id=? AND state=?
                """,
                (next_state, now, str(row["batch_id"]), previous),
            )
            claimed = conn.execute(
                "SELECT * FROM official_processing_batches WHERE batch_id=?",
                (str(row["batch_id"]),),
            ).fetchone()
        if claimed is None:
            raise OfficialProcessingError("claimed official work disappeared")
        return self._row_to_item(claimed)

    def mark_prepared(
        self, batch_id: str, prepared: PreparedReply, *, now_ms: int | None = None
    ) -> None:
        if not prepared.requires_delivery or prepared.text is None:
            raise OfficialProcessingError("only sendable replies enter prepared state")
        now = int(time.time() * 1000) if now_ms is None else now_ms
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE official_processing_batches
                SET state='prepared', prepared_decision=?, prepared_text=?, reservation_id=?,
                    retry_at_ms=0, last_error_code=NULL, updated_at_ms=?
                WHERE batch_id=? AND state='preparing'
                """,
                (
                    prepared.decision.value,
                    prepared.text,
                    prepared.reservation_id,
                    now,
                    batch_id,
                ),
            )
        if cursor.rowcount != 1:
            raise OfficialProcessingError("official preparation state conflict")

    def mark_finalizing(self, batch_id: str, plan: ReplyPlan, *, now_ms: int | None = None) -> None:
        now = int(time.time() * 1000) if now_ms is None else now_ms
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE official_processing_batches
                SET state='finalizing', final_decision=?, final_text=?, retry_at_ms=0,
                    last_error_code=NULL, updated_at_ms=?
                WHERE batch_id=? AND state IN ('preparing','sending')
                """,
                (plan.decision.value, plan.text, now, batch_id),
            )
        if cursor.rowcount != 1:
            raise OfficialProcessingError("official finalization state conflict")

    def mark_complete(self, batch_id: str, *, now_ms: int | None = None) -> None:
        now = int(time.time() * 1000) if now_ms is None else now_ms
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE official_processing_batches
                SET state='complete', retry_at_ms=0, last_error_code=NULL, updated_at_ms=?
                WHERE batch_id=? AND state='finalizing'
                """,
                (now, batch_id),
            )
        if cursor.rowcount != 1:
            raise OfficialProcessingError("official completion state conflict")

    def mark_retry(
        self,
        item: OfficialWorkItem,
        *,
        error_code: str,
        now_ms: int | None = None,
    ) -> None:
        now = int(time.time() * 1000) if now_ms is None else now_ms
        safe_code = "_".join(error_code.strip().split())[:80] or "processing_error"
        retry_state = {"preparing": "pending", "sending": "prepared"}.get(item.state, item.state)
        delay_ms = min(30_000, 500 * (2 ** min(item.attempts, 6)))
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE official_processing_batches
                SET state=?, retry_at_ms=?, last_error_code=?, updated_at_ms=?
                WHERE batch_id=? AND state=?
                """,
                (retry_state, now + delay_ms, safe_code, now, item.batch_id, item.state),
            )

    def state_counts(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT state, COUNT(*) AS count FROM official_processing_batches GROUP BY state"
            ).fetchall()
        return {str(row["state"]): int(row["count"]) for row in rows}

    def purge_completed(self, *, before_ms: int) -> int:
        if not isinstance(before_ms, int) or isinstance(before_ms, bool) or before_ms < 0:
            raise OfficialProcessingError("before_ms must be a non-negative integer")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            batch_ids = tuple(
                str(row[0])
                for row in conn.execute(
                    """
                    SELECT batch_id FROM official_processing_batches
                    WHERE state='complete' AND updated_at_ms < ?
                    """,
                    (before_ms,),
                ).fetchall()
            )
            for batch_id in batch_ids:
                conn.execute(
                    "DELETE FROM official_processing_events WHERE batch_id=?",
                    (batch_id,),
                )
                conn.execute(
                    "DELETE FROM official_processing_batches WHERE batch_id=?",
                    (batch_id,),
                )
        return len(batch_ids)


PrepareCallback = Callable[[InboundEvent, IngestResult], Awaitable[PreparedReply]]
DeliverCallback = Callable[[InboundEvent, PreparedReply], Awaitable[ReplyPlan]]
FinalizeCallback = Callable[[InboundEvent, ReplyPlan], Awaitable[None]]


class OfficialDurableProcessor:
    """Single-worker state machine; failures remain durable and retry with backoff."""

    def __init__(
        self,
        *,
        store: OfficialProcessingStore,
        prepare: PrepareCallback,
        deliver: DeliverCallback,
        finalize: FinalizeCallback,
        poll_seconds: float = 0.2,
    ) -> None:
        self.store = store
        self.prepare = prepare
        self.deliver = deliver
        self.finalize = finalize
        self.poll_seconds = poll_seconds

    async def process_one(self) -> bool:
        try:
            item = await asyncio.to_thread(self.store.claim_ready)
        except Exception as exc:
            _log.error("official_processing_claim_failed type=%s", type(exc).__name__)
            return False
        if item is None:
            return False
        try:
            if item.state == "preparing":
                prepared = await self.prepare(item.event, item.result)
                if prepared.requires_delivery:
                    await asyncio.to_thread(self.store.mark_prepared, item.batch_id, prepared)
                else:
                    await asyncio.to_thread(
                        self.store.mark_finalizing,
                        item.batch_id,
                        ReplyPlan(prepared.decision, prepared.text),
                    )
            elif item.state == "sending":
                if item.prepared is None:
                    raise OfficialProcessingError("sending work has no prepared reply")
                plan = await self.deliver(item.event, item.prepared)
                await asyncio.to_thread(self.store.mark_finalizing, item.batch_id, plan)
            elif item.state == "finalizing":
                if item.final_plan is None:
                    raise OfficialProcessingError("finalizing work has no reply plan")
                await self.finalize(item.event, item.final_plan)
                await asyncio.to_thread(self.store.mark_complete, item.batch_id)
            else:
                raise OfficialProcessingError("claimed unsupported official state")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.error("official_processing_failed type=%s", type(exc).__name__)
            await asyncio.to_thread(
                self.store.mark_retry,
                item,
                error_code=type(exc).__name__,
            )
        return True

    async def run(self) -> None:
        while True:
            processed = await self.process_one()
            if not processed:
                await asyncio.sleep(self.poll_seconds)
