"""Hybrid FTS5 and vector recall with strict scope filtering."""

from __future__ import annotations

import re
import sqlite3
import time
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
                # One initialization sync is followed by incremental triggers.  Query
                # traffic never rebuilds the entire index.
                conn.execute("DELETE FROM memory_items_fts")
                conn.execute(
                    """
                    INSERT INTO memory_items_fts(item_id,text,scope_type,scope_id,status)
                    SELECT item_id,text,scope_type,scope_id,status FROM memory_items
                    """
                )
                conn.executescript(
                    """
                    CREATE TRIGGER IF NOT EXISTS memory_fts_after_insert
                    AFTER INSERT ON memory_items BEGIN
                      INSERT INTO memory_items_fts(item_id,text,scope_type,scope_id,status)
                      VALUES (new.item_id,new.text,new.scope_type,new.scope_id,new.status);
                    END;
                    CREATE TRIGGER IF NOT EXISTS memory_fts_after_update
                    AFTER UPDATE OF text,scope_type,scope_id,status ON memory_items BEGIN
                      DELETE FROM memory_items_fts WHERE item_id=old.item_id;
                      INSERT INTO memory_items_fts(item_id,text,scope_type,scope_id,status)
                      VALUES (new.item_id,new.text,new.scope_type,new.scope_id,new.status);
                    END;
                    CREATE TRIGGER IF NOT EXISTS memory_fts_after_delete
                    AFTER DELETE ON memory_items BEGIN
                      DELETE FROM memory_items_fts WHERE item_id=old.item_id;
                    END;
                    """
                )
            return True
        except sqlite3.OperationalError:
            return False

    @staticmethod
    def _match_query(query: str) -> str:
        clean = " ".join(query.strip().split()).replace('"', '""')
        terms: list[str] = []
        for span in re.findall(r"[\u3400-\u9fff]+|[A-Za-z0-9_]+", clean):
            if len(span) >= 3:
                terms.extend(span[index : index + 3] for index in range(len(span) - 2))
            else:
                terms.append(span)
        unique = list(dict.fromkeys(terms))[:20]
        return " OR ".join(f'"{term}"' for term in unique) or f'"{clean}"'

    def _lexical(
        self, *, scope: MemoryScope, scope_id: str, query: str, limit: int
    ) -> list[MemoryRecord]:
        if not self.fts_available:
            return self.memory.search_active(
                scope=scope, scope_id=scope_id, query=query, limit=limit
            )
        if len(query.strip()) < 3:
            return self.memory.search_active(
                scope=scope, scope_id=scope_id, query=query, limit=limit
            )
        try:
            now_ms = int(time.time() * 1000)
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT f.item_id
                    FROM memory_items_fts AS f
                    JOIN memory_items AS m ON m.item_id=f.item_id
                    WHERE memory_items_fts MATCH ?
                      AND f.scope_type = ? AND f.scope_id = ? AND f.status = 'active'
                      AND m.valid_from_ms <= ?
                      AND (m.valid_to_ms IS NULL OR m.valid_to_ms > ?)
                    ORDER BY bm25(memory_items_fts), f.item_id
                    LIMIT ?
                    """,
                    (
                        self._match_query(query),
                        scope.value,
                        scope_id.strip(),
                        now_ms,
                        now_ms,
                        limit,
                    ),
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
        max_chars: int = 1200,
        min_rrf_score: float = 0.015,
        min_vector_similarity: float = 0.35,
    ) -> list[MemoryRecord]:
        bounded_limit = max(1, min(limit, 20))
        bounded_chars = max(100, min(max_chars, 4000))
        lexical = self._lexical(
            scope=scope, scope_id=scope_id, query=query, limit=max(20, bounded_limit * 3)
        )
        vector = (
            self.vectors.search_active(
                scope=scope,
                scope_id=scope_id,
                query_embedding=query_embedding,
                limit=max(20, bounded_limit * 3),
                min_similarity=min_vector_similarity,
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
        ordered = sorted(ranked.values(), key=lambda value: (-value[1], value[0].item_id))
        selected: list[MemoryRecord] = []
        used_chars = 0
        for item, score in ordered:
            if score < min_rrf_score:
                continue
            item_chars = len(item.text)
            if used_chars + item_chars > bounded_chars:
                continue
            selected.append(item)
            used_chars += item_chars
            if len(selected) >= bounded_limit:
                break
        return selected
