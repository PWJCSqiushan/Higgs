"""Auditable, scope-isolated memory primitives for Phase 3.

Chat messages never become active memory through this module alone. Callers may
propose candidates, while deterministic owner authorization controls every
state transition and physical deletion.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from r_agent.identity import Principal


class MemoryError(RuntimeError):
    """Base error for memory operations."""


class MemoryNotFoundError(MemoryError):
    """The requested memory item does not exist."""


class MemoryPermissionError(MemoryError):
    """The actor is not authorized to govern memory."""


class MemoryTransitionError(MemoryError):
    """A requested state transition is not valid."""


class MemoryValidationError(MemoryError):
    """A candidate is structurally unsafe or incomplete."""


class MemoryScope(StrEnum):
    PRINCIPAL = "principal"
    GROUP = "group"
    PERSONA = "persona"
    GLOBAL = "global"


class MemoryKind(StrEnum):
    USER_FACT = "user_fact"
    PREFERENCE = "preference"
    RELATIONSHIP = "relationship"
    COMMITMENT = "commitment"
    EPISODE_SUMMARY = "episode_summary"
    GROUP_NORM = "group_norm"


class MemoryRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MemoryStatus(StrEnum):
    CANDIDATE = "candidate"
    QUARANTINED = "quarantined"
    ACTIVE = "active"
    INVALIDATED = "invalidated"


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    item_id: str
    scope: MemoryScope
    scope_id: str
    kind: MemoryKind
    text: str
    source_channel: str
    source_account_id: str
    source_message_id: str
    source_principal_id: str
    created_by: str
    risk: MemoryRisk
    confidence: float
    status: MemoryStatus
    created_at_ms: int
    reviewed_at_ms: int | None
    reviewed_by: str | None
    invalidated_reason: str | None
    embedding_dim: int | None


@dataclass(frozen=True, slots=True)
class MemoryAuditRecord:
    audit_id: int
    item_id: str
    action: str
    actor_principal_id: str
    actor_role: str
    details_sha256: str
    created_at_ms: int


class MemoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                    item_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    scope_type TEXT NOT NULL
                        CHECK(scope_type IN ('principal','group','persona','global')),
                    scope_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN (
                        'user_fact','preference','relationship','commitment',
                        'episode_summary','group_norm'
                    )),
                    text TEXT NOT NULL,
                    source_channel TEXT NOT NULL,
                    source_account_id TEXT NOT NULL,
                    source_message_id TEXT NOT NULL,
                    source_principal_id TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    risk TEXT NOT NULL CHECK(risk IN ('low','medium','high')),
                    confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
                    status TEXT NOT NULL CHECK(status IN (
                        'candidate','quarantined','active','invalidated'
                    )),
                    created_at_ms INTEGER NOT NULL,
                    reviewed_at_ms INTEGER,
                    reviewed_by TEXT,
                    invalidated_reason TEXT,
                    embedding BLOB,
                    embedding_dim INTEGER
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_scope_status
                ON memory_items(scope_type, scope_id, status, created_at_ms DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_audit (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor_principal_id TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    details_sha256 TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL
                )
                """
            )

    @staticmethod
    def _require_owner(actor: Principal) -> None:
        if actor.role != "owner":
            raise MemoryPermissionError("memory governance requires owner role")

    @staticmethod
    def _clean_required(value: str, *, field: str, limit: int) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise MemoryValidationError(f"{field} is required")
        if len(cleaned) > limit:
            raise MemoryValidationError(f"{field} exceeds {limit} characters")
        return cleaned

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            item_id=str(row["item_id"]),
            scope=MemoryScope(row["scope_type"]),
            scope_id=str(row["scope_id"]),
            kind=MemoryKind(row["kind"]),
            text=str(row["text"]),
            source_channel=str(row["source_channel"]),
            source_account_id=str(row["source_account_id"]),
            source_message_id=str(row["source_message_id"]),
            source_principal_id=str(row["source_principal_id"]),
            created_by=str(row["created_by"]),
            risk=MemoryRisk(row["risk"]),
            confidence=float(row["confidence"]),
            status=MemoryStatus(row["status"]),
            created_at_ms=int(row["created_at_ms"]),
            reviewed_at_ms=(
                int(row["reviewed_at_ms"]) if row["reviewed_at_ms"] is not None else None
            ),
            reviewed_by=str(row["reviewed_by"]) if row["reviewed_by"] is not None else None,
            invalidated_reason=(
                str(row["invalidated_reason"]) if row["invalidated_reason"] is not None else None
            ),
            embedding_dim=(int(row["embedding_dim"]) if row["embedding_dim"] is not None else None),
        )

    @staticmethod
    def _audit(
        conn: sqlite3.Connection,
        *,
        item_id: str,
        action: str,
        actor_principal_id: str,
        actor_role: str,
        details: str,
        now_ms: int,
    ) -> None:
        digest = hashlib.sha256(details.encode("utf-8")).hexdigest()
        conn.execute(
            """
            INSERT INTO memory_audit(
                item_id, action, actor_principal_id, actor_role,
                details_sha256, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (item_id, action, actor_principal_id, actor_role, digest, now_ms),
        )

    def propose(
        self,
        *,
        scope: MemoryScope,
        scope_id: str,
        kind: MemoryKind,
        text: str,
        source_channel: str,
        source_account_id: str,
        source_message_id: str,
        source_principal_id: str,
        created_by: str,
        risk: MemoryRisk = MemoryRisk.LOW,
        confidence: float = 0.5,
        now_ms: int | None = None,
    ) -> MemoryRecord:
        if not isinstance(scope, MemoryScope):
            raise MemoryValidationError("scope must be a MemoryScope")
        if not isinstance(kind, MemoryKind):
            raise MemoryValidationError("kind must be a MemoryKind")
        if not isinstance(risk, MemoryRisk):
            raise MemoryValidationError("risk must be a MemoryRisk")
        if not 0 <= confidence <= 1:
            raise MemoryValidationError("confidence must be between 0 and 1")

        clean_scope_id = self._clean_required(scope_id, field="scope_id", limit=256)
        if scope is MemoryScope.GLOBAL and clean_scope_id != "*":
            raise MemoryValidationError("global scope_id must be '*'")
        clean_text = self._clean_required(text, field="text", limit=4000)
        clean_source_channel = self._clean_required(
            source_channel, field="source_channel", limit=32
        )
        clean_source_account = self._clean_required(
            source_account_id, field="source_account_id", limit=64
        )
        clean_source_message = self._clean_required(
            source_message_id, field="source_message_id", limit=128
        )
        clean_source_principal = self._clean_required(
            source_principal_id, field="source_principal_id", limit=128
        )
        clean_created_by = self._clean_required(created_by, field="created_by", limit=128)
        timestamp = int(time.time() * 1000) if now_ms is None else now_ms
        initial_status = (
            MemoryStatus.QUARANTINED if risk is MemoryRisk.HIGH else MemoryStatus.CANDIDATE
        )
        fingerprint_payload = json.dumps(
            {
                "scope": scope.value,
                "scope_id": clean_scope_id,
                "kind": kind.value,
                "text": clean_text,
                "source_channel": clean_source_channel,
                "source_account_id": clean_source_account,
                "source_message_id": clean_source_message,
                "source_principal_id": clean_source_principal,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        fingerprint = hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest()
        item_id = str(uuid.uuid4())

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO memory_items(
                    item_id, fingerprint, scope_type, scope_id, kind, text,
                    source_channel, source_account_id, source_message_id,
                    source_principal_id, created_by, risk, confidence,
                    status, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    fingerprint,
                    scope.value,
                    clean_scope_id,
                    kind.value,
                    clean_text,
                    clean_source_channel,
                    clean_source_account,
                    clean_source_message,
                    clean_source_principal,
                    clean_created_by,
                    risk.value,
                    confidence,
                    initial_status.value,
                    timestamp,
                ),
            )
            if cursor.rowcount == 1:
                self._audit(
                    conn,
                    item_id=item_id,
                    action="proposed",
                    actor_principal_id=clean_created_by,
                    actor_role="extractor",
                    details=f"{initial_status.value}:{risk.value}",
                    now_ms=timestamp,
                )
            row = conn.execute(
                "SELECT * FROM memory_items WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
        if row is None:
            raise MemoryError("memory proposal could not be persisted")
        return self._row_to_record(row)

    def get(self, item_id: str) -> MemoryRecord:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_items WHERE item_id = ?",
                (item_id,),
            ).fetchone()
        if row is None:
            raise MemoryNotFoundError("memory item not found")
        return self._row_to_record(row)

    def get_for_review(self, item_id: str, *, actor: Principal) -> MemoryRecord:
        """Return one complete record to an authenticated memory governor."""
        self._require_owner(actor)
        return self.get(item_id)

    def list_items(
        self,
        *,
        actor: Principal,
        status: MemoryStatus | None = None,
        scope: MemoryScope | None = None,
        scope_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        """List review records without allowing chat-controlled authorization."""
        self._require_owner(actor)
        if status is not None and not isinstance(status, MemoryStatus):
            raise MemoryValidationError("status must be a MemoryStatus")
        if scope is not None and not isinstance(scope, MemoryScope):
            raise MemoryValidationError("scope must be a MemoryScope")
        if scope_id is not None and scope is None:
            raise MemoryValidationError("scope_id requires scope")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise MemoryValidationError("limit must be between 1 and 200")

        clauses: list[str] = []
        params: list[str | int] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if scope is not None:
            clauses.append("scope_type = ?")
            params.append(scope.value)
        if scope_id is not None:
            clauses.append("scope_id = ?")
            params.append(self._clean_required(scope_id, field="scope_id", limit=256))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM memory_items
                {where}
                ORDER BY created_at_ms DESC, item_id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def audit_log(
        self,
        item_id: str,
        *,
        actor: Principal,
        limit: int = 100,
    ) -> list[MemoryAuditRecord]:
        """Return content-free governance history, including after hard deletion."""
        self._require_owner(actor)
        clean_item_id = self._clean_required(item_id, field="item_id", limit=128)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
            raise MemoryValidationError("limit must be between 1 and 500")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT audit_id, item_id, action, actor_principal_id, actor_role,
                       details_sha256, created_at_ms
                FROM memory_audit
                WHERE item_id = ?
                ORDER BY audit_id ASC
                LIMIT ?
                """,
                (clean_item_id, limit),
            ).fetchall()
        return [
            MemoryAuditRecord(
                audit_id=int(row["audit_id"]),
                item_id=str(row["item_id"]),
                action=str(row["action"]),
                actor_principal_id=str(row["actor_principal_id"]),
                actor_role=str(row["actor_role"]),
                details_sha256=str(row["details_sha256"]),
                created_at_ms=int(row["created_at_ms"]),
            )
            for row in rows
        ]

    def _transition(
        self,
        item_id: str,
        *,
        actor: Principal,
        target: MemoryStatus,
        allowed_from: frozenset[MemoryStatus],
        reason: str,
        now_ms: int | None = None,
    ) -> MemoryRecord:
        self._require_owner(actor)
        timestamp = int(time.time() * 1000) if now_ms is None else now_ms
        clean_reason = self._clean_required(reason, field="reason", limit=500)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_items WHERE item_id = ?",
                (item_id,),
            ).fetchone()
            if row is None:
                raise MemoryNotFoundError("memory item not found")
            current = MemoryStatus(row["status"])
            if current not in allowed_from:
                raise MemoryTransitionError(
                    f"cannot transition memory from {current.value} to {target.value}"
                )
            invalidated_reason = clean_reason if target is MemoryStatus.INVALIDATED else None
            cursor = conn.execute(
                """
                UPDATE memory_items
                SET status = ?, reviewed_at_ms = ?, reviewed_by = ?,
                    invalidated_reason = ?
                WHERE item_id = ? AND status = ?
                """,
                (
                    target.value,
                    timestamp,
                    actor.principal_id,
                    invalidated_reason,
                    item_id,
                    current.value,
                ),
            )
            if cursor.rowcount != 1:
                raise MemoryTransitionError("memory changed during review; retry from fresh state")
            self._audit(
                conn,
                item_id=item_id,
                action=target.value,
                actor_principal_id=actor.principal_id,
                actor_role=actor.role,
                details=clean_reason,
                now_ms=timestamp,
            )
            updated = conn.execute(
                "SELECT * FROM memory_items WHERE item_id = ?",
                (item_id,),
            ).fetchone()
        if updated is None:
            raise MemoryError("memory transition could not be read back")
        return self._row_to_record(updated)

    def activate(self, item_id: str, *, actor: Principal, reason: str) -> MemoryRecord:
        return self._transition(
            item_id,
            actor=actor,
            target=MemoryStatus.ACTIVE,
            allowed_from=frozenset({MemoryStatus.CANDIDATE, MemoryStatus.QUARANTINED}),
            reason=reason,
        )

    def quarantine(self, item_id: str, *, actor: Principal, reason: str) -> MemoryRecord:
        return self._transition(
            item_id,
            actor=actor,
            target=MemoryStatus.QUARANTINED,
            allowed_from=frozenset({MemoryStatus.CANDIDATE, MemoryStatus.ACTIVE}),
            reason=reason,
        )

    def invalidate(self, item_id: str, *, actor: Principal, reason: str) -> MemoryRecord:
        return self._transition(
            item_id,
            actor=actor,
            target=MemoryStatus.INVALIDATED,
            allowed_from=frozenset(
                {MemoryStatus.CANDIDATE, MemoryStatus.QUARANTINED, MemoryStatus.ACTIVE}
            ),
            reason=reason,
        )

    def restore(self, item_id: str, *, actor: Principal, reason: str) -> MemoryRecord:
        record = self.get(item_id)
        target = MemoryStatus.QUARANTINED if record.risk is MemoryRisk.HIGH else MemoryStatus.ACTIVE
        return self._transition(
            item_id,
            actor=actor,
            target=target,
            allowed_from=frozenset({MemoryStatus.INVALIDATED}),
            reason=reason,
        )

    def hard_delete(self, item_id: str, *, actor: Principal, reason: str) -> None:
        self._require_owner(actor)
        clean_reason = self._clean_required(reason, field="reason", limit=500)
        timestamp = int(time.time() * 1000)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT text FROM memory_items WHERE item_id = ?",
                (item_id,),
            ).fetchone()
            if row is None:
                raise MemoryNotFoundError("memory item not found")
            content_digest = hashlib.sha256(str(row["text"]).encode("utf-8")).hexdigest()
            self._audit(
                conn,
                item_id=item_id,
                action="hard_deleted",
                actor_principal_id=actor.principal_id,
                actor_role=actor.role,
                details=f"{clean_reason}:{content_digest}",
                now_ms=timestamp,
            )
            conn.execute("DELETE FROM memory_items WHERE item_id = ?", (item_id,))

    def search_active(
        self,
        *,
        scope: MemoryScope,
        scope_id: str,
        query: str,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        if not isinstance(scope, MemoryScope):
            raise MemoryValidationError("scope must be a MemoryScope")
        clean_scope_id = self._clean_required(scope_id, field="scope_id", limit=256)
        clean_query = self._clean_required(query, field="query", limit=500)
        bounded_limit = max(1, min(limit, 50))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_items
                WHERE scope_type = ? AND scope_id = ? AND status = 'active'
                  AND instr(lower(text), lower(?)) > 0
                ORDER BY confidence DESC, created_at_ms DESC
                LIMIT ?
                """,
                (scope.value, clean_scope_id, clean_query, bounded_limit),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_active_for_scope(
        self,
        *,
        scope: MemoryScope,
        scope_id: str,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        """Return only owner-approved memory from one exact scope."""
        if not isinstance(scope, MemoryScope):
            raise MemoryValidationError("scope must be a MemoryScope")
        clean_scope_id = self._clean_required(scope_id, field="scope_id", limit=256)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise MemoryValidationError("limit must be between 1 and 20")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_items
                WHERE scope_type = ? AND scope_id = ? AND status = 'active'
                ORDER BY confidence DESC, created_at_ms DESC, item_id ASC
                LIMIT ?
                """,
                (scope.value, clean_scope_id, limit),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def audit_count(self, item_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM memory_audit WHERE item_id = ?",
                (item_id,),
            ).fetchone()
        return int(row[0]) if row is not None else 0

    # Compatibility facade: vector storage is implemented in a separate module
    # so the core memory state machine remains easy to audit.
    def set_embedding(
        self,
        item_id: str,
        embedding: tuple[float, ...] | list[float],
    ) -> MemoryRecord:
        from r_agent.vector_memory import MemoryVectorStore

        return MemoryVectorStore(self.path, memory=self).set(item_id, embedding)

    def search_active_by_vector(
        self,
        *,
        scope: MemoryScope,
        scope_id: str,
        query_embedding: tuple[float, ...] | list[float],
        limit: int = 10,
    ) -> list[MemoryRecord]:
        from r_agent.vector_memory import MemoryVectorStore

        return MemoryVectorStore(self.path, memory=self).search_active(
            scope=scope,
            scope_id=scope_id,
            query_embedding=query_embedding,
            limit=limit,
        )

    def vector_status(self) -> dict[str, int]:
        from r_agent.vector_memory import MemoryVectorStore

        return MemoryVectorStore(self.path, memory=self).status()
