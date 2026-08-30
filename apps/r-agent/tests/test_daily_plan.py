from __future__ import annotations

from datetime import datetime, tzinfo
from pathlib import Path

import pytest

import r_agent.daily_plan as daily_plan
from r_agent.agenda import AgendaError, AgendaStore
from r_agent.daily_plan import DailyPlanConfig, DailyPlanService
from r_agent.events import ConversationKind, InboundEvent
from r_agent.identity import Principal
from r_agent.planner import SHANGHAI, parse_simple_plan, solve_plan
from r_agent.reminders import ReminderError, ReminderStore
from r_agent.skills import SkillApprovalStore, default_skill_registry


def event(text: str, *, group: bool = False, channel: str = "qq") -> InboundEvent:
    conversation_id = (
        "qq_official:group:1"
        if channel == "qq_official" and group
        else "qq_official:private:bot-qq:owner-openid"
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


def service(
    tmp_path: Path,
    *,
    mode: str,
    official_proactive_enabled: bool = False,
) -> DailyPlanService:
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
        official_proactive_enabled=official_proactive_enabled,
    )


def freeze_morning(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep today-plan tests independent from the CI runner's wall clock."""

    fixed = datetime(2026, 8, 9, 9, 0, tzinfo=SHANGHAI)

    class MorningDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            return fixed if tz is None else fixed.astimezone(tz)

    monkeypatch.setattr(daily_plan, "datetime", MorningDateTime)
    monkeypatch.setattr(daily_plan.time, "time", fixed.timestamp)


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
    replayed = store.confirm_exact_version(
        plan.plan_id,
        principal_id="owner",
        actor_principal_id="owner",
        parameter_sha256=plan.parameter_sha256,
    )
    assert replayed.plan_id == active.plan_id
    assert store.event_count_since("owner", "plan_confirmed", since_ms=0) == 1
    assert active.status == "active"
    scheduled = store.tasks(plan.plan_id, principal_id="owner")
    assert {task.status for task in scheduled} == {"scheduled"}
    completed = store.transition_task(
        scheduled[0].task_id,
        principal_id="owner",
        actor_principal_id="owner",
        target="completed",
    )
    repeated_completion = store.transition_task(
        scheduled[0].task_id,
        principal_id="owner",
        actor_principal_id="owner",
        target="completed",
    )
    assert repeated_completion.task_id == completed.task_id
    assert store.event_count_since("owner", "task_completed", since_ms=0) == 1


def test_agenda_draft_request_key_is_idempotent_and_conflicts_fail_closed(
    tmp_path: Path,
) -> None:
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
    request_key = "a" * 64
    first = store.create_draft(
        principal_id="owner",
        actor_principal_id="owner",
        plan_date=day,
        document=document,
        request_key=request_key,
        max_drafts_for_date=1,
    )
    replay = store.create_draft(
        principal_id="owner",
        actor_principal_id="owner",
        plan_date=day,
        document=document,
        request_key=request_key,
        max_drafts_for_date=1,
    )
    assert replay.plan_id == first.plan_id
    assert store.count_for_date("owner", day) == 1
    assert store.event_count_since("owner", "draft_created", since_ms=0) == 1
    changed = {**document, "tasks": [{**document["tasks"][0], "title": "冲突"}]}
    with pytest.raises(AgendaError, match="幂等键"):
        store.create_draft(
            principal_id="owner",
            actor_principal_id="owner",
            plan_date=day,
            document=changed,
            request_key=request_key,
            max_drafts_for_date=1,
        )


@pytest.mark.asyncio
async def test_shadow_plan_never_creates_real_reminders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    freeze_morning(monkeypatch)
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
async def test_same_plan_event_replay_returns_one_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    freeze_morning(monkeypatch)
    planner = service(tmp_path, mode="shadow")
    principal = Principal("owner", "owner")
    inbound = event("今天的待办：背单词、写代码，帮我安排")
    first = await planner.handle_event(inbound, principal)
    replay = await planner.handle_event(inbound, principal)
    assert replay == first
    assert len(planner.store.list_for_principal("owner")) == 1


@pytest.mark.asyncio
async def test_plan_add_creates_a_new_versioned_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    freeze_morning(monkeypatch)
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
async def test_live_plan_confirmation_creates_one_shot_nodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    freeze_morning(monkeypatch)
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
async def test_plan_confirmation_replay_repairs_partial_schedule_without_duplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    freeze_morning(monkeypatch)
    planner = service(tmp_path, mode="live")
    principal = Principal("owner", "owner")
    await planner.handle_event(event("今天的待办：背单词、写代码，帮我安排"), principal)
    plan = planner.store.latest_pending("owner")
    assert plan is not None
    confirmation = event(f"/higgs plan confirm {plan.plan_id[:8]}")
    original_create = planner.reminders.create_scheduled
    calls = 0

    def fail_after_first(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ReminderError("injected crash boundary")
        return original_create(**kwargs)

    monkeypatch.setattr(planner.reminders, "create_scheduled", fail_after_first)
    failed = await planner.handle_event(confirmation, principal)
    assert failed is not None and "injected crash boundary" in failed
    first_jobs = planner.reminders.list(limit=20)
    assert len(first_jobs) == 1

    monkeypatch.setattr(planner.reminders, "create_scheduled", original_create)
    recovered = await planner.handle_event(confirmation, principal)
    assert recovered is not None and "计划已确认" in recovered
    jobs = planner.reminders.list(limit=20)
    assert first_jobs[0].job_id in {job.job_id for job in jobs}
    assert len(jobs) == len({job.source_message_id for job in jobs})
    assert len(jobs) > 1
    assert planner.store.event_count_since("owner", "plan_confirmed", since_ms=0) == 1


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
async def test_official_owner_can_draft_but_live_confirmation_requires_proactive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    freeze_morning(monkeypatch)
    planner = service(tmp_path, mode="live")
    response = await planner.handle_event(
        event("今天的待办：背单词、写代码，帮我安排", channel="qq_official"),
        Principal("owner", "owner"),
    )
    assert response is not None and "今日计划" in response
    plan = planner.store.latest_pending("owner")
    assert plan is not None
    confirmation = await planner.handle_event(
        event(f"/higgs plan confirm {plan.plan_id[:8]}", channel="qq_official"),
        Principal("owner", "owner"),
    )
    assert confirmation is not None and "主动提醒尚未启用" in confirmation
    assert planner.store.get(plan.plan_id, principal_id="owner").status == ("awaiting_confirmation")
    assert planner.reminders.list() == []


@pytest.mark.asyncio
async def test_official_live_plan_confirmation_binds_all_nodes_to_owner_c2c(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    freeze_morning(monkeypatch)
    planner = service(tmp_path, mode="live", official_proactive_enabled=True)
    principal = Principal("owner", "owner")
    await planner.handle_event(
        event("今天的待办：背单词、写代码，帮我安排", channel="qq_official"),
        principal,
    )
    plan = planner.store.latest_pending("owner")
    assert plan is not None
    confirmation = await planner.handle_event(
        event(f"/higgs plan confirm {plan.plan_id[:8]}", channel="qq_official"),
        principal,
    )
    assert confirmation is not None and "计划已确认" in confirmation
    jobs = planner.reminders.list(limit=20)
    assert jobs
    assert {job.delivery_policy for job in jobs} == {"agenda_once"}
    assert {job.delivery_channel for job in jobs} == {"qq_official"}
    assert {job.delivery_surface for job in jobs} == {"private"}
    assert {job.delivery_account_id for job in jobs} == {"bot-qq"}
    assert {job.delivery_target_id for job in jobs} == {"owner-openid"}
    assert {job.delivery_binding_version for job in jobs} == {2}


@pytest.mark.asyncio
async def test_official_daily_plan_rejects_group_and_non_owner(tmp_path: Path) -> None:
    planner = service(tmp_path, mode="shadow")
    group_reply = await planner.handle_event(
        event("今天的待办：背单词、写代码", group=True, channel="qq_official"),
        Principal("owner", "owner"),
    )
    assert group_reply is not None and "只在私聊中使用" in group_reply
    user_reply = await planner.handle_event(
        event("今天的待办：背单词、写代码", channel="qq_official"),
        Principal("official-user", "user"),
    )
    assert user_reply is not None and "仅允许主人" in user_reply
    assert planner.store.list_for_principal("owner") == []
    assert planner.store.list_for_principal("official-user") == []


@pytest.mark.asyncio
async def test_map_is_not_called_before_explicit_and_unambiguous_consent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze_morning(monkeypatch)

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
