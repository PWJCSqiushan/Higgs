from pathlib import Path

import pytest

from r_agent.context import ContextBuilder
from r_agent.conversation import ConversationStore
from r_agent.events import ConversationKind, InboundEvent
from r_agent.identity import Principal
from r_agent.memory import MemoryKind, MemoryScope, MemoryStore
from r_agent.persona_bundle import load_persona_bundle
from r_agent.persona_evolution import EvolutionCandidate, SelfMemoryService
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

    built = builder.build(event("2", "上午深度学习怎么安排?"), principal_id="owner")
    assert [message["role"] for message in built.messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert "主人偏好上午安排深度学习" in built.messages[0]["content"]
    assert built.messages[-1]["content"] == "上午深度学习怎么安排?"
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


def test_context_hashes_long_platform_message_id_for_bounded_recall_key(
    tmp_path: Path,
) -> None:
    history, memory, recall = stores(tmp_path)
    builder = ContextBuilder(
        history=history,
        memory=memory,
        recall=recall,
        persona="test persona",
        memory_limit=0,
    )
    long_message_id = "platform-message-" + "x" * 160
    inbound = InboundEvent(
        channel="qq_official",
        account_id="bot-account-identifier",
        sender_id="owner-openid-placeholder",
        message_id=long_message_id,
        occurred_at_ms=1_767_225_600_000,
        conversation_kind=ConversationKind.PRIVATE,
        conversation_id="qq_official:private:owner-openid-placeholder",
        group_id=None,
        text="测试",
        mentioned=False,
    )

    built = builder.build(inbound, principal_id="owner", principal_role="owner")

    assert built.turn_id.startswith("event-sha256:")
    assert len(built.turn_id) == 77
    assert long_message_id not in built.turn_id
    assert recall.get_for_owner(built.turn_id, actor=OWNER).turn_id == built.turn_id


def test_persona_v2_context_orders_safety_before_verified_bundle_and_memory(
    tmp_path: Path,
) -> None:
    history, memory, recall = stores(tmp_path)
    bundle = load_persona_bundle(env={})
    builder = ContextBuilder(
        history=history,
        memory=memory,
        recall=recall,
        persona="legacy persona",
        persona_bundle=bundle,
        memory_limit=0,
    )

    built = builder.build(event("6", "继续"), principal_id="owner", use_persona_v2=True)
    system = built.messages[0]["content"]

    assert system.index("# 不可覆盖的安全与权限规则") < system.index("# Higgs Persona Bundle")
    assert system.index("## constitution") < system.index("## style")
    assert system.index("## style") < system.index("## examples")
    assert system.index("## examples") < system.index("# Higgs 已激活的自我记忆")
    assert "legacy persona" not in system


def test_persona_v2_context_fails_closed_without_verified_bundle(tmp_path: Path) -> None:
    history, memory, recall = stores(tmp_path)
    builder = ContextBuilder(
        history=history,
        memory=memory,
        recall=recall,
        persona="legacy persona",
        memory_limit=0,
    )

    with pytest.raises(ValueError, match="verified bundle"):
        builder.build(event("7", "继续"), principal_id="owner", use_persona_v2=True)


def test_photography_self_stance_survives_history_expiry_and_restart(tmp_path: Path) -> None:
    history, memory, recall = stores(tmp_path)
    self_memory = SelfMemoryService(memory)
    seeded = self_memory.seed_photography_stance(actor=OWNER, confirm=True, now_ms=10)
    assert seeded.item_id is not None
    for index in range(10, 20):
        history.record(
            event(str(index), f"第{index}轮"),
            principal_id="owner",
            outcome="sent",
            assistant_text=f"第{index}轮回答",
            now_ms=index,
        )
    builder = ContextBuilder(
        history=history,
        memory=memory,
        recall=recall,
        persona="legacy persona",
        self_memory=self_memory,
        history_limit=8,
        memory_limit=8,
    )

    first = builder.build(event("90", "镜头和机身哪个更重要"), principal_id="owner")
    assert seeded.item_id in first.memory_item_ids
    assert "都不重要，也不该分开比" in first.messages[0]["content"]
    assert len([message for message in first.messages if message["role"] == "assistant"]) == 8

    restarted_memory = MemoryStore(memory.path)
    restarted_memory.initialize(self_memory_v4=True)
    restarted = ContextBuilder(
        history=ConversationStore(history.path),
        memory=restarted_memory,
        recall=RecallLedger(memory.path),
        persona="legacy persona",
        self_memory=SelfMemoryService(restarted_memory),
        history_limit=8,
        memory_limit=8,
    )
    second = restarted.build(event("91", "器材应该怎样取舍"), principal_id="owner")
    assert seeded.item_id in second.memory_item_ids
    assert "Higgs 原句证据" in second.messages[0]["content"]


def test_adopted_external_idea_hides_source_quote_from_context(tmp_path: Path) -> None:
    history, memory, recall = stores(tmp_path)
    self_memory = SelfMemoryService(memory)
    adopted = self_memory.submit_candidate(
        EvolutionCandidate(
            kind="adopted_idea",
            scope="persona",
            evidence_message_id="external-1",
            confidence=0.99,
            sensitive_level="low",
            normalized_content="观察光线应先于讨论器材",
            original_quote="某位群友说：先看光，再看器材",
        ),
        source_principal_id="private-member-id",
        source_message_id="external-1",
        now_ms=100,
    )
    assert adopted.item_id is not None
    builder = ContextBuilder(
        history=history,
        memory=memory,
        recall=recall,
        persona="legacy persona",
        self_memory=self_memory,
    )

    built = builder.build(event("92", "光线和器材"), principal_id="owner")
    system = built.messages[0]["content"]

    assert "观察光线应先于讨论器材" in system
    assert "某位群友说" not in system
    assert "private-member-id" not in system
    assert "外部来源已去标识" in system
