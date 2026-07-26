import sqlite3
from pathlib import Path

import pytest

from r_agent.identity import Principal
from r_agent.memory import MemoryKind, MemoryScope, MemoryStore
from r_agent.recall import (
    RecallConflictError,
    RecallLedger,
    RecallPermissionError,
    RecallValidationError,
)

OWNER = Principal("owner-principal", "owner")
USER = Principal("user-principal", "user")


def stores(tmp_path: Path) -> tuple[MemoryStore, RecallLedger]:
    path = tmp_path / "memory.sqlite"
    memory = MemoryStore(path)
    memory.initialize()
    recall = RecallLedger(path)
    recall.initialize()
    return memory, recall


def proposal(memory: MemoryStore, *, scope_id: str = "alice", message_id: str = "1"):
    return memory.propose(
        scope=MemoryScope.PRINCIPAL,
        scope_id=scope_id,
        kind=MemoryKind.PREFERENCE,
        text=f"{scope_id} prefers morning runs",
        source_channel="qq",
        source_account_id="900001",
        source_message_id=message_id,
        source_principal_id=scope_id,
        created_by="candidate-extractor-v1",
        confidence=0.8,
        now_ms=1_767_225_600_000,
    )


def record(recall: RecallLedger, memory_item, *, query: str = "When should Alice run?"):
    return recall.record(
        turn_id="turn-1",
        conversation_key="qq:private:alice",
        requesting_principal_id="alice",
        query=query,
        memories=[memory_item],
        allowed_scopes=frozenset({(MemoryScope.PRINCIPAL, "alice")}),
        policy_version="scope-first-v1",
        now_ms=1_767_225_600_100,
    )


def test_records_only_ids_and_query_hash_without_content(tmp_path: Path) -> None:
    memory, recall = stores(tmp_path)
    item = proposal(memory)
    active = memory.activate(item.item_id, actor=OWNER, reason="verified")
    entry = record(recall, active)

    assert entry.memory_item_ids == (item.item_id,)
    assert entry.memory_scope_keys == ("principal:alice",)
    with sqlite3.connect(recall.path) as conn:
        blob = " ".join(
            str(value)
            for value in conn.execute(
                """
                SELECT query_sha256, memory_item_ids_json, memory_scope_keys_json
                FROM recall_ledger WHERE turn_id = 'turn-1'
                """
            ).fetchone()
        )
    assert "When should Alice run?" not in blob
    assert "prefers morning runs" not in blob


def test_rejects_candidate_and_cross_scope_memory(tmp_path: Path) -> None:
    memory, recall = stores(tmp_path)
    candidate = proposal(memory)
    with pytest.raises(RecallValidationError, match="only active"):
        record(recall, candidate)

    bob = proposal(memory, scope_id="bob", message_id="2")
    active_bob = memory.activate(bob.item_id, actor=OWNER, reason="verified")
    with pytest.raises(RecallValidationError, match="outside"):
        record(recall, active_bob)


def test_rejects_duplicate_item_in_one_recall(tmp_path: Path) -> None:
    memory, recall = stores(tmp_path)
    item = proposal(memory)
    active = memory.activate(item.item_id, actor=OWNER, reason="verified")
    with pytest.raises(RecallValidationError, match="duplicate"):
        recall.record(
            turn_id="turn-1",
            conversation_key="qq:private:alice",
            requesting_principal_id="alice",
            query="running",
            memories=[active, active],
            allowed_scopes=frozenset({(MemoryScope.PRINCIPAL, "alice")}),
            policy_version="scope-first-v1",
        )


def test_same_turn_is_idempotent_but_conflicting_reuse_is_rejected(tmp_path: Path) -> None:
    memory, recall = stores(tmp_path)
    item = proposal(memory)
    active = memory.activate(item.item_id, actor=OWNER, reason="verified")
    first = record(recall, active)
    second = record(recall, active)
    assert second.recall_id == first.recall_id

    with pytest.raises(RecallConflictError):
        record(recall, active, query="different query")


def test_only_owner_can_read_recall_audit(tmp_path: Path) -> None:
    memory, recall = stores(tmp_path)
    item = proposal(memory)
    active = memory.activate(item.item_id, actor=OWNER, reason="verified")
    record(recall, active)

    assert recall.get_for_owner("turn-1", actor=OWNER).turn_id == "turn-1"
    assert [entry.turn_id for entry in recall.list_recent(actor=OWNER)] == ["turn-1"]
    with pytest.raises(RecallPermissionError):
        recall.get_for_owner("turn-1", actor=USER)
    with pytest.raises(RecallPermissionError):
        recall.list_recent(actor=USER)


def test_ledger_survives_memory_hard_delete(tmp_path: Path) -> None:
    memory, recall = stores(tmp_path)
    item = proposal(memory)
    active = memory.activate(item.item_id, actor=OWNER, reason="verified")
    record(recall, active)
    memory.hard_delete(item.item_id, actor=OWNER, reason="privacy request")

    entry = recall.get_for_owner("turn-1", actor=OWNER)
    assert entry.memory_item_ids == (item.item_id,)
