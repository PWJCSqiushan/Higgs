"""Content-minimized audit ledger for memory injection decisions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from r_agent.identity import Principal
from r_agent.memory import MemoryRecord, MemoryScope, MemoryStatus


class RecallError(RuntimeError):
    """Base error for recall ledger operations."""


class RecallPermissionError(RecallError):
    """The actor is not authorized to inspect recall history."""


class RecallValidationError(RecallError):
    """The proposed recall would violate a safety invariant."""


class RecallConflictError(RecallError):
    """A turn ID was reused for a different recall decision."""


class RecallNotFoundError(RecallError):
    """No recall entry exists for the requested turn."""


@dataclass(frozen=True, slots=True)
class RecallEntry:
    recall_id: str
    turn_id: str
    conversation_key: str
    requesting_principal_id: str
    query_sha256: str
    memory_item_ids: tuple[str, ...]
    memory_scope_keys: tuple[str, ...]
    policy_version: str
    created_at_ms: int


class RecallLedger:
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
                CREATE TABLE IF NOT EXISTS recall_ledger (
                    recall_id TEXT PRIMARY KEY,
                    turn_id TEXT NOT NULL UNIQUE,
                    conversation_key TEXT NOT NULL,
                    requesting_principal_id TEXT NOT NULL,
                    query_sha256 TEXT NOT NULL,
                    memory_item_ids_json TEXT NOT NULL,
                    memory_scope_keys_json TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_recall_created
                ON recall_ledger(created_at_ms DESC)
                """
            )

    @staticmethod
    def _clean(value: str, *, field: str, limit: int) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise RecallValidationError(f"{field} is required")
        if len(cleaned) > limit:
            raise RecallValidationError(f"{field} exceeds {limit} characters")
        return cleaned

    @staticmethod
    def _require_owner(actor: Principal) -> None:
        if actor.role != "owner":
            raise RecallPermissionError("recall audit requires owner role")

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> RecallEntry:
        return RecallEntry(
            recall_id=str(row["recall_id"]),
            turn_id=str(row["turn_id"]),
            conversation_key=str(row["conversation_key"]),
            requesting_principal_id=str(row["requesting_principal_id"]),
            query_sha256=str(row["query_sha256"]),
            memory_item_ids=tuple(json.loads(row["memory_item_ids_json"])),
            memory_scope_keys=tuple(json.loads(row["memory_scope_keys_json"])),
            policy_version=str(row["policy_version"]),
            created_at_ms=int(row["created_at_ms"]),
        )

    def record(
        self,
        *,
        turn_id: str,
        conversation_key: str,
        requesting_principal_id: str,
        query: str,
        memories: list[MemoryRecord],
        allowed_scopes: frozenset[tuple[MemoryScope, str]],
        policy_version: str,
        now_ms: int | None = None,
    ) -> RecallEntry:
        clean_turn = self._clean(turn_id, field="turn_id", limit=128)
        clean_conversation = self._clean(conversation_key, field="conversation_key", limit=256)
        clean_requester = self._clean(
            requesting_principal_id,
            field="requesting_principal_id",
            limit=128,
        )
        clean_query = self._clean(query, field="query", limit=1000)
        clean_policy = self._clean(policy_version, field="policy_version", limit=64)
        if len(memories) > 50:
            raise RecallValidationError("at most 50 memories may be injected")
        if any(
            not isinstance(scope, MemoryScope) or not scope_id.strip()
            for scope, scope_id in allowed_scopes
        ):
            raise RecallValidationError("allowed_scopes contains an invalid scope")

        item_ids: list[str] = []
        scope_keys: list[str] = []
        seen: set[str] = set()
        for memory in memories:
            if memory.status is not MemoryStatus.ACTIVE:
                raise RecallValidationError("only active memories may be injected")
            scope_key = (memory.scope, memory.scope_id)
            if scope_key not in allowed_scopes:
                raise RecallValidationError("memory is outside the allowed recall scopes")
            if memory.item_id in seen:
                raise RecallValidationError("duplicate memory item in recall decision")
            seen.add(memory.item_id)
            item_ids.append(memory.item_id)
            scope_keys.append(f"{memory.scope.value}:{memory.scope_id}")

        query_sha256 = hashlib.sha256(clean_query.encode("utf-8")).hexdigest()
        item_ids_json = json.dumps(item_ids, ensure_ascii=True, separators=(",", ":"))
        scope_keys_json = json.dumps(scope_keys, ensure_ascii=False, separators=(",", ":"))
        timestamp = int(time.time() * 1000) if now_ms is None else now_ms
        recall_id = str(uuid.uuid4())
        expected = (
            clean_conversation,
            clean_requester,
            query_sha256,
            item_ids_json,
            scope_keys_json,
            clean_policy,
        )

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO recall_ledger(
                    recall_id, turn_id, conversation_key, requesting_principal_id,
                    query_sha256, memory_item_ids_json, memory_scope_keys_json,
                    policy_version, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (recall_id, clean_turn, *expected, timestamp),
            )
            row = conn.execute(
                "SELECT * FROM recall_ledger WHERE turn_id = ?",
                (clean_turn,),
            ).fetchone()
        if row is None:
            raise RecallError("recall entry could not be persisted")
        actual = (
            str(row["conversation_key"]),
            str(row["requesting_principal_id"]),
            str(row["query_sha256"]),
            str(row["memory_item_ids_json"]),
            str(row["memory_scope_keys_json"]),
            str(row["policy_version"]),
        )
        if actual != expected:
            raise RecallConflictError("turn_id already has a different recall decision")
        return self._row_to_entry(row)

    def get_for_owner(self, turn_id: str, *, actor: Principal) -> RecallEntry:
        self._require_owner(actor)
        clean_turn = self._clean(turn_id, field="turn_id", limit=128)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM recall_ledger WHERE turn_id = ?",
                (clean_turn,),
            ).fetchone()
        if row is None:
            raise RecallNotFoundError("recall entry not found")
        return self._row_to_entry(row)

    def list_recent(self, *, actor: Principal, limit: int = 50) -> list[RecallEntry]:
        self._require_owner(actor)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise RecallValidationError("limit must be between 1 and 200")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM recall_ledger
                ORDER BY created_at_ms DESC, recall_id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]
