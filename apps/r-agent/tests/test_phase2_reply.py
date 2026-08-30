import time
from types import SimpleNamespace

from r_agent.access import IngressDecision
from r_agent.events import ConversationKind, InboundEvent
from r_agent.identity import Principal
from r_agent.ingest import IngestResult
from r_agent.model_client import ModelError
from r_agent.phase2_cli import process_reply
from r_agent.phase2_outbound import OutboundError
from r_agent.phase2_reply import PersonaBrain, ReplyDecision, ReplyPolicy
from r_agent.reminders import ReminderStore
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


class _OfficialIdentities:
    def resolve(self, channel: str, sender_id: str) -> Principal:
        return Principal("owner-principal", "owner")


class _ForbiddenFeature:
    def __getattr__(self, name: str) -> object:
        raise AssertionError("official MVP must not enter a mutating feature")


class _OwnerCommands:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.governed_calls: list[tuple[str, str]] = []

    def handle(self, text: str, *, actor: Principal, surface: str) -> str:
        self.calls.append(text)
        return "状态正常"

    @staticmethod
    def is_governed_mutation(text: str) -> bool:
        return text.strip().casefold() in {"/higgs enable", "/higgs disable"}

    async def handle_governed(
        self,
        text: str,
        *,
        actor: Principal,
        surface: str,
        idempotency_key: str,
    ) -> str:
        assert actor.role == "owner"
        assert surface == "private"
        assert len(idempotency_key) == 64
        self.governed_calls.append((text, idempotency_key))
        return "变更已治理"


class _DailyPlans:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def handle_event(self, item: InboundEvent, actor: Principal) -> str:
        assert actor.role == "owner"
        self.calls.append(item.text)
        return "计划已受理"


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


async def test_official_owner_private_commands_use_an_explicit_allowlist() -> None:
    commands = _OwnerCommands()
    brain = PersonaBrain(
        None,
        "test",
        identities=_OfficialIdentities(),  # type: ignore[arg-type]
        context_builder=SimpleNamespace(),  # type: ignore[arg-type]
        owner_commands=commands,  # type: ignore[arg-type]
        reminders=_ForbiddenFeature(),  # type: ignore[arg-type]
        daily_plans=_ForbiddenFeature(),  # type: ignore[arg-type]
    )
    base = event(text="/higgs status")
    official = InboundEvent(
        channel="qq_official",
        account_id=base.account_id,
        sender_id=base.sender_id,
        message_id=base.message_id,
        occurred_at_ms=base.occurred_at_ms,
        conversation_kind=base.conversation_kind,
        conversation_id="qq_official:private:bot:owner",
        group_id=None,
        text=base.text,
        mentioned=False,
    )

    assert await brain.draft(official) == "状态正常"
    assert commands.calls == ["/higgs status"]

    for index, allowed_text in enumerate(
        ("/higgs help", "/higgs server status", "/higgs memory stats", "/higgs remind list"),
        start=2,
    ):
        allowed = InboundEvent(
            channel=official.channel,
            account_id=official.account_id,
            sender_id=official.sender_id,
            message_id=str(index),
            occurred_at_ms=official.occurred_at_ms,
            conversation_kind=official.conversation_kind,
            conversation_id=official.conversation_id,
            group_id=None,
            text=allowed_text,
            mentioned=False,
        )
        assert await brain.draft(allowed) == "状态正常"

    governed = InboundEvent(
        channel=official.channel,
        account_id=official.account_id,
        sender_id=official.sender_id,
        message_id="20",
        occurred_at_ms=official.occurred_at_ms,
        conversation_kind=official.conversation_kind,
        conversation_id=official.conversation_id,
        group_id=None,
        text="/higgs enable",
        mentioned=False,
    )
    assert await brain.draft(governed) == "变更已治理"
    assert len(commands.governed_calls) == 1

    blocked = InboundEvent(
        channel=official.channel,
        account_id=official.account_id,
        sender_id=official.sender_id,
        message_id="21",
        occurred_at_ms=official.occurred_at_ms,
        conversation_kind=official.conversation_kind,
        conversation_id=official.conversation_id,
        group_id=None,
        text="/higgs whitelist group add 700001",
        mentioned=False,
    )
    assert await brain.draft(blocked) == "该主人命令尚未迁移到官方 QQ 安全边界。"
    assert commands.calls == [
        "/higgs status",
        "/higgs help",
        "/higgs server status",
        "/higgs memory stats",
        "/higgs remind list",
    ]


async def test_unrelated_official_dialogue_skips_reminder_mutations() -> None:
    brain = PersonaBrain(
        None,
        "test",
        identities=_OfficialIdentities(),  # type: ignore[arg-type]
        context_builder=SimpleNamespace(),  # type: ignore[arg-type]
        reminders=_ForbiddenFeature(),  # type: ignore[arg-type]
    )
    base = event(text="明天提醒我写计划")
    official = InboundEvent(
        channel="qq_official",
        account_id=base.account_id,
        sender_id=base.sender_id,
        message_id=base.message_id,
        occurred_at_ms=base.occurred_at_ms,
        conversation_kind=base.conversation_kind,
        conversation_id="qq_official:private:bot:owner",
        group_id=None,
        text=base.text,
        mentioned=False,
    )

    assert (
        await brain.draft(official) == "我已收到。当前处于受控测试阶段，请告诉我需要协助处理什么。"
    )


async def test_official_owner_private_plan_command_and_natural_intent_use_daily_service() -> None:
    plans = _DailyPlans()
    brain = PersonaBrain(
        None,
        "test",
        identities=_OfficialIdentities(),  # type: ignore[arg-type]
        context_builder=SimpleNamespace(),  # type: ignore[arg-type]
        owner_commands=_ForbiddenFeature(),  # type: ignore[arg-type]
        daily_plans=plans,  # type: ignore[arg-type]
    )
    base = event(text="/higgs plan today")
    official = InboundEvent(
        channel="qq_official",
        account_id="official-bot-id",
        sender_id="owner-openid",
        message_id=base.message_id,
        occurred_at_ms=base.occurred_at_ms,
        conversation_kind=ConversationKind.PRIVATE,
        conversation_id="qq_official:private:official-bot-id:owner-openid",
        group_id=None,
        text=base.text,
        mentioned=False,
    )
    assert await brain.draft(official) == "计划已受理"
    natural = InboundEvent(
        channel=official.channel,
        account_id=official.account_id,
        sender_id=official.sender_id,
        message_id="natural-plan",
        occurred_at_ms=official.occurred_at_ms,
        conversation_kind=official.conversation_kind,
        conversation_id=official.conversation_id,
        group_id=None,
        text="今天的待办：背单词、写代码，帮我安排",
        mentioned=False,
    )
    assert await brain.draft(natural) == "计划已受理"
    assert plans.calls == ["/higgs plan today", natural.text]


async def test_official_owner_can_create_only_explicit_bound_private_reminder(tmp_path) -> None:
    reminders = ReminderStore(tmp_path / "reminders.sqlite")
    reminders.initialize()
    brain = PersonaBrain(
        None,
        "test",
        identities=_OfficialIdentities(),  # type: ignore[arg-type]
        context_builder=SimpleNamespace(),  # type: ignore[arg-type]
        reminders=reminders,
        official_proactive_enabled=True,
    )
    base = event(text="5分钟后提醒我喝水")
    official = InboundEvent(
        channel="qq_official",
        account_id="official-bot-id",
        sender_id="owner-openid",
        message_id=base.message_id,
        occurred_at_ms=int(time.time() * 1000),
        conversation_kind=ConversationKind.PRIVATE,
        conversation_id="qq_official:private:official-bot-id:owner-openid",
        group_id=None,
        text=base.text,
        mentioned=False,
    )

    assert "请核对后回复" in await brain.draft(official)
    job = reminders.list()[0]
    assert job.delivery_channel == "qq_official"
    assert job.delivery_surface == "private"
    assert job.delivery_account_id == "official-bot-id"
    assert job.delivery_target_id == "owner-openid"

    replay = await brain.draft(official)
    assert "请核对后回复" in replay
    assert len(reminders.list()) == 1


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
            idempotency_key: str | None = None,
        ) -> SimpleNamespace:
            assert not is_owner
            assert idempotency_key is None
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
