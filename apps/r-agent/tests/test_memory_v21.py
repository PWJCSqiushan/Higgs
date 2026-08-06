import sqlite3
from pathlib import Path

import pytest

import r_agent.memory_v2 as memory_v2
from r_agent.events import ConversationKind, InboundEvent
from r_agent.hybrid_recall import HybridMemorySearch
from r_agent.identity import Principal
from r_agent.memory import MemoryKind, MemoryRisk, MemoryScope, MemoryStatus, MemoryStore
from r_agent.memory_v2 import MemoryObservationStore, MemoryReconciler
from r_agent.vector_memory import MemoryVectorStore

OWNER = Principal("owner", "owner")


def _propose(memory: MemoryStore, message_id: str, text: str, **kwargs):
    return memory.propose(
        scope=MemoryScope.PRINCIPAL,
        scope_id="owner",
        kind=MemoryKind.PREFERENCE,
        text=text,
        source_channel="qq",
        source_account_id="bot",
        source_message_id=message_id,
        source_principal_id="owner",
        source_principal_role="owner",
        created_by="memory-reconciler-v2",
        risk=MemoryRisk.LOW,
        confidence=0.95,
        now_ms=1_767_225_600_000,
        **kwargs,
    )


def _event(message_id: str, text: str) -> InboundEvent:
    return InboundEvent(
        channel="qq",
        account_id="bot",
        sender_id="owner-account",
        message_id=message_id,
        occurred_at_ms=1_767_225_600_000,
        conversation_kind=ConversationKind.PRIVATE,
        conversation_id="qq:private:bot:owner-account",
        group_id=None,
        text=text,
        mentioned=False,
    )


def test_schema_migration_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "memory.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE memory_items (
                item_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
                scope_type TEXT NOT NULL, scope_id TEXT NOT NULL, kind TEXT NOT NULL,
                text TEXT NOT NULL, source_channel TEXT NOT NULL,
                source_account_id TEXT NOT NULL, source_message_id TEXT NOT NULL,
                source_principal_id TEXT NOT NULL, created_by TEXT NOT NULL,
                risk TEXT NOT NULL, confidence REAL NOT NULL, status TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL, reviewed_at_ms INTEGER,
                reviewed_by TEXT, invalidated_reason TEXT, embedding BLOB,
                embedding_dim INTEGER
            )
            """
        )
    memory = MemoryStore(path)
    memory.initialize()
    memory.initialize()
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_items)")}
        versions = conn.execute("SELECT version FROM memory_schema_versions").fetchall()
    assert {
        "importance",
        "source_trust",
        "valid_from_ms",
        "valid_to_ms",
        "supersedes_item_id",
        "source_principal_role",
    } <= columns
    assert versions == [(2,)]


def test_non_owner_can_never_use_auto_activation_lane(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite")
    memory.initialize()
    for message_id in ("m1", "m2"):
        item = memory.propose(
            scope=MemoryScope.PRINCIPAL,
            scope_id="user-a",
            kind=MemoryKind.PREFERENCE,
            text="该用户表达过偏好：清晨跑步",
            source_channel="qq",
            source_account_id="bot",
            source_message_id=message_id,
            source_principal_id="user-a",
            source_principal_role="user",
            created_by="memory-reconciler-v2",
            risk=MemoryRisk.LOW,
            confidence=0.99,
        )
    outcome = memory.auto_review_candidate(item.item_id, min_confidence=0.9, min_evidence=2)
    assert outcome.decision == "manual_review_required"
    assert outcome.record.status is MemoryStatus.CANDIDATE


def test_activating_revision_closes_superseded_version(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite")
    memory.initialize()
    old = _propose(memory, "old", "该用户表达过偏好：早晨跑步")
    memory.activate(old.item_id, actor=OWNER, reason="verified")
    new = _propose(
        memory,
        "new",
        "该用户表达过偏好：晚上跑步",
        supersedes_item_id=old.item_id,
    )
    memory.activate(new.item_id, actor=OWNER, reason="correction")
    previous = memory.get(old.item_id)
    assert previous.status is MemoryStatus.INVALIDATED
    assert previous.valid_to_ms is not None
    assert memory.get(new.item_id).supersedes_item_id == old.item_id


def test_incremental_fts_and_no_unrelated_fallback(tmp_path: Path) -> None:
    path = tmp_path / "memory.sqlite"
    memory = MemoryStore(path)
    memory.initialize()
    vectors = MemoryVectorStore(path, memory=memory)
    search = HybridMemorySearch(path, memory=memory, vectors=vectors)
    assert (
        search.search(
            scope=MemoryScope.PRINCIPAL,
            scope_id="owner",
            query="完全无关的问题",
            query_embedding=None,
        )
        == []
    )
    item = _propose(memory, "fts-new", "主人喜欢越野跑训练")
    memory.activate(item.item_id, actor=OWNER, reason="verified")
    assert [
        record.item_id
        for record in search.search(
            scope=MemoryScope.PRINCIPAL,
            scope_id="owner",
            query="越野跑",
            query_embedding=None,
        )
    ] == [item.item_id]


def test_vector_recall_respects_future_validity(tmp_path: Path) -> None:
    path = tmp_path / "memory.sqlite"
    memory = MemoryStore(path)
    memory.initialize()
    item = _propose(
        memory,
        "future",
        "该用户表达过偏好：未来再考虑的安排",
        valid_from_ms=9_999_999_999_999,
    )
    memory.activate(item.item_id, actor=OWNER, reason="reviewed for future use")
    vectors = MemoryVectorStore(path, memory=memory)
    vectors.set(item.item_id, (1.0, 0.0))
    assert (
        vectors.search_active(
            scope=MemoryScope.PRINCIPAL,
            scope_id="owner",
            query_embedding=(1.0, 0.0),
        )
        == []
    )


@pytest.mark.asyncio
async def test_bad_observation_does_not_block_batch(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "memory.sqlite"
    memory = MemoryStore(path)
    memory.initialize()
    observations = MemoryObservationStore(path)
    observations.initialize()
    observations.enqueue(
        _event("bad", "我喜欢坏数据"), principal_id="owner", principal_role="owner"
    )
    observations.enqueue(
        _event("good", "我喜欢清晨跑步"), principal_id="owner", principal_role="owner"
    )
    original = memory_v2._extract

    def extract_with_one_failure(observation):
        if observation.message_id == "bad":
            raise ValueError("private message text must not enter audit")
        return original(observation)

    monkeypatch.setattr(memory_v2, "_extract", extract_with_one_failure)
    reconciler = MemoryReconciler(
        observations=observations,
        memory=memory,
        vectors=MemoryVectorStore(path, memory=memory),
        embedding_client=None,
        auto_review_enabled=lambda: False,
        auto_review_confidence=lambda: 0.9,
        auto_review_evidence=lambda: 2,
    )
    summary = await reconciler.reconcile_once()
    assert summary.failed == 1
    assert summary.candidates == 1
    failed = observations.list_failed()
    assert len(failed) == 1
    assert failed[0]["error_type"] == "ValueError"
    assert "private message" not in str(failed)
    assert observations.retry_failed(str(failed[0]["observation_id"])[:8]) is True
