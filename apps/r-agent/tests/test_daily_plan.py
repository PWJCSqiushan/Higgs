from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from r_agent.agenda import AgendaError, AgendaStore
from r_agent.daily_plan import DailyPlanConfig, DailyPlanService
from r_agent.events import ConversationKind, InboundEvent
from r_agent.identity import Principal
from r_agent.planner import SHANGHAI, parse_simple_plan, solve_plan
from r_agent.reminders import ReminderStore
from r_agent.skills import SkillApprovalStore, default_skill_registry


def event(text: str, *, group: bool = False, channel: str = "qq") -> InboundEvent:
    conversation_id = (
        "qq_official:group:1"
        if channel == "qq_official" and group
        else "qq_official:private:bot:owner-openid"
        if channel == "qq_official"
        else "qq:group:1"
        if group
        else "qq:private:owner:owner-qq"
    )
    return InboundEvent(
        channel=channel,
        account_id="bot-qq",
        sender_id="owner-openid" if channel == "qq_official" else "owner-qq",
        message_id=f"message-{abs(hash(text))}",
        occurred_at_ms=int(datetime.now(SHANGHAI).timestamp() * 1000),
        conversation_kind=ConversationKind.GROUP if group else ConversationKind.PRIVATE,
        conversation_id=conversation_id,
        group_id="1" if group else None,
        text=text,
        mentioned=group,
    )


def service(tmp_path: Path, *, mode: str) -> DailyPlanService:
    agenda = AgendaStore(tmp_path / "agenda.sqlite")
    agenda.initialize()
    reminders = ReminderStore(tmp_path / "reminders.sqlite")
    reminders.initialize()
    approvals = SkillApprovalStore(tmp_path / "skills.sqlite")
    approvals.initialize()
    return DailyPlanService(
        store=agenda,
        reminders=reminders,
        registry=default_skill_registry(),
        approvals=approvals,
        config=DailyPlanConfig(mode=mode),
    )


def test_parser_orders_soft_preferences_and_keeps_deadline() -> None:
    now = datetime(2026, 8, 9, 14, 0, tzinfo=SHANGHAI)
    day, tasks = parse_simple_plan(
        "今天要取快递、买一桶水、去菜市场买菜，18:20前取到快递，帮我安排",
        now=now,
    )
    result = solve_plan(tasks, plan_day=day, start_at=now)
    assert len(result.tasks) == 3
    assert any(task.deadline_ms is not None for task in result.tasks)
    assert result.tasks[-1].title.find("水") >= 0


def test_agenda_store_isolates_principals_and_binds_confirmation(tmp_path: Path) -> None:
    store = AgendaStore(tmp_path / "agenda.sqlite")
    store.initialize()
    day, tasks = parse_simple_plan(
        "今天的待办：背单词、写代码，帮我安排",
        now=datetime(2026, 8, 9, 9, 0, tzinfo=SHANGHAI),
    )
    result = solve_plan(
        tasks,
        plan_day=day,
        start_at=datetime(2026, 8, 9, 9, 0, tzinfo=SHANGHAI),
    )
    document = {
        "plan_date": day.isoformat(),
        "tasks": [task.as_document() for task in result.tasks],
    }
    plan = store.create_draft(
        principal_id="owner",
        actor_principal_id="owner",
        plan_date=day,
        document=document,
    )
    with pytest.raises(AgendaError):
        store.get(plan.plan_id, principal_id="someone-else")
    with pytest.raises(AgendaError):
        store.confirm_exact_version(
            plan.plan_id,
            principal_id="owner",
            actor_principal_id="owner",
            parameter_sha256="wrong",
        )
    active = store.confirm_exact_version(
        plan.plan_id,
        principal_id="owner",
        actor_principal_id="owner",
        parameter_sha256=plan.parameter_sha256,
    )
    assert active.status == "active"
    assert {task.status for task in store.tasks(plan.plan_id, principal_id="owner")} == {
        "scheduled"
    }


@pytest.mark.asyncio
async def test_shadow_plan_never_creates_real_reminders(tmp_path: Path) -> None:
    planner = service(tmp_path, mode="shadow")
    principal = Principal("owner", "owner")
    response = await planner.handle_event(event("今天的待办：背单词、写代码，帮我安排"), principal)
    assert response is not None and "SHADOW" in response
    plan = planner.store.latest_pending(principal.principal_id)
    assert plan is not None and plan.status == "awaiting_confirmation"
    confirmation = await planner.handle_event(
        event(f"/higgs plan confirm {plan.plan_id[:8]}"), principal
    )
    assert confirmation is not None and "不会激活计划" in confirmation
    assert planner.store.get(plan.plan_id, principal_id="owner").status == ("awaiting_confirmation")
    assert planner.reminders.list() == []


@pytest.mark.asyncio
async def test_plan_add_creates_a_new_versioned_draft(tmp_path: Path) -> None:
    planner = service(tmp_path, mode="shadow")
    principal = Principal("owner", "owner")
    await planner.handle_event(event("今天的待办：背单词、写代码，帮我安排"), principal)
    original = planner.store.latest_pending(principal.principal_id)
    assert original is not None
    response = await planner.handle_event(event("/higgs plan add 整理照片"), principal)
    assert response is not None and "新草案" in response
    replacement = planner.store.latest_pending(principal.principal_id)
    assert replacement is not None and replacement.plan_id != original.plan_id
    assert replacement.parent_plan_id == original.plan_id
    assert planner.store.get(original.plan_id, principal_id="owner").status == "superseded"
    assert len(planner.store.tasks(replacement.plan_id, principal_id="owner")) == 3


@pytest.mark.asyncio
async def test_live_plan_confirmation_creates_one_shot_nodes(tmp_path: Path) -> None:
    planner = service(tmp_path, mode="live")
    principal = Principal("owner", "owner")
    response = await planner.handle_event(event("今天的待办：背单词、写代码，帮我安排"), principal)
    assert response is not None
    plan = planner.store.latest_pending(principal.principal_id)
    assert plan is not None
    confirmation = await planner.handle_event(
        event(f"/higgs plan confirm {plan.plan_id[:8]}"), principal
    )
    assert confirmation is not None and "计划已确认" in confirmation
    jobs = planner.reminders.list(limit=20)
    assert jobs
    assert {job.delivery_policy for job in jobs} == {"agenda_once"}
    assert all(job.status == "scheduled" for job in jobs)


@pytest.mark.asyncio
async def test_group_and_untrusted_identity_cannot_create_plan(tmp_path: Path) -> None:
    planner = service(tmp_path, mode="shadow")
    group_reply = await planner.handle_event(
        event("今天的待办：背单词、写代码", group=True),
        Principal("owner", "owner"),
    )
    assert group_reply is not None and "只在私聊中使用" in group_reply
    denied = await planner.handle_event(
        event("今天的待办：背单词、写代码"),
        Principal("pending", "pending"),
    )
    assert denied is not None and "不能使用" in denied


@pytest.mark.asyncio
async def test_official_channel_cannot_create_plan_or_reminders(tmp_path: Path) -> None:
    planner = service(tmp_path, mode="live")
    response = await planner.handle_event(
        event("今天的待办：背单词、写代码，帮我安排", channel="qq_official"),
        Principal("owner", "owner"),
    )
    assert response is not None and "官方 QQ 通道" in response
    assert planner.store.list_for_principal("owner") == []
    assert planner.reminders.list() == []


@pytest.mark.asyncio
async def test_map_is_not_called_before_explicit_and_unambiguous_consent(
    tmp_path: Path,
) -> None:
    class FakeAmap:
        calls = 0

        async def geocode_candidates(self, address: str):
            self.calls += 1
            raise AssertionError(f"unexpected map call for {address}")

    planner = service(tmp_path, mode="shadow")
    fake = FakeAmap()
    planner.amap = fake
    principal = Principal("owner", "owner")
    await planner.handle_event(event("今天要取快递、买一桶水、去菜市场买菜，帮我安排"), principal)
    assert fake.calls == 0
    plan = planner.store.latest_pending(principal.principal_id)
    assert plan is not None and plan.status == "awaiting_map_consent"
    response = await planner.handle_event(
        event(f"/higgs plan map-consent {plan.plan_id[:8]}"), principal
    )
    assert response is not None and "地点仍有歧义" in response
    assert fake.calls == 0


def test_agenda_once_reminder_is_completed_after_single_send(tmp_path: Path) -> None:
    store = ReminderStore(tmp_path / "reminders.sqlite")
    store.initialize()
    now = 2_000_000_000_000
    job = store.create_scheduled(
        owner_principal_id="owner",
        owner_qq="owner-qq",
        content="节点提醒",
        due_at_ms=now + 10_000,
        origin_conversation_id="qq:private:owner:owner-qq",
        source_kind="agenda_task",
        source_id="task-1",
        expires_at_ms=now + 60_000,
        now_ms=now,
    )
    due = store.prepare_due(now_ms=now + 10_000)
    assert len(due) == 1 and due[0].delivery_policy == "agenda_once"
    store.finish_occurrence(due[0].occurrence_key, state="sent", message_id="1")
    assert store.get(job.job_id).status == "completed"
    assert store.prepare_due(now_ms=now + 40_000) == []


def test_agenda_once_can_be_caught_up_until_its_expiry(tmp_path: Path) -> None:
    store = ReminderStore(tmp_path / "reminders.sqlite")
    store.initialize()
    now = 2_000_000_000_000
    job = store.create_scheduled(
        owner_principal_id="owner",
        owner_qq="owner-qq",
        content="仍然有意义的节点",
        due_at_ms=now + 10_000,
        origin_conversation_id="qq:private:owner:owner-qq",
        source_kind="agenda_task",
        source_id="task-2",
        expires_at_ms=now + 30 * 60_000,
        now_ms=now,
    )
    assert len(store.prepare_due(now_ms=now + 10 * 60_000)) == 1
    store.finish_occurrence(f"{job.job_id}:0", state="sent", message_id="2")
    assert store.get(job.job_id).status == "completed"
