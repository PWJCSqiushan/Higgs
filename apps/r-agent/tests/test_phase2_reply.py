from r_agent.access import IngressDecision
from r_agent.events import ConversationKind, InboundEvent
from r_agent.ingest import IngestResult
from r_agent.model_client import ModelError
from r_agent.phase2_cli import process_reply
from r_agent.phase2_outbound import OutboundError
from r_agent.phase2_reply import PersonaBrain, ReplyDecision, ReplyPolicy


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

    async def sender(item: InboundEvent, text: str) -> None:
        sent.append(text)

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
