from types import SimpleNamespace

from r_agent.access import IngressDecision
from r_agent.events import ConversationKind, InboundEvent
from r_agent.ingest import IngestResult
from r_agent.model_client import ModelError
from r_agent.phase2_cli import process_reply
from r_agent.phase2_outbound import OutboundError
from r_agent.phase2_reply import PersonaBrain, ReplyDecision, ReplyPolicy
from r_agent.transport import DeliveryReceipt, DeliveryState


def event(
    *,
    group: str | None = None,
    mentioned: bool = False,
    text: str = "hello",
    replied_to_account: bool = False,
) -> InboundEvent:
    kind = ConversationKind.GROUP if group else ConversationKind.PRIVATE
    return InboundEvent(
        channel="qq",
        account_id="900001",
        sender_id="800001",
        message_id="1",
        occurred_at_ms=1_767_225_600_000,
        conversation_kind=kind,
        conversation_id="c",
        group_id=group,
        text=text,
        mentioned=mentioned,
        replied_to_account=replied_to_account,
    )


def accepted() -> IngestResult:
    return IngestResult(IngressDecision.ACCEPT, stored=True)


def test_draft_requires_mention_for_group() -> None:
    policy = ReplyPolicy(
        mode="draft",
        private_users=frozenset({"800001"}),
        groups=frozenset({"700001"}),
        require_mention=True,
        max_per_minute=2,
    )
    assert policy.gate(event(group="700001"), accepted(), now=0) is ReplyDecision.MENTION_REQUIRED
    assert (
        policy.gate(event(group="700001", mentioned=True), accepted(), now=0)
        is ReplyDecision.DRAFTED
    )


def test_natural_group_accepts_configured_conversation_triggers() -> None:
    policy = ReplyPolicy(
        mode="draft",
        private_users=frozenset(),
        groups=frozenset({"700001", "700002"}),
        natural_trigger_groups=frozenset({"700002"}),
        require_mention=True,
        max_per_minute=6,
    )
    assert (
        policy.gate(event(group="700002", text="HIGGS 在吗"), accepted(), now=0)
        is ReplyDecision.DRAFTED
    )
    assert (
        policy.gate(event(group="700002", text="你怎么看"), accepted(), now=0)
        is ReplyDecision.GROUP_TRIGGER_REQUIRED
    )
    assert (
        policy.gate(
            event(group="700002", text="", replied_to_account=True),
            accepted(),
            now=0,
        )
        is ReplyDecision.DRAFTED
    )
    assert (
        policy.gate(event(group="700002", text="大家好"), accepted(), now=0)
        is ReplyDecision.GROUP_TRIGGER_REQUIRED
    )


def test_keywords_do_not_bypass_mention_in_default_group() -> None:
    policy = ReplyPolicy(
        mode="draft",
        private_users=frozenset(),
        groups=frozenset({"700001"}),
        natural_trigger_groups=frozenset(),
        require_mention=True,
        max_per_minute=6,
    )
    assert (
        policy.gate(event(group="700001", text="higgs 你在吗"), accepted(), now=0)
        is ReplyDecision.MENTION_REQUIRED
    )


def test_rate_limit_after_marking_sent() -> None:
    policy = ReplyPolicy(
        mode="live",
        private_users=frozenset({"800001"}),
        groups=frozenset(),
        require_mention=True,
        max_per_minute=1,
    )
    item = event()
    assert policy.gate(item, accepted(), now=0) is ReplyDecision.SENT
    policy.mark_sent(item, now=0)
    assert policy.gate(item, accepted(), now=1) is ReplyDecision.RATE_LIMITED
    assert policy.gate(item, accepted(), now=61) is ReplyDecision.SENT


async def test_draft_generation_counts_toward_rate_limit() -> None:
    policy = ReplyPolicy(
        mode="draft",
        private_users=frozenset({"800001"}),
        groups=frozenset(),
        require_mention=True,
        max_per_minute=1,
    )

    async def unused_sender(item: InboundEvent, text: str) -> None:
        raise AssertionError("draft mode must not send")

    item = event()
    plan = await process_reply(
        event=item,
        result=accepted(),
        policy=policy,
        brain=PersonaBrain(None, "test"),
        sender=unused_sender,
    )
    assert plan.decision is ReplyDecision.DRAFTED
    assert policy.gate(item, accepted()) is ReplyDecision.RATE_LIMITED


async def test_model_failure_becomes_auditable_decision() -> None:
    class BrokenBrain:
        async def draft(self, item: InboundEvent) -> str:
            raise ModelError("provider failed")

    async def unused_sender(item: InboundEvent, text: str) -> None:
        raise AssertionError("model failure must not send")

    plan = await process_reply(
        event=event(),
        result=accepted(),
        policy=ReplyPolicy(
            mode="draft",
            private_users=frozenset({"800001"}),
            groups=frozenset(),
            require_mention=True,
            max_per_minute=1,
        ),
        brain=BrokenBrain(),  # type: ignore[arg-type]
        sender=unused_sender,
    )
    assert plan.decision is ReplyDecision.MODEL_FAILED
    assert plan.text is None


async def test_send_failure_becomes_auditable_decision() -> None:
    async def broken_sender(item: InboundEvent, text: str) -> None:
        raise OutboundError("rejected")

    plan = await process_reply(
        event=event(),
        result=accepted(),
        policy=ReplyPolicy(
            mode="live",
            private_users=frozenset({"800001"}),
            groups=frozenset(),
            require_mention=True,
            max_per_minute=1,
        ),
        brain=PersonaBrain(None, "test"),
        sender=broken_sender,
    )
    assert plan.decision is ReplyDecision.SEND_FAILED
    assert plan.text is not None


async def test_unknown_delivery_receipt_is_not_reported_as_sent() -> None:
    async def unknown_sender(item: InboundEvent, text: str) -> DeliveryReceipt:
        return DeliveryReceipt("qq", DeliveryState.UNKNOWN, "unknown-send")

    plan = await process_reply(
        event=event(),
        result=accepted(),
        policy=ReplyPolicy(
            mode="live",
            private_users=frozenset({"800001"}),
            groups=frozenset(),
            require_mention=True,
            max_per_minute=1,
        ),
        brain=PersonaBrain(None, "test"),
        sender=unknown_sender,
    )
    assert plan.decision is ReplyDecision.SEND_FAILED


async def test_group_reply_passes_sender_scope_to_both_risk_guards() -> None:
    class Guard:
        def __init__(self) -> None:
            self.source_ids: list[str | None] = []

        def check_and_reserve(
            self,
            _conversation_id: str,
            *,
            is_owner: bool,
            source_id: str | None = None,
        ) -> SimpleNamespace:
            assert not is_owner
            self.source_ids.append(source_id)
            return SimpleNamespace(allowed=True)

    class Risk:
        def __init__(self) -> None:
            self.source_ids: list[str | None] = []

        def reserve_send(self, **kwargs: object) -> SimpleNamespace:
            self.source_ids.append(kwargs.get("source_id"))
            return SimpleNamespace(allowed=True, reservation_id=1)

        def finish_send(self, _reservation_id: int, *, outcome: str) -> None:
            assert outcome == "sent"

    async def sender(_item: InboundEvent, _text: str) -> DeliveryReceipt:
        return DeliveryReceipt("qq", DeliveryState.SENT, "group-sender-scope", "provider-1")

    guard = Guard()
    risk = Risk()
    plan = await process_reply(
        event=event(group="700001", mentioned=True),
        result=accepted(),
        policy=ReplyPolicy(
            mode="live",
            private_users=frozenset(),
            groups=frozenset({"700001"}),
            require_mention=True,
            max_per_minute=2,
        ),
        brain=PersonaBrain(None, "test"),
        sender=sender,
        breaker=guard,  # type: ignore[arg-type]
        owner_qq="owner",
        risk_ledger=risk,  # type: ignore[arg-type]
    )
    assert plan.decision is ReplyDecision.SENT
    assert guard.source_ids == ["800001"]
    assert risk.source_ids == ["800001"]


def test_private_reply_requires_explicit_user_permission() -> None:
    policy = ReplyPolicy(
        mode="live",
        private_users=frozenset({"800002"}),
        groups=frozenset(),
        require_mention=True,
        max_per_minute=1,
    )
    assert policy.gate(event(), accepted()) is ReplyDecision.PRIVATE_NOT_ENABLED


async def test_markdown_is_removed_before_send_and_audit() -> None:
    class MarkdownBrain:
        async def draft(self, item: InboundEvent) -> str:
            return "# **希格斯**\n* 雪豹\n计算：2 * 3\n```python\nprint('ok')\n```"

    sent: list[str] = []

    async def sender(item: InboundEvent, text: str) -> DeliveryReceipt:
        sent.append(text)
        return DeliveryReceipt("qq", DeliveryState.SENT, "test-send", "provider-1")

    plan = await process_reply(
        event=event(),
        result=accepted(),
        policy=ReplyPolicy(
            mode="live",
            private_users=frozenset({"800001"}),
            groups=frozenset(),
            require_mention=True,
            max_per_minute=1,
        ),
        brain=MarkdownBrain(),  # type: ignore[arg-type]
        sender=sender,
    )
    assert plan.decision is ReplyDecision.SENT
    assert plan.text == "希格斯\n• 雪豹\n计算：2 x 3\nprint('ok')"
    assert sent == [plan.text]
