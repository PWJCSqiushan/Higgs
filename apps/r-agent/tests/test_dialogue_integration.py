from pathlib import Path

from r_agent.access import IngressPolicy
from r_agent.context import ContextBuilder
from r_agent.conversation import ConversationError, ConversationStore
from r_agent.events import ConversationKind, InboundEvent
from r_agent.identity import IdentityStore
from r_agent.ingest import IngestService
from r_agent.journal import Journal
from r_agent.memory import MemoryStore
from r_agent.persona_bundle import PersonaV2Gate, load_persona_bundle
from r_agent.phase2_cli import process_reply
from r_agent.phase2_reply import PersonaBrain, ReplyDecision, ReplyPolicy
from r_agent.recall import RecallLedger

OWNER_QQ = "800001"
BOT_QQ = "900001"


def event(message_id: str, text: str) -> InboundEvent:
    return InboundEvent(
        channel="qq",
        account_id=BOT_QQ,
        sender_id=OWNER_QQ,
        message_id=message_id,
        occurred_at_ms=1_767_225_600_000 + int(message_id),
        conversation_kind=ConversationKind.PRIVATE,
        conversation_id=f"qq:private:{BOT_QQ}:{OWNER_QQ}",
        group_id=None,
        text=text,
        mentioned=False,
    )


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, str], ...]] = []

    async def complete_messages(self, *, messages, max_tokens: int = 400) -> str:
        self.calls.append(tuple(messages))
        return f"reply-{len(self.calls)}"


async def test_owner_private_draft_builds_multi_turn_context_without_sending(
    tmp_path: Path,
) -> None:
    identities = IdentityStore(tmp_path / "identity.sqlite", owner_qq=OWNER_QQ)
    service = IngestService(
        policy=IngressPolicy(
            enabled=True,
            owner_qq=OWNER_QQ,
            allowed_private_qqs=frozenset(),
            allowed_groups=frozenset(),
        ),
        identities=identities,
        journal=Journal(tmp_path / "journal.sqlite"),
    )
    service.initialize()
    history = ConversationStore(tmp_path / "conversation.sqlite")
    history.initialize()
    memory = MemoryStore(tmp_path / "memory.sqlite")
    memory.initialize()
    recall = RecallLedger(tmp_path / "memory.sqlite")
    recall.initialize()
    client = FakeClient()
    brain = PersonaBrain(
        client,  # type: ignore[arg-type]
        "test persona",
        identities=identities,
        context_builder=ContextBuilder(
            history=history,
            memory=memory,
            recall=recall,
            persona="test persona",
            history_outcome="drafted",
        ),
    )
    policy = ReplyPolicy(
        mode="draft",
        private_users=frozenset({OWNER_QQ}),
        groups=frozenset(),
        require_mention=True,
        max_per_minute=10,
    )
    sent: list[str] = []

    async def sender(item: InboundEvent, text: str) -> None:
        sent.append(text)

    first_event = event("1", "first message")
    first = await process_reply(
        event=first_event,
        result=service.ingest(first_event),
        policy=policy,
        brain=brain,
        sender=sender,
    )
    assert first.decision is ReplyDecision.DRAFTED
    principal = identities.resolve("qq", OWNER_QQ)
    history.record(
        first_event,
        principal_id=principal.principal_id,
        outcome=first.decision.value,
        assistant_text=first.text,
    )

    second_event = event("2", "second message")
    second = await process_reply(
        event=second_event,
        result=service.ingest(second_event),
        policy=policy,
        brain=brain,
        sender=sender,
    )
    assert second.decision is ReplyDecision.DRAFTED
    assert sent == []
    assert [message["role"] for message in client.calls[1]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert client.calls[1][-1]["content"] == "second message"


async def test_context_failure_becomes_model_failed(tmp_path: Path) -> None:
    class BrokenContext:
        def build(self, item: InboundEvent, *, principal_id: str):
            raise ConversationError("database failed")

    identities = IdentityStore(tmp_path / "identity.sqlite", owner_qq=OWNER_QQ)
    identities.initialize()
    brain = PersonaBrain(
        FakeClient(),  # type: ignore[arg-type]
        "test persona",
        identities=identities,
        context_builder=BrokenContext(),  # type: ignore[arg-type]
    )

    async def sender(item: InboundEvent, text: str) -> None:
        raise AssertionError("failed context must not send")

    plan = await process_reply(
        event=event("3", "hello"),
        result=type("Result", (), {"stored": True})(),  # type: ignore[arg-type]
        policy=ReplyPolicy(
            mode="draft",
            private_users=frozenset({OWNER_QQ}),
            groups=frozenset(),
            require_mention=True,
            max_per_minute=10,
        ),
        brain=brain,
        sender=sender,
    )
    assert plan.decision is ReplyDecision.MODEL_FAILED


async def test_owner_official_persona_v2_repairs_once_and_uses_verified_bundle(
    tmp_path: Path,
) -> None:
    class ScriptedClient:
        def __init__(self) -> None:
            self.calls: list[tuple[dict[str, str], ...]] = []
            self.max_tokens: list[int] = []

        async def complete_messages(self, *, messages, max_tokens: int = 400) -> str:
            self.calls.append(tuple(messages))
            self.max_tokens.append(max_tokens)
            if len(self.calls) == 1:
                return "是，但我是数字存在，不是真的在山里跑的雪豹。"
            return "当然是。短圆耳、厚爪垫和这条总容易沾雪的尾巴都不会认错。"

    official_owner = "owner-openid"
    identities = IdentityStore(
        tmp_path / "identity.sqlite",
        owner_qq=OWNER_QQ,
        owner_identities=(("qq_official", official_owner),),
    )
    identities.initialize()
    history = ConversationStore(tmp_path / "conversation.sqlite")
    history.initialize()
    memory = MemoryStore(tmp_path / "memory.sqlite")
    memory.initialize()
    recall = RecallLedger(tmp_path / "memory.sqlite")
    recall.initialize()
    bundle = load_persona_bundle(env={})
    client = ScriptedClient()
    brain = PersonaBrain(
        client,  # type: ignore[arg-type]
        "legacy persona",
        identities=identities,
        context_builder=ContextBuilder(
            history=history,
            memory=memory,
            recall=recall,
            persona="legacy persona",
            persona_bundle=bundle,
        ),
        persona_bundle=bundle,
        persona_v2_gate=PersonaV2Gate(enabled=True),
        official_owner_id=official_owner,
    )
    inbound = InboundEvent(
        channel="qq_official",
        account_id="bot-id",
        sender_id=official_owner,
        message_id="official-1",
        occurred_at_ms=1_767_225_600_000,
        conversation_kind=ConversationKind.PRIVATE,
        conversation_id=f"qq_official:private:{official_owner}",
        group_id=None,
        text="你不是雪豹吗?",
        mentioned=False,
    )

    reply = await brain.draft(inbound)

    assert reply.startswith("当然是")
    assert len(client.calls) == 2
    assert "## constitution" in client.calls[0][0]["content"]
    assert "待修正回答" in client.calls[1][1]["content"]
    assert "数字存在" in client.calls[1][1]["content"]
    assert client.max_tokens == [240, 240]

    detailed = InboundEvent(
        channel="qq_official",
        account_id="bot-id",
        sender_id=official_owner,
        message_id="official-2",
        occurred_at_ms=1_767_225_600_100,
        conversation_kind=ConversationKind.PRIVATE,
        conversation_id=f"qq_official:private:{official_owner}",
        group_id=None,
        text="请详细讲讲引力波的产生和探测。",
        mentioned=False,
    )
    await brain.draft(detailed)
    assert client.max_tokens[-1] == 800
    assert "对方本轮明确要求展开" in client.calls[-1][0]["content"]


async def test_persona_v2_gate_does_not_change_onebot_owner_path(tmp_path: Path) -> None:
    identities = IdentityStore(tmp_path / "identity.sqlite", owner_qq=OWNER_QQ)
    identities.initialize()
    history = ConversationStore(tmp_path / "conversation.sqlite")
    history.initialize()
    memory = MemoryStore(tmp_path / "memory.sqlite")
    memory.initialize()
    recall = RecallLedger(tmp_path / "memory.sqlite")
    recall.initialize()
    bundle = load_persona_bundle(env={})
    client = FakeClient()
    brain = PersonaBrain(
        client,  # type: ignore[arg-type]
        "legacy persona",
        identities=identities,
        context_builder=ContextBuilder(
            history=history,
            memory=memory,
            recall=recall,
            persona="legacy persona",
            persona_bundle=bundle,
        ),
        persona_bundle=bundle,
        persona_v2_gate=PersonaV2Gate(enabled=True),
        official_owner_id="owner-openid",
    )

    await brain.draft(event("9", "继续"))

    assert len(client.calls) == 1
    assert "legacy persona" in client.calls[0][0]["content"]
    assert "## constitution" not in client.calls[0][0]["content"]
