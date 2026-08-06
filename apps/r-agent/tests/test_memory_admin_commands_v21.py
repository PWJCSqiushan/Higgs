from pathlib import Path

from r_agent.events import ConversationKind, InboundEvent
from r_agent.identity import Principal
from r_agent.memory import MemoryKind, MemoryScope, MemoryStore
from r_agent.memory_v2 import MemoryObservationStore
from r_agent.owner_commands import OwnerCommandContext, OwnerCommandRouter
from r_agent.recall import RecallLedger
from r_agent.vector_memory import MemoryVectorStore

OWNER = Principal("owner-principal", "owner")


def build_router(tmp_path: Path) -> tuple[OwnerCommandRouter, MemoryObservationStore]:
    memory = MemoryStore(tmp_path / "memory.sqlite")
    memory.initialize()
    observations = MemoryObservationStore(memory.path)
    observations.initialize()
    recall = RecallLedger(memory.path)
    recall.initialize()
    vectors = MemoryVectorStore(memory.path, memory=memory)
    router = OwnerCommandRouter(
        context=OwnerCommandContext("live", 0, 0, 0, True, True, True),
        vectors=vectors,
        memory=memory,
        observations=observations,
        recall_ledger=recall,
    )
    return router, observations


def test_owner_can_list_and_retry_failed_observations_without_content(tmp_path: Path) -> None:
    router, observations = build_router(tmp_path)
    event = InboundEvent(
        channel="qq",
        account_id="900001",
        sender_id="800001",
        message_id="42",
        occurred_at_ms=1_767_225_600_000,
        conversation_kind=ConversationKind.PRIVATE,
        conversation_id="qq:private:900001:800001",
        group_id=None,
        text="private source text must not appear in admin failure output",
        mentioned=False,
    )
    assert observations.enqueue(event, principal_id="owner-principal", principal_role="owner")
    observation_id = observations.pending()[0].observation_id
    observations.fail(observation_id, error=ValueError("sensitive diagnostic detail"))

    listing = router.handle("/higgs memory observations failed 10", actor=OWNER) or ""
    assert observation_id[:8] in listing
    assert "private source text" not in listing
    assert "sensitive diagnostic detail" not in listing

    response = router.handle(f"/higgs memory observations retry {observation_id[:8]}", actor=OWNER)
    assert "queued for retry" in (response or "")
    assert observations.stats()["pending"] == 1


def test_owner_recent_recall_command_shows_real_short_memory_id(tmp_path: Path) -> None:
    router, _ = build_router(tmp_path)
    memory = router.memory
    item = memory.propose(
        scope=MemoryScope.PRINCIPAL,
        scope_id="alice",
        kind=MemoryKind.PREFERENCE,
        text="Alice prefers morning runs",
        source_channel="qq",
        source_account_id="900001",
        source_message_id="1",
        source_principal_id="alice",
        created_by="test",
        now_ms=1_767_225_600_000,
    )
    active = memory.activate(item.item_id, actor=OWNER, reason="verified")
    assert router.recall_ledger is not None
    router.recall_ledger.record(
        turn_id="turn-1",
        conversation_key="qq:private:alice",
        requesting_principal_id="alice",
        query="When should Alice run?",
        memories=[active],
        allowed_scopes=frozenset({(MemoryScope.PRINCIPAL, "alice")}),
        policy_version="scope-first-v1",
        now_ms=1_767_225_600_100,
    )

    response = router.handle("/higgs memory recall 10", actor=OWNER) or ""
    assert "recent_recalls=1" in response
    assert item.item_id[:8] in response
    assert "When should Alice run?" not in response
