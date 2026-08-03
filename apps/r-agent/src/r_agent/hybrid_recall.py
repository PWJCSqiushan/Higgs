"""Hybrid FTS5 and vector recall with strict scope filtering."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from r_agent.memory import MemoryRecord, MemoryScope, MemoryStore
from r_agent.vector_memory import MemoryVectorStore


class HybridMemorySearch:
    """Fuse lexical and vector ranks with reciprocal-rank fusion."""

    def __init__(self, path: Path, *, memory: MemoryStore, vectors: MemoryVectorStore) -> None:
        if path.resolve() != memory.path.resolve() or path.resolve() != vectors.path.resolve():
            raise ValueError("hybrid search stores must share one database")
        self.path = path
        self.memory = memory
        self.vectors = vectors
        self.fts_available = self._initialize_fts()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_fts(self) -> bool:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS memory_items_fts
                    USING fts5(
                        item_id UNINDEXED,
                        text,
                        scope_type UNINDEXED,
                        scope_id UNINDEXED,
                        status UNINDEXED,
                        tokenize='trigram'
                    )
                    """
                )
                conn.execute("DELETE FROM memory_items_fts")
                conn.execute(
                    """
                    INSERT INTO memory_items_fts(item_id,text,scope_type,scope_id,status)
                    SELECT item_id,text,scope_type,scope_id,status FROM memory_items
                    """
                )
            return True
        except sqlite3.OperationalError:
            return False

    def _refresh_fts(self) -> None:
        if not self.fts_available:
            return
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM memory_items_fts")
                conn.execute(
                    """
                    INSERT INTO memory_items_fts(item_id,text,scope_type,scope_id,status)
                    SELECT item_id,text,scope_type,scope_id,status FROM memory_items
                    """
                )
        except sqlite3.OperationalError:
            self.fts_available = False

    @staticmethod
    def _match_query(query: str) -> str:
        clean = " ".join(query.strip().split()).replace('"', '""')
        return f'"{clean}"'

    def _lexical(
        self, *, scope: MemoryScope, scope_id: str, query: str, limit: int
    ) -> list[MemoryRecord]:
        if not self.fts_available:
            return self.memory.search_active(
                scope=scope, scope_id=scope_id, query=query, limit=limit
            )
        self._refresh_fts()
        if len(query.strip()) < 3:
            return self.memory.search_active(
                scope=scope, scope_id=scope_id, query=query, limit=limit
            )
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT f.item_id
                    FROM memory_items_fts AS f
                    WHERE memory_items_fts MATCH ?
                      AND f.scope_type = ? AND f.scope_id = ? AND f.status = 'active'
                    ORDER BY bm25(memory_items_fts), f.item_id
                    LIMIT ?
                    """,
                    (self._match_query(query), scope.value, scope_id.strip(), limit),
                ).fetchall()
        except sqlite3.OperationalError:
            return self.memory.search_active(
                scope=scope, scope_id=scope_id, query=query, limit=limit
            )
        return [self.memory.get(str(row["item_id"])) for row in rows]

    def search(
        self,
        *,
        scope: MemoryScope,
        scope_id: str,
        query: str,
        query_embedding: tuple[float, ...] | None,
        limit: int = 8,
    ) -> list[MemoryRecord]:
        bounded_limit = max(1, min(limit, 20))
        lexical = self._lexical(
            scope=scope, scope_id=scope_id, query=query, limit=max(20, bounded_limit * 3)
        )
        vector = (
            self.vectors.search_active(
                scope=scope,
                scope_id=scope_id,
                query_embedding=query_embedding,
                limit=max(20, bounded_limit * 3),
            )
            if query_embedding is not None
            else []
        )
        ranked: dict[str, tuple[MemoryRecord, float]] = {}
        for source in (lexical, vector):
            for rank, item in enumerate(source):
                score = 1.0 / (60.0 + rank + 1)
                previous = ranked.get(item.item_id)
                ranked[item.item_id] = (
                    item,
                    score + (previous[1] if previous is not None else 0.0),
                )
        if not ranked:
            return self.memory.list_active_for_scope(
                scope=scope, scope_id=scope_id, limit=bounded_limit
            )
        ordered = sorted(ranked.values(), key=lambda value: (-value[1], value[0].item_id))
        return [item for item, _ in ordered[:bounded_limit]]
