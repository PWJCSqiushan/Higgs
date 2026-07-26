"""SQLite-backed vector attachment and scoped cosine search for memory items."""

from __future__ import annotations

import math
import sqlite3
import struct
from pathlib import Path

from r_agent.memory import (
    MemoryNotFoundError,
    MemoryRecord,
    MemoryScope,
    MemoryStore,
    MemoryValidationError,
)


class MemoryVectorStore:
    """Operate only on the embedding columns owned by MemoryStore's schema."""

    def __init__(self, path: Path, *, memory: MemoryStore) -> None:
        if path.resolve() != memory.path.resolve():
            raise MemoryValidationError("vector store must share the memory database")
        self.path = path
        self.memory = memory

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _validate(values: tuple[float, ...] | list[float]) -> tuple[float, ...]:
        if not 2 <= len(values) <= 2048:
            raise MemoryValidationError("embedding dimension must be between 2 and 2048")
        vector: list[float] = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise MemoryValidationError("embedding must contain only numbers")
            number = float(value)
            if not math.isfinite(number):
                raise MemoryValidationError("embedding must contain finite numbers")
            vector.append(number)
        if not any(vector):
            raise MemoryValidationError("embedding must not be all zero")
        return tuple(vector)

    def set(self, item_id: str, embedding: tuple[float, ...] | list[float]) -> MemoryRecord:
        vector = self._validate(embedding)
        blob = struct.pack(f"<{len(vector)}f", *vector)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE memory_items
                SET embedding = ?, embedding_dim = ?
                WHERE item_id = ?
                """,
                (blob, len(vector), item_id),
            )
            if cursor.rowcount != 1:
                raise MemoryNotFoundError("memory item not found")
        return self.memory.get(item_id)

    def search_active(
        self,
        *,
        scope: MemoryScope,
        scope_id: str,
        query_embedding: tuple[float, ...] | list[float],
        limit: int = 10,
    ) -> list[MemoryRecord]:
        if not isinstance(scope, MemoryScope):
            raise MemoryValidationError("scope must be a MemoryScope")
        query = self._validate(query_embedding)
        if not scope_id.strip() or len(scope_id.strip()) > 256:
            raise MemoryValidationError("scope_id is invalid")
        bounded_limit = max(1, min(limit, 50))
        query_norm = math.sqrt(sum(value * value for value in query))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT item_id, confidence, created_at_ms, embedding
                FROM memory_items
                WHERE scope_type = ? AND scope_id = ? AND status = 'active'
                  AND embedding IS NOT NULL AND embedding_dim = ?
                """,
                (scope.value, scope_id.strip(), len(query)),
            ).fetchall()
        scored: list[tuple[float, float, int, str]] = []
        for row in rows:
            blob = row["embedding"]
            if not isinstance(blob, bytes) or len(blob) != len(query) * 4:
                continue
            vector = struct.unpack(f"<{len(query)}f", blob)
            norm = math.sqrt(sum(value * value for value in vector))
            if norm == 0:
                continue
            similarity = sum(a * b for a, b in zip(query, vector, strict=True))
            similarity /= query_norm * norm
            scored.append(
                (
                    similarity,
                    float(row["confidence"]),
                    int(row["created_at_ms"]),
                    str(row["item_id"]),
                )
            )
        scored.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
        return [self.memory.get(item[3]) for item in scored[:bounded_limit]]

    def status(self) -> dict[str, int]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) AS embedded,
                       SUM(CASE WHEN status = 'active' AND embedding IS NOT NULL
                                THEN 1 ELSE 0 END) AS active_embedded
                FROM memory_items
                """
            ).fetchone()
        return {
            "total": int(row["total"] or 0),
            "embedded": int(row["embedded"] or 0),
            "active_embedded": int(row["active_embedded"] or 0),
        }
