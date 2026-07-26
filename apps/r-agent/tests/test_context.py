from pathlib import Path

from r_agent.context import ContextBuilder
from r_agent.conversation import ConversationStore
from r_agent.events import ConversationKind, InboundEvent
from r_agent.identity import Principal
from r_agent.memory import MemoryKind, MemoryScope, MemoryStore
from r_agent.recall import RecallLedger

OWNER = Principal("owner", "owner")


def event(message_id: str, text: str) -> InboundEvent:
    return InboundEvent(
        channel="qq",
        account_id="900001",
        sender_id="800001",
        message_id=message_id,
        occurred_at_ms=1_767_225_600_000 + int(message_id),
        conversation_kind=ConversationKind.PRIVATE,
        conversation_id="qq:private:900001:800001",
        group_id=None,
        text=text,
        mentioned=False,
    )


def stores(tmp_path: Path):
    history = ConversationStore(tmp_path / "conversation.sqlite")
    history.initialize()
    memory = MemoryStore(tmp_path / "memory.sqlite")
    memory.initialize()
    recall = RecallLedger(tmp_path / "memory.sqlite")
    recall.initialize()
    return history, memory, recall


def propose(memory: MemoryStore, *, scope_id: str, message_id: str, text: str):
    return memory.propose(
        scope=MemoryScope.PRINCIPAL,
        scope_id=scope_id,
        kind=MemoryKind.PREFERENCE,
        text=text,
        source_channel="qq",
        source_account_id="900001",
        source_message_id=message_id,
        source_principal_id=scope_id,
        created_by="offline-test",
        confidence=0.9,
        now_ms=1_767_225_600_000,
    )


def test_context_includes_sent_history_and_owner_approved_memory(tmp_path: Path) -> None:
    history, memory, recall = stores(tmp_path)
    history.record(
        event("1", "我上午做什么?"),
        principal_id="owner",
        outcome="sent",
        assistant_text="先完成高强度学习。",
        now_ms=100,
    )
    item = propose(
        memory,
        scope_id="owner",
        message_id="m1",
        text="主人偏好上午安排深度学习",
    )
    memory.activate(item.item_id, actor=OWNER, reason="verified")
    builder = ContextBuilder(
        history=history,
        memory=memory,
        recall=recall,
        persona="你是有判断力、诚实而自然的长期助手。",
    )

    built = builder.build(event("2", "那下午呢?"), principal_id="owner")
    assert [message["role"] for message in built.messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert "主人偏好上午安排深度学习" in built.messages[0]["content"]
    assert built.messages[-1]["content"] == "那下午呢?"
    assert built.memory_item_ids == (item.item_id,)
    ledger = recall.get_for_owner(built.turn_id, actor=OWNER)
    assert ledger.memory_item_ids == (item.item_id,)


def test_context_excludes_candidate_and_cross_principal_memory(tmp_path: Path) -> None:
    history, memory, recall = stores(tmp_path)
    candidate = propose(
        memory,
        scope_id="owner",
        message_id="m1",
        text="candidate secret",
    )
    other = propose(
        memory,
        scope_id="other",
        message_id="m2",
        text="other user secret",
    )
    memory.activate(other.item_id, actor=OWNER, reason="verified")
    builder = ContextBuilder(
        history=history,
        memory=memory,
        recall=recall,
        persona="test persona",
    )

    built = builder.build(event("3", "hello"), principal_id="owner")
    system = built.messages[0]["content"]
    assert candidate.item_id not in built.memory_item_ids
    assert other.item_id not in built.memory_item_ids
    assert "candidate secret" not in system
    assert "other user secret" not in system


def test_context_prefers_semantically_nearest_active_memory(tmp_path: Path) -> None:
    history, memory, recall = stores(tmp_path)
    running = propose(
        memory,
        scope_id="owner",
        message_id="m1",
        text="主人喜欢清晨跑步",
    )
    photo = propose(
        memory,
        scope_id="owner",
        message_id="m2",
        text="主人喜欢夜景摄影",
    )
    memory.activate(running.item_id, actor=OWNER, reason="verified")
    memory.activate(photo.item_id, actor=OWNER, reason="verified")
    memory.set_embedding(running.item_id, (1.0, 0.0))
    memory.set_embedding(photo.item_id, (0.0, 1.0))
    builder = ContextBuilder(
        history=history,
        memory=memory,
        recall=recall,
        persona="test persona",
        memory_limit=1,
    )
    built = builder.build(
        event("5", "训练"),
        principal_id="owner",
        query_embedding=(0.9, 0.1),
    )
    assert built.memory_item_ids == (running.item_id,)


def test_memory_disabled_records_empty_recall_decision(tmp_path: Path) -> None:
    history, memory, recall = stores(tmp_path)
    builder = ContextBuilder(
        history=history,
        memory=memory,
        recall=recall,
        persona="test persona",
        memory_limit=0,
    )
    built = builder.build(event("4", "hello"), principal_id="owner")
    assert built.memory_item_ids == ()
    assert recall.get_for_owner(built.turn_id, actor=OWNER).memory_item_ids == ()
