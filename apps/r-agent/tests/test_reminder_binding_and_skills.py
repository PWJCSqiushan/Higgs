import sqlite3
from pathlib import Path

from r_agent.reminders import ReminderStore
from r_agent.skills import (
    SkillApprovalStore,
    default_skill_registry,
    normalized_parameter_hash,
)


def create_job(
    store: ReminderStore,
    *,
    conversation: str,
    message: str,
    now: int = 1_000_000,
):
    return store.create_pending(
        owner_principal_id="owner",
        owner_qq="800001",
        content="study",
        due_at_ms=now + 10_000,
        origin_channel="qq",
        origin_surface="group" if ":group:" in conversation else "private",
        origin_conversation_id=conversation,
        source_message_id=message,
        now_ms=now,
    )


def test_generic_confirmation_is_same_conversation_and_unambiguous(tmp_path: Path) -> None:
    store = ReminderStore(tmp_path / "reminders.sqlite")
    store.initialize()
    first = create_job(store, conversation="qq:group:1", message="m1")
    create_job(store, conversation="qq:group:2", message="m2")

    assert (
        store.resolve_contextual(
            owner_principal_id="owner",
            statuses=frozenset({"pending_confirmation"}),
            conversation_id="qq:group:3",
        )
        is None
    )
    resolved = store.resolve_contextual(
        owner_principal_id="owner",
        statuses=frozenset({"pending_confirmation"}),
        conversation_id="qq:group:1",
    )
    assert resolved is not None and resolved.job_id == first.job_id

    create_job(store, conversation="qq:group:1", message="m3", now=1_001_000)
    assert (
        store.resolve_contextual(
            owner_principal_id="owner",
            statuses=frozenset({"pending_confirmation"}),
            conversation_id="qq:group:1",
        )
        is None
    )
    quoted = store.resolve_contextual(
        owner_principal_id="owner",
        statuses=frozenset({"pending_confirmation"}),
        conversation_id="qq:group:1",
        reply_message_id="m1",
    )
    assert quoted is not None and quoted.job_id == first.job_id


def test_delivery_quote_binds_ack_but_another_group_does_not(tmp_path: Path) -> None:
    store = ReminderStore(tmp_path / "reminders.sqlite")
    store.initialize()
    job = create_job(store, conversation="qq:group:1", message="request")
    store.confirm(job.job_id)
    occurrence = store.prepare_due(now_ms=job.due_at_ms)[0]
    assert occurrence.origin_surface == "group"
    assert occurrence.origin_conversation_id == "qq:group:1"
    store.finish_occurrence(occurrence.occurrence_key, state="sent", message_id="delivery-1")

    assert (
        store.resolve_contextual(
            owner_principal_id="owner",
            statuses=frozenset({"awaiting_ack"}),
            conversation_id="qq:group:2",
        )
        is None
    )
    assert (
        store.resolve_contextual(
            owner_principal_id="owner",
            statuses=frozenset({"awaiting_ack"}),
            conversation_id="qq:private:owner",
            reply_message_id="delivery-1",
        )
        is None
    )
    quoted = store.resolve_contextual(
        owner_principal_id="owner",
        statuses=frozenset({"awaiting_ack"}),
        conversation_id="qq:group:1",
        reply_message_id="delivery-1",
    )
    assert quoted is not None and quoted.job_id == job.job_id
    store.acknowledge(quoted.job_id)
    assert store.prepare_due(now_ms=job.due_at_ms + 300_000) == []


def test_offline_deferral_and_restart_idempotency(tmp_path: Path) -> None:
    path = tmp_path / "reminders.sqlite"
    store = ReminderStore(path)
    store.initialize()
    job = create_job(store, conversation="qq:private:owner", message="request")
    store.confirm(job.job_id)

    # An offline scheduler does not call prepare_due. Reopening the store preserves work.
    restarted = ReminderStore(path)
    restarted.initialize()
    occurrence = restarted.prepare_due(now_ms=job.due_at_ms)[0]
    assert restarted.prepare_due(now_ms=job.due_at_ms) == []
    assert (
        restarted.recover_stale_prepared(now_ms=job.due_at_ms + 61_000, stale_after_ms=60_000) == 1
    )
    assert restarted.prepare_due(now_ms=job.due_at_ms + 61_000) == []
    with sqlite3.connect(path) as conn:
        state = conn.execute(
            "SELECT state FROM reminder_occurrences WHERE occurrence_key=?",
            (occurrence.occurrence_key,),
        ).fetchone()[0]
    assert state == "unknown"


def test_send_states_are_terminal_and_fourth_attempt_becomes_missed(tmp_path: Path) -> None:
    store = ReminderStore(tmp_path / "reminders.sqlite")
    store.initialize()
    job = create_job(store, conversation="qq:private:owner", message="request")
    store.confirm(job.job_id)
    due = job.due_at_ms
    states = ("sent", "failed", "unknown", "sent")
    times = (due, due + 300_000, due + 900_000, due + 1_800_000)
    for expected_attempt, (state, at_ms) in enumerate(zip(states, times, strict=True)):
        occurrence = store.prepare_due(now_ms=at_ms)[0]
        assert occurrence.attempt == expected_attempt
        store.finish_occurrence(occurrence.occurrence_key, state=state)
        store.finish_occurrence(occurrence.occurrence_key, state="sent")
    assert store.prepare_due(now_ms=due + 1_861_000) == []
    assert store.get(job.job_id).status == "missed"


def test_snooze_parameter_change_requires_fresh_confirmation(tmp_path: Path) -> None:
    store = ReminderStore(tmp_path / "reminders.sqlite")
    store.initialize()
    job = create_job(store, conversation="qq:private:owner", message="request")
    confirmed = store.confirm(job.job_id)
    assert confirmed.approved_parameter_sha256
    changed = store.snooze(job.job_id, 10)
    assert changed.status == "pending_confirmation"
    assert changed.approved_parameter_sha256 is None
    reconfirmed = store.confirm(job.job_id)
    assert reconfirmed.status == "scheduled"
    assert reconfirmed.approved_parameter_sha256
    assert reconfirmed.approved_parameter_sha256 != confirmed.approved_parameter_sha256


def test_confirmed_job_parameter_tampering_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "reminders.sqlite"
    store = ReminderStore(path)
    store.initialize()
    job = create_job(store, conversation="qq:private:owner", message="request")
    store.confirm(job.job_id)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE reminder_jobs SET content='changed' WHERE job_id=?", (job.job_id,))
    assert store.prepare_due(now_ms=job.due_at_ms) == []
    assert store.get(job.job_id).status == "failed"


def test_skill_registry_is_fail_closed_and_future_skills_are_disabled() -> None:
    registry = default_skill_registry()
    assert registry.authorize_surface("reminder", caller_role="owner", surface="group")
    assert not registry.authorize_surface("reminder", caller_role="user", surface="private")
    assert not registry.authorize_surface("server_alert", caller_role="owner", surface="private")
    assert not registry.authorize_surface("missing", caller_role="owner", surface="private")


def test_skill_approval_is_bound_to_skill_and_normalized_parameters(tmp_path: Path) -> None:
    approvals = SkillApprovalStore(tmp_path / "skills.sqlite")
    approvals.initialize()
    original = {"content": "run", "due_at_ms": 12, "nested": {"b": 2, "a": 1}}
    reordered = {"nested": {"a": 1, "b": 2}, "due_at_ms": 12, "content": "run"}
    changed = {**original, "due_at_ms": 13}
    digest = approvals.approve("reminder", original, approved_by="owner", now_ms=1)
    assert digest == normalized_parameter_hash(reordered)
    assert approvals.is_approved("reminder", reordered, now_ms=2)
    assert not approvals.is_approved("reminder", changed, now_ms=2)
    assert not approvals.is_approved("server_alert", original, now_ms=2)
    assert approvals.revoke("reminder", reordered, now_ms=3)
    assert not approvals.is_approved("reminder", original, now_ms=4)


def test_skill_execution_requires_exact_approved_parameters(tmp_path: Path) -> None:
    registry = default_skill_registry()
    approvals = SkillApprovalStore(tmp_path / "skills.sqlite")
    approvals.initialize()
    parameters = {
        "content": "study",
        "due_at_ms": 123,
        "origin_conversation_id": "qq:group:1",
    }
    assert not registry.authorize_execution(
        "reminder",
        caller_role="owner",
        surface="group",
        parameters=parameters,
        approvals=approvals,
        now_ms=1,
    )
    approvals.approve("reminder", parameters, approved_by="owner", now_ms=1)
    assert registry.authorize_execution(
        "reminder",
        caller_role="owner",
        surface="group",
        parameters=parameters,
        approvals=approvals,
        now_ms=2,
    )
    assert not registry.authorize_execution(
        "reminder",
        caller_role="owner",
        surface="group",
        parameters={**parameters, "due_at_ms": 124},
        approvals=approvals,
        now_ms=2,
    )
    assert not registry.authorize_execution(
        "reminder",
        caller_role="owner",
        surface="group",
        parameters={**parameters, "unexpected": True},
        approvals=approvals,
        now_ms=2,
    )
