# ruff: noqa: E501, RUF001
"""Observation queue, safe background reconciliation, and historical backfill.

The hot path only appends observations. Extraction is deterministic and bounded;
model-generated chat can never change identity, persona, permissions, or memory state.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from r_agent.embedding import EmbeddingClient, EmbeddingError
from r_agent.events import ConversationKind, InboundEvent
from r_agent.memory import (
    MemoryKind,
    MemoryRisk,
    MemoryScope,
    MemoryStore,
    is_auto_review_safe_text,
)
from r_agent.vector_memory import MemoryVectorStore

_PREFERENCE_PATTERNS = (
    re.compile(r"^我(?:很|比较|最|一直)?(?:喜欢|偏好|爱好)\s*(.{1,120})[。！!？?]?$"),
    re.compile(r"^我(?:不喜欢|讨厌)\s*(.{1,120})[。！!？?]?$"),
)
_COMMITMENT_PATTERN = re.compile(r"^我(?:打算|计划|准备|要)\s*(.{2,160})[。！!？?]?$")
_INJECTION_MARKERS = (
    "忽略之前",
    "忽略系统",
    "系统提示",
    "提示词",
    "修改权限",
    "你必须听我的",
    "叫我主人",
    "我是主人",
    "管理员权限",
)
_SENSITIVE_MARKERS = (
    "地址",
    "住在",
    "电话",
    "手机",
    "微信",
    "邮箱",
    "账号",
    "密码",
    "token",
    "密钥",
    "身份证",
    "银行卡",
    "病史",
    "诊断",
    "收入",
    "政治",
    "宗教",
)


@dataclass(frozen=True, slots=True)
class Observation:
    observation_id: str
    principal_id: str
    principal_role: str
    channel: str
    account_id: str
    message_id: str
    conversation_kind: str
    conversation_id: str
    text: str
    occurred_at_ms: int


@dataclass(frozen=True, slots=True)
class ReconcileSummary:
    processed: int
    candidates: int
    quarantined: int
    excluded: int
    embedded: int
    activated: int
    failed: int = 0


class MemoryObservationStore:
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
                CREATE TABLE IF NOT EXISTS memory_observations (
                    observation_id TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    principal_role TEXT NOT NULL CHECK(principal_role IN ('owner','user','blocked')),
                    channel TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    conversation_kind TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    occurred_at_ms INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','processed','excluded','failed')),
                    exclude_reason TEXT,
                    memory_item_id TEXT,
                    processed_at_ms INTEGER,
                    error_type TEXT,
                    error_sha256 TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(channel, account_id, message_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_observations_status_time
                ON memory_observations(status, occurred_at_ms)
                """
            )
            columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(memory_observations)")
            }
            for name, definition in (
                ("error_type", "TEXT"),
                ("error_sha256", "TEXT"),
                ("retry_count", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if name not in columns:
                    conn.execute(f"ALTER TABLE memory_observations ADD COLUMN {name} {definition}")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_reconcile_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at_ms INTEGER NOT NULL,
                    finished_at_ms INTEGER NOT NULL,
                    processed INTEGER NOT NULL,
                    candidates INTEGER NOT NULL,
                    quarantined INTEGER NOT NULL,
                    excluded INTEGER NOT NULL,
                    embedded INTEGER NOT NULL,
                    activated INTEGER NOT NULL,
                    failed INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            run_columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(memory_reconcile_runs)")
            }
            if "failed" not in run_columns:
                conn.execute(
                    "ALTER TABLE memory_reconcile_runs ADD COLUMN failed INTEGER NOT NULL DEFAULT 0"
                )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_notification_state (
                    key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                )
                """
            )

    @staticmethod
    def _observation_id(event: InboundEvent) -> str:
        raw = ":".join(event.source_key).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:32]

    def enqueue(self, event: InboundEvent, *, principal_id: str, principal_role: str) -> bool:
        clean = " ".join(event.text.split())[:4000]
        if not clean:
            return False
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO memory_observations(
                    observation_id, principal_id, principal_role, channel, account_id,
                    message_id, conversation_kind, conversation_id, text,
                    occurred_at_ms, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    self._observation_id(event),
                    principal_id,
                    principal_role,
                    event.channel,
                    event.account_id,
                    event.message_id,
                    event.conversation_kind.value,
                    event.conversation_id,
                    clean,
                    event.occurred_at_ms,
                ),
            )
        return cursor.rowcount == 1

    def pending(self, *, limit: int = 50) -> list[Observation]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_observations
                WHERE status = 'pending'
                ORDER BY occurred_at_ms, observation_id LIMIT ?
                """,
                (max(1, min(limit, 50)),),
            ).fetchall()
        return [
            Observation(
                str(row["observation_id"]),
                str(row["principal_id"]),
                str(row["principal_role"]),
                str(row["channel"]),
                str(row["account_id"]),
                str(row["message_id"]),
                str(row["conversation_kind"]),
                str(row["conversation_id"]),
                str(row["text"]),
                int(row["occurred_at_ms"]),
            )
            for row in rows
        ]

    def finish(
        self,
        observation_id: str,
        *,
        status: str,
        reason: str | None = None,
        memory_item_id: str | None = None,
        now_ms: int | None = None,
    ) -> None:
        if status not in {"processed", "excluded", "failed"}:
            raise ValueError("invalid observation terminal status")
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE memory_observations
                SET status=?, exclude_reason=?, memory_item_id=?, processed_at_ms=?
                WHERE observation_id=? AND status='pending'
                """,
                (
                    status,
                    reason[:120] if reason else None,
                    memory_item_id,
                    int(time.time() * 1000) if now_ms is None else now_ms,
                    observation_id,
                ),
            )

    def fail(self, observation_id: str, *, error: Exception, now_ms: int | None = None) -> None:
        """Fail one observation without retaining exception text or message content."""
        error_type = type(error).__name__[:80]
        error_sha256 = hashlib.sha256(str(error).encode("utf-8")).hexdigest()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE memory_observations
                SET status='failed', error_type=?, error_sha256=?, processed_at_ms=?
                WHERE observation_id=? AND status='pending'
                """,
                (
                    error_type,
                    error_sha256,
                    int(time.time() * 1000) if now_ms is None else now_ms,
                    observation_id,
                ),
            )

    def list_failed(self, *, limit: int = 20) -> list[dict[str, object]]:
        """Return content-free failed-observation metadata for owner operations."""
        bounded = max(1, min(limit, 200))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT observation_id, error_type, error_sha256, retry_count,
                       occurred_at_ms, processed_at_ms
                FROM memory_observations WHERE status='failed'
                ORDER BY processed_at_ms DESC, observation_id LIMIT ?
                """,
                (bounded,),
            ).fetchall()
        return [dict(row) for row in rows]

    def retry_failed(self, observation_id: str) -> bool:
        clean = observation_id.strip()
        if len(clean) < 8:
            raise ValueError("observation id must contain at least 8 characters")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT observation_id FROM memory_observations WHERE status='failed' AND observation_id LIKE ? LIMIT 2",
                (f"{clean}%",),
            ).fetchall()
            if len(rows) != 1:
                return False
            cursor = conn.execute(
                """
                UPDATE memory_observations SET status='pending', error_type=NULL,
                    error_sha256=NULL, processed_at_ms=NULL, retry_count=retry_count+1
                WHERE observation_id=? AND status='failed'
                """,
                (str(rows[0]["observation_id"]),),
            )
        return cursor.rowcount == 1

    def source_quality(self) -> list[dict[str, object]]:
        """Return anonymous source quality counts without message text."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT principal_id, status, COUNT(*) AS n
                FROM memory_observations GROUP BY principal_id, status
                """
            ).fetchall()
        return [
            {
                "source": hashlib.sha256(str(row["principal_id"]).encode()).hexdigest()[:8],
                "status": str(row["status"]),
                "count": int(row["n"]),
            }
            for row in rows
        ]

    def candidate_notification_due(self, total_candidates: int, *, threshold: int = 8) -> bool:
        """Return whether another content-free owner review reminder is due."""
        if threshold < 1 or total_candidates < threshold:
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM memory_notification_state WHERE key='candidate_notified'"
            ).fetchone()
        last_notified = int(row[0]) if row is not None else 0
        return total_candidates // threshold > last_notified // threshold

    def mark_candidate_notified(self, total_candidates: int, *, now_ms: int | None = None) -> None:
        if total_candidates < 0:
            raise ValueError("candidate count cannot be negative")
        now = int(time.time() * 1000) if now_ms is None else now_ms
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_notification_state(key, value, updated_at_ms)
                VALUES ('candidate_notified', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=MAX(value, excluded.value), updated_at_ms=excluded.updated_at_ms
                """,
                (total_candidates, now),
            )

    def stats(self) -> dict[str, int | None]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM memory_observations GROUP BY status"
            ).fetchall()
            last = conn.execute("SELECT MAX(finished_at_ms) FROM memory_reconcile_runs").fetchone()[
                0
            ]
        result = {"pending": 0, "processed": 0, "excluded": 0, "failed": 0}
        result.update({str(row["status"]): int(row["n"]) for row in rows})
        result["last_reconcile_ms"] = int(last) if last is not None else None
        return result

    def record_run(self, summary: ReconcileSummary, *, started_at_ms: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_reconcile_runs(
                    started_at_ms, finished_at_ms, processed, candidates,
                    quarantined, excluded, embedded, activated, failed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    started_at_ms,
                    int(time.time() * 1000),
                    summary.processed,
                    summary.candidates,
                    summary.quarantined,
                    summary.excluded,
                    summary.embedded,
                    summary.activated,
                    summary.failed,
                ),
            )

    def purge_raw(self, *, retention_days: int = 30, now_ms: int | None = None) -> int:
        now = int(time.time() * 1000) if now_ms is None else now_ms
        cutoff = now - retention_days * 86_400_000
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM memory_observations WHERE occurred_at_ms < ? AND status <> 'pending'",
                (cutoff,),
            )
        return int(cursor.rowcount)


def _extract(observation: Observation) -> tuple[MemoryKind, str, MemoryRisk, float] | None:
    text = observation.text.strip()
    lowered = text.casefold()
    if any(marker in lowered for marker in _INJECTION_MARKERS):
        return MemoryKind.USER_FACT, text[:300], MemoryRisk.HIGH, 0.99
    sensitive = any(marker in lowered for marker in _SENSITIVE_MARKERS)
    for pattern in _PREFERENCE_PATTERNS:
        match = pattern.fullmatch(text)
        if match:
            value = " ".join(match.group(1).split())
            canonical = f"该用户表达过偏好：{value}"
            risk = MemoryRisk.HIGH if sensitive else MemoryRisk.LOW
            return MemoryKind.PREFERENCE, canonical, risk, 0.95
    match = _COMMITMENT_PATTERN.fullmatch(text)
    if match:
        value = " ".join(match.group(1).split())
        risk = MemoryRisk.HIGH if sensitive else MemoryRisk.MEDIUM
        return MemoryKind.COMMITMENT, f"该用户计划：{value}", risk, 0.90
    return None


class MemoryReconciler:
    def __init__(
        self,
        *,
        observations: MemoryObservationStore,
        memory: MemoryStore,
        vectors: MemoryVectorStore,
        embedding_client: EmbeddingClient | None,
        auto_review_enabled: Callable[[], bool],
        auto_review_confidence: Callable[[], float],
        auto_review_evidence: Callable[[], int],
    ) -> None:
        self.observations = observations
        self.memory = memory
        self.vectors = vectors
        self.embedding_client = embedding_client
        self.auto_review_enabled = auto_review_enabled
        self.auto_review_confidence = auto_review_confidence
        self.auto_review_evidence = auto_review_evidence

    async def _process_one(self, observation: Observation, counts: dict[str, int]) -> None:
        extracted = _extract(observation)
        if extracted is None:
            await asyncio.to_thread(
                self.observations.finish,
                observation.observation_id,
                status="excluded",
                reason="no_atomic_fact",
            )
            counts["excluded"] += 1
            return
        kind, text, risk, confidence = extracted
        record = await asyncio.to_thread(
            self.memory.propose,
            scope=MemoryScope.PRINCIPAL,
            scope_id=observation.principal_id,
            kind=kind,
            text=text,
            source_channel=observation.channel,
            source_account_id=observation.account_id,
            source_message_id=observation.message_id,
            source_principal_id=observation.principal_id,
            source_principal_role=observation.principal_role,
            created_by="memory-reconciler-v2",
            risk=risk,
            confidence=confidence,
            source_trust=1.0 if observation.principal_role == "owner" else 0.5,
            valid_from_ms=observation.occurred_at_ms,
            now_ms=observation.occurred_at_ms,
        )
        counts["quarantined" if risk is MemoryRisk.HIGH else "candidates"] += 1
        if self.embedding_client is not None:
            try:
                vector = await self.embedding_client.embed_one(record.text)
                await asyncio.to_thread(self.vectors.set, record.item_id, vector)
                counts["embedded"] += 1
            except EmbeddingError:
                pass
        if (
            observation.principal_role == "owner"
            and kind is MemoryKind.PREFERENCE
            and risk is MemoryRisk.LOW
            and confidence >= 0.90
            and self.auto_review_enabled()
            and is_auto_review_safe_text(text)
        ):
            outcome = await asyncio.to_thread(
                self.memory.auto_review_candidate,
                record.item_id,
                min_confidence=max(0.90, self.auto_review_confidence()),
                min_evidence=max(2, self.auto_review_evidence()),
            )
            if outcome.decision == "activated":
                counts["activated"] += 1
        await asyncio.to_thread(
            self.observations.finish,
            observation.observation_id,
            status="processed",
            memory_item_id=record.item_id,
        )

    async def reconcile_once(self, *, limit: int = 50) -> ReconcileSummary:
        started = int(time.time() * 1000)
        counts = {
            "processed": 0,
            "candidates": 0,
            "quarantined": 0,
            "excluded": 0,
            "embedded": 0,
            "activated": 0,
            "failed": 0,
        }
        pending = await asyncio.to_thread(self.observations.pending, limit=limit)
        for observation in pending:
            counts["processed"] += 1
            try:
                await self._process_one(observation, counts)
            except Exception as exc:
                counts["failed"] += 1
                await asyncio.to_thread(
                    self.observations.fail,
                    observation.observation_id,
                    error=exc,
                )
        summary = ReconcileSummary(**counts)
        await asyncio.to_thread(self.observations.record_run, summary, started_at_ms=started)
        return summary

    async def run_periodically(self, *, interval_seconds: float = 900.0) -> None:
        while True:
            try:
                await self.reconcile_once(limit=50)
                await asyncio.to_thread(self.observations.purge_raw, retention_days=30)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Store-wide faults are retried later; one bad row is isolated above.
                pass
            await asyncio.sleep(interval_seconds)


def backfill_preview(
    journal_path: Path, *, high_frequency_threshold: int = 200
) -> dict[str, object]:
    """Return content-free historical statistics; no memory or observation is written."""
    with sqlite3.connect(journal_path) as conn:
        conn.row_factory = sqlite3.Row
        total = int(conn.execute("SELECT COUNT(*) FROM inbound_events").fetchone()[0])
        rows = conn.execute(
            """
            SELECT principal_id, conversation_kind, COUNT(*) AS n
            FROM inbound_events GROUP BY principal_id, conversation_kind
            ORDER BY n DESC
            """
        ).fetchall()
    excluded = sum(int(row["n"]) for row in rows if int(row["n"]) > high_frequency_threshold)
    distribution = [
        {
            "source": hashlib.sha256(str(row["principal_id"]).encode()).hexdigest()[:8],
            "kind": str(row["conversation_kind"]),
            "count": int(row["n"]),
            "excluded": int(row["n"]) > high_frequency_threshold,
        }
        for row in rows
    ]
    return {
        "total_messages": total,
        "eligible_messages": total - excluded,
        "excluded_high_frequency": excluded,
        "sources": distribution,
        "mode": "preview_only",
    }


def backfill_candidates(
    journal_path: Path,
    observations: MemoryObservationStore,
    *,
    high_frequency_threshold: int = 200,
) -> dict[str, int | str]:
    """Queue eligible history as candidate-only observations.

    Historical owner messages are deliberately labelled as ordinary users here,
    so this operation can never trigger automatic activation.
    """
    if not 1 <= high_frequency_threshold <= 10_000:
        raise ValueError("high_frequency_threshold must be between 1 and 10000")
    with sqlite3.connect(journal_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            WITH source_counts AS (
                SELECT principal_id, conversation_kind, COUNT(*) AS n
                FROM inbound_events
                GROUP BY principal_id, conversation_kind
            )
            SELECT e.*
            FROM inbound_events AS e
            JOIN source_counts AS c
              ON c.principal_id=e.principal_id
             AND c.conversation_kind=e.conversation_kind
            WHERE c.n <= ?
            ORDER BY e.id
            """,
            (high_frequency_threshold,),
        ).fetchall()
        total = int(conn.execute("SELECT COUNT(*) FROM inbound_events").fetchone()[0])
    enqueued = 0
    already_present = 0
    for row in rows:
        event = InboundEvent(
            channel=str(row["channel"]),
            account_id=str(row["account_id"]),
            sender_id=str(row["principal_id"]),
            message_id=str(row["message_id"]),
            occurred_at_ms=int(row["occurred_at_ms"]),
            conversation_kind=ConversationKind(str(row["conversation_kind"])),
            conversation_id=str(row["conversation_id"]),
            group_id=str(row["group_id"]) if row["group_id"] is not None else None,
            text=str(row["text"]),
            mentioned=bool(row["mentioned"]),
        )
        inserted = observations.enqueue(
            event,
            principal_id=str(row["principal_id"]),
            principal_role="user",
        )
        enqueued += int(inserted)
        already_present += int(not inserted)
    return {
        "total_messages": total,
        "eligible_messages": len(rows),
        "excluded_high_frequency": total - len(rows),
        "enqueued": enqueued,
        "already_present": already_present,
        "mode": "candidate_only",
    }
