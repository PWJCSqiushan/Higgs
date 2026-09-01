from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import pytest

import r_agent.daily_plan as daily_plan
from r_agent.agenda import AgendaError, AgendaStore
from r_agent.daily_plan import DailyPlanConfig, DailyPlanService
from r_agent.events import ConversationKind, InboundEvent
from r_agent.identity import IdentityStore, Principal
from r_agent.phase2_cli import _official_reminder_target
from r_agent.planner import SHANGHAI
from r_agent.reminders import DueOccurrence, ReminderError, ReminderJob, ReminderStore
from r_agent.skills import SkillApprovalStore, default_skill_registry
from r_agent.task_scope import ordinary_user_task_target
from r_agent.transport import DeliveryTarget


def _target(user: str = "member-openid", bot: str = "bot-1") -> DeliveryTarget:
    return DeliveryTarget("qq_official", bot, user, "private")


def _event(
    text: str,
    *,
    sender: str = "member-openid",
    bot: str = "bot-1",
    group: bool = False,
    message_id: str = "message-1",
) -> InboundEvent:
    surface = "group" if group else "private"
    conversation = f"qq_official:{surface}:{bot}:{'group-1' if group else sender}"
    return InboundEvent(
        channel="qq_official",
        account_id=bot,
        sender_id=sender,
        message_id=message_id,
        occurred_at_ms=int(time.time() * 1000),
        conversation_kind=ConversationKind.GROUP if group else ConversationKind.PRIVATE,
        conversation_id=conversation,
        group_id="group-1" if group else None,
        text=text,
        mentioned=group,
    )


def test_delivery_target_is_canonical_and_event_bound() -> None:
    event = _event("hello")
    target = ordinary_user_task_target(event)
    assert target == _target()
    assert target.conversation_id == event.conversation_id
    assert target.matches_event(event)
    assert not target.matches_event(_event("hello", bot="other-bot"))
    with pytest.raises(ValueError):
        DeliveryTarget("qq_official", "bot:bad", "member", "private")


def test_official_proactive_target_separates_owner_and_allowlisted_ordinary_user() -> None:
    ordinary = DueOccurrence(
        occurrence_key="job:ordinary:0",
        job_id="job-ordinary",
        owner_qq="ordinary-openid",
        content="study",
        attempt=0,
        scheduled_at_ms=1,
        origin_channel="qq_official",
        origin_surface="private",
        origin_conversation_id="qq_official:private:bot-1:ordinary-openid",
        delivery_channel="qq_official",
        delivery_surface="private",
        delivery_account_id="bot-1",
        delivery_target_id="ordinary-openid",
    )
    assert (
        _official_reminder_target(
            ordinary,
            owner_openid="owner-openid",
            account_id="bot-1",
        )
        is None
    )

    owner = DueOccurrence(
        occurrence_key="job:owner:0",
        job_id="job-owner",
        owner_qq="owner-openid",
        content="owner task",
        attempt=0,
        scheduled_at_ms=1,
        origin_channel="qq_official",
        origin_surface="private",
        origin_conversation_id="qq_official:private:bot-1:owner-openid",
        delivery_channel="qq_official",
        delivery_surface="private",
        delivery_account_id="bot-1",
        delivery_target_id="owner-openid",
    )
    assert (
        _official_reminder_target(
            owner,
            owner_openid="owner-openid",
            account_id="bot-1",
            allowed_private_openids=frozenset({"owner-openid", "ordinary-openid"}),
            ordinary_proactive_enabled=True,
        )
        is None
    )
    assert (
        _official_reminder_target(
            owner,
            owner_openid="owner-openid",
            account_id="bot-1",
            owner_proactive_enabled=True,
        )
        is not None
    )
    target = _official_reminder_target(
        ordinary,
        owner_openid="owner-openid",
        account_id="bot-1",
        allowed_private_openids=frozenset({"owner-openid", "ordinary-openid"}),
        ordinary_proactive_enabled=True,
    )
    assert target is not None
    assert target.conversation_id == "qq_official:private:bot-1:ordinary-openid"
    assert (
        _official_reminder_target(
            ordinary,
            owner_openid="owner-openid",
            account_id="other-bot",
            allowed_private_openids=frozenset({"ordinary-openid"}),
            ordinary_proactive_enabled=True,
        )
        is None
    )
    assert (
        _official_reminder_target(
            ordinary,
            owner_openid="owner-openid",
            account_id="bot-1",
            allowed_private_openids=frozenset({"ordinary-openid"}),
            ordinary_proactive_enabled=False,
        )
        is None
    )


def test_reminders_scope_every_short_id_operation_to_principal_and_target(
    tmp_path: Path,
) -> None:
    store = ReminderStore(tmp_path / "reminders.sqlite")
    store.initialize()
    now = int(time.time() * 1000)
    first = store.create_pending(
        owner_principal_id="principal-a",
        owner_qq="member-a",
        content="private A",
        due_at_ms=now + 10_000,
        origin_channel="qq_official",
        origin_surface="private",
        origin_conversation_id="qq_official:private:bot-1:member-a",
        delivery_target=_target("member-a"),
        source_message_id="message-a",
        now_ms=now,
    )
    second = store.create_pending(
        owner_principal_id="principal-b",
        owner_qq="member-b",
        content="private B",
        due_at_ms=now + 10_000,
        origin_channel="qq_official",
        origin_surface="private",
        origin_conversation_id="qq_official:private:bot-1:member-b",
        delivery_target=_target("member-b"),
        source_message_id="message-b",
        now_ms=now,
    )
    assert (
        store.get_for_principal(
            first.job_id,
            principal_id="principal-a",
            delivery_target=_target("member-a"),
        ).content
        == "private A"
    )
    with pytest.raises(ReminderError, match="当前会话"):
        store.get_for_principal(
            first.job_id,
            principal_id="principal-b",
            delivery_target=_target("member-b"),
        )
    with pytest.raises(ReminderError, match="当前会话"):
        store.confirm_for_principal(
            first.job_id,
            principal_id="principal-b",
            delivery_target=_target("member-b"),
        )
    confirmed = store.confirm_for_principal(
        first.job_id,
        principal_id="principal-a",
        delivery_target=_target("member-a"),
    )
    assert confirmed.status == "scheduled"
    assert store.list_for_principal("principal-a", delivery_target=_target("member-a")) == [
        confirmed
    ]
    assert store.list_for_principal("principal-b", delivery_target=_target("member-b")) == [second]


def test_scoped_reminder_confirm_cancel_snooze_ack_and_legacy_owner_paths(
    tmp_path: Path,
) -> None:
    store = ReminderStore(tmp_path / "reminders.sqlite")
    store.initialize()
    now = int(time.time() * 1000)
    target = _target("member-a")

    def create(content: str, source: str) -> ReminderJob:
        return store.create_pending(
            owner_principal_id="principal-a",
            owner_qq="member-a",
            content=content,
            due_at_ms=now + 10_000,
            origin_channel="qq_official",
            origin_surface="private",
            origin_conversation_id=target.conversation_id,
            delivery_target=target,
            source_message_id=source,
            now_ms=now,
        )

    first = create("first", "message-first")
    scheduled = store.confirm_for_principal(
        first.job_id[:8], principal_id="principal-a", delivery_target=target
    )
    assert scheduled.status == "scheduled"
    snoozed = store.snooze_for_principal(
        first.job_id[:8], 1, principal_id="principal-a", delivery_target=target
    )
    assert snoozed.status == "pending_confirmation"
    cancelled = store.cancel_for_principal(
        first.job_id[:8], principal_id="principal-a", delivery_target=target
    )
    assert cancelled.status == "cancelled"

    second = create("second", "message-second")
    assert (
        store.confirm_for_principal(
            second.job_id[:8], principal_id="principal-a", delivery_target=target
        ).status
        == "scheduled"
    )
    assert (
        store.acknowledge_for_principal(
            second.job_id[:8], principal_id="principal-a", delivery_target=target
        ).status
        == "completed"
    )
    with pytest.raises(ReminderError, match="当前会话"):
        store.cancel_for_principal(
            first.job_id[:8],
            principal_id="principal-a",
            delivery_target=_target("member-a", bot="other-bot"),
        )
    with pytest.raises(ReminderError, match="范围参数不完整"):
        store.cancel_by_source(
            source_kind="user",
            source_id="source",
            principal_id="principal-a",
        )

    legacy = store.create_pending(
        owner_principal_id="owner-principal",
        owner_qq="10001",
        content="legacy",
        due_at_ms=now + 10_000,
        origin_channel="qq",
        origin_surface="private",
        origin_conversation_id="qq:private:legacy-bot:10001",
        source_message_id="legacy-message",
        now_ms=now,
    )
    assert legacy.delivery_channel == "qq"
    assert store.confirm(legacy.job_id[:8]).status == "scheduled"


def test_reminder_quota_is_transactional_and_idempotent(tmp_path: Path) -> None:
    store = ReminderStore(tmp_path / "reminders.sqlite")
    store.initialize()
    now = int(time.time() * 1000)
    kwargs = dict(
        owner_principal_id="principal-a",
        owner_qq="member-a",
        content="one",
        due_at_ms=now + 10_000,
        origin_channel="qq_official",
        origin_surface="private",
        origin_conversation_id="qq_official:private:bot-1:member-a",
        delivery_target=_target("member-a"),
        source_message_id="same-message",
        max_active_for_principal=1,
        max_created_for_principal_since_ms=now - 1,
        max_created_for_principal=1,
        now_ms=now,
    )
    first = store.create_pending(**kwargs)
    assert store.create_pending(**kwargs).job_id == first.job_id
    with pytest.raises(ReminderError, match="活动提醒"):
        store.create_pending(
            **{
                **kwargs,
                "content": "two",
                "source_message_id": "another-message",
            }
        )


@pytest.mark.asyncio
async def test_ordinary_plan_has_target_scope_and_shadow_never_schedules(
    tmp_path: Path,
) -> None:
    agenda = AgendaStore(tmp_path / "agenda.sqlite")
    agenda.initialize()
    reminders = ReminderStore(tmp_path / "reminders.sqlite")
    reminders.initialize()
    approvals = SkillApprovalStore(tmp_path / "skills.sqlite")
    approvals.initialize()
    service = DailyPlanService(
        store=agenda,
        reminders=reminders,
        registry=default_skill_registry(),
        approvals=approvals,
        config=DailyPlanConfig(
            ordinary_mode="shadow",
            ordinary_proactive_enabled=False,
        ),
    )
    principal = Principal("principal-a", "user")
    inbound = _event("今天的待办：背单词、写代码，帮我安排")
    response = await service.handle_event(inbound, principal)
    assert response is not None and "SHADOW" in response
    plan = agenda.latest_pending(
        principal.principal_id,
        delivery_target=_target(),
    )
    assert plan is not None and plan.delivery_target == _target()
    confirmation = await service.handle_event(
        _event(f"/higgs plan confirm {plan.plan_id[:8]}", message_id="confirm-1"),
        principal,
    )
    assert confirmation is not None and "不会激活" in confirmation
    assert reminders.list() == []
    with pytest.raises(AgendaError):
        agenda.get_for_principal(
            plan.plan_id,
            principal_id=principal.principal_id,
            delivery_target=_target(bot="other-bot"),
        )


@pytest.mark.asyncio
async def test_ordinary_live_plan_requires_proactive_gate_and_binds_each_reminder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_morning = datetime(2026, 8, 9, 9, 0, tzinfo=SHANGHAI)
    monkeypatch.setattr(daily_plan.time, "time", fixed_morning.timestamp)
    agenda = AgendaStore(tmp_path / "agenda.sqlite")
    agenda.initialize()
    reminders = ReminderStore(tmp_path / "reminders.sqlite")
    reminders.initialize()
    approvals = SkillApprovalStore(tmp_path / "skills.sqlite")
    approvals.initialize()
    principal = Principal("principal-a", "user")
    inbound = _event("今天的待办：背单词、写代码，帮我安排")
    target = _target()

    blocked_service = DailyPlanService(
        store=agenda,
        reminders=reminders,
        registry=default_skill_registry(),
        approvals=approvals,
        config=DailyPlanConfig(
            ordinary_mode="live",
            ordinary_proactive_enabled=False,
        ),
    )
    await blocked_service.handle_event(inbound, principal)
    blocked_plan = agenda.latest_pending(principal.principal_id, delivery_target=target)
    assert blocked_plan is not None
    blocked_reply = await blocked_service.handle_event(
        _event(f"/higgs plan confirm {blocked_plan.plan_id[:8]}", message_id="blocked-confirm"),
        principal,
    )
    assert blocked_reply is not None and "主动提醒尚未启用" in blocked_reply
    assert reminders.list_for_principal(principal.principal_id, delivery_target=target) == []

    enabled_agenda = AgendaStore(tmp_path / "enabled-agenda.sqlite")
    enabled_agenda.initialize()
    enabled_reminders = ReminderStore(tmp_path / "enabled-reminders.sqlite")
    enabled_reminders.initialize()
    enabled_approvals = SkillApprovalStore(tmp_path / "enabled-skills.sqlite")
    enabled_approvals.initialize()
    enabled_service = DailyPlanService(
        store=enabled_agenda,
        reminders=enabled_reminders,
        registry=default_skill_registry(),
        approvals=enabled_approvals,
        config=DailyPlanConfig(
            ordinary_mode="live",
            ordinary_proactive_enabled=True,
        ),
    )
    await enabled_service.handle_event(inbound, principal)
    plan = enabled_agenda.latest_pending(principal.principal_id, delivery_target=target)
    assert plan is not None
    reply = await enabled_service.handle_event(
        _event(f"/higgs plan confirm {plan.plan_id[:8]}", message_id="enabled-confirm"),
        principal,
    )
    assert reply is not None and "计划已确认" in reply
    jobs = enabled_reminders.list_for_principal(principal.principal_id, delivery_target=target)
    assert jobs and all(job.delivery_target == target for job in jobs)


@pytest.mark.asyncio
async def test_ordinary_reminder_requires_official_private_and_keeps_proactive_separate(
    tmp_path: Path,
) -> None:
    reminders = ReminderStore(tmp_path / "reminders.sqlite")
    reminders.initialize()
    identities = IdentityStore(
        tmp_path / "identity.sqlite",
        owner_qq="owner-qq",
        account_scoped_official_enabled=True,
    )
    identities.initialize()
    from r_agent.phase2_reply import PersonaBrain

    brain = PersonaBrain(
        None,
        "test persona",
        identities=identities,
        context_builder=object(),
        reminders=reminders,
        ordinary_task_mode="live",
        ordinary_proactive_enabled=False,
    )
    inbound = _event("10分钟后提醒我喝水", message_id="reminder-1")
    response = await brain.draft(inbound)
    assert response.startswith("请核对后回复")
    principal = identities.resolve_event(inbound)
    target = _target()
    job = reminders.list_for_principal(principal.principal_id, delivery_target=target)[0]
    assert job.status == "pending_confirmation"
    confirmation = await brain.draft(
        _event("/higgs remind confirm " + job.job_id[:8], message_id="confirm-2")
    )
    assert "主动投递尚未开启" in confirmation
    assert (
        reminders.get_for_principal(
            job.job_id,
            principal_id=principal.principal_id,
            delivery_target=target,
        ).status
        == "pending_confirmation"
    )
    group = await brain.draft(_event("10分钟后提醒我开会", group=True, message_id="group-reminder"))
    assert "只允许在当前官方 QQ 私聊" in group
