from r_agent.access import IngressDecision
from r_agent.events import ConversationKind, InboundEvent
from r_agent.ingest import IngestResult
from r_agent.phase2_reply import ReplyDecision, ReplyPolicy


def event(text: str) -> InboundEvent:
    return InboundEvent(
        channel="qq",
        account_id="900001",
        sender_id="800001",
        message_id="1",
        occurred_at_ms=1,
        conversation_kind=ConversationKind.PRIVATE,
        conversation_id="private",
        group_id=None,
        text=text,
        mentioned=False,
    )


def test_pause_keeps_owner_command_channel_available() -> None:
    policy = ReplyPolicy(
        mode="live",
        private_users=frozenset({"800001"}),
        groups=frozenset(),
        require_mention=True,
        max_per_minute=1,
        owner_qq="800001",
        runtime_enabled=False,
    )
    accepted = IngestResult(IngressDecision.ACCEPT, stored=True)
    assert policy.gate(event("普通消息"), accepted) is ReplyDecision.RUNTIME_PAUSED
    assert policy.gate(event("/higgs enable"), accepted) is ReplyDecision.SENT
