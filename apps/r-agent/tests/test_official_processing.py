from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from r_agent.access import IngressDecision
from r_agent.conversation import ConversationStore
from r_agent.events import ConversationKind, InboundEvent
from r_agent.ingest import IngestResult
from r_agent.official_processing import OfficialDurableProcessor, OfficialProcessingStore
from r_agent.phase2_reply import PreparedReply, ReplyAudit, ReplyDecision, ReplyPlan


def event(
    message_id: str,
    text: str,
    *,
    occurred_at_ms: int = 1_000,
    sender_id: str = "owner-openid",
    group_id: str | None = None,
) -> InboundEvent:
    kind = ConversationKind.GROUP if group_id else ConversationKind.PRIVATE
    target = group_id or sender_id
    return InboundEvent(
        channel="qq_official",
        account_id="bot-openid",
        sender_id=sender_id,
        message_id=message_id,
        occurred_at_ms=occurred_at_ms,
        conversation_kind=kind,
        conversation_id=f"qq_official:{kind.value}:bot-openid:{target}",
        group_id=group_id,
        text=text,
        mentioned=group_id is not None,
    )


def accepted(*, stored: bool = True, duplicate: bool = False) -> IngestResult:
    return IngestResult(IngressDecision.ACCEPT, stored=stored, duplicate=duplicate)


def test_enqueue_is_durable_deduplicated_and_quiet_window_merged(tmp_path: Path) -> None:
    store = OfficialProcessingStore(tmp_path / "official_processing.sqlite")
    store.initialize(now_ms=1_000)

    assert store.enqueue(event("m1", "第一段"), accepted(), quiet_seconds=1, now_ms=1_000)
    assert store.enqueue(
        event("m2", "第二段", occurred_at_ms=1_100),
        accepted(),
        quiet_seconds=1,
        now_ms=1_200,
    )
    assert not store.enqueue(
        event("m2", "第二段", occurred_at_ms=1_100),
        accepted(stored=False, duplicate=True),
        quiet_seconds=1,
        now_ms=1_300,
    )

    assert store.claim_ready(now_ms=2_199) is None
    item = store.claim_ready(now_ms=2_200)
    assert item is not None
    assert item.state == "preparing"
    assert item.event.message_id == "m2"
    assert item.event.text == "第一段\n第二段"
    assert item.result.stored


def test_journal_duplicate_without_queue_record_is_recovered(tmp_path: Path) -> None:
    store = OfficialProcessingStore(tmp_path / "official_processing.sqlite")
    store.initialize(now_ms=1_000)

    assert store.enqueue(
        event("journal-only", "恢复"),
        accepted(stored=False, duplicate=True),
        quiet_seconds=0.5,
        now_ms=1_000,
    )
    item = store.claim_ready(now_ms=1_500)
    assert item is not None
    assert item.result.stored
    assert item.result.duplicate


def test_group_debounce_is_isolated_per_sender(tmp_path: Path) -> None:
    store = OfficialProcessingStore(tmp_path / "official_processing.sqlite")
    store.initialize(now_ms=1_000)
    store.enqueue(
        event("a1", "甲一", sender_id="member-a", group_id="group"),
        accepted(),
        quiet_seconds=1,
        now_ms=1_000,
    )
    store.enqueue(
        event("a2", "甲二", sender_id="member-a", group_id="group"),
        accepted(),
        quiet_seconds=1,
        now_ms=1_100,
    )
    store.enqueue(
        event("b1", "乙", sender_id="member-b", group_id="group"),
        accepted(),
        quiet_seconds=1,
        now_ms=1_100,
    )

    first = store.claim_ready(now_ms=2_100)
    second = store.claim_ready(now_ms=2_100)
    assert first is not None and second is not None
    texts = {first.event.sender_id: first.event.text, second.event.sender_id: second.event.text}
    assert texts == {"member-a": "甲一\n甲二", "member-b": "乙"}


def test_restart_recovers_preparing_and_sending_without_changing_text(tmp_path: Path) -> None:
    path = tmp_path / "official_processing.sqlite"
    store = OfficialProcessingStore(path)
    store.initialize(now_ms=1_000)
    store.enqueue(event("m1", "输入"), accepted(), quiet_seconds=0.5, now_ms=1_000)

    preparing = store.claim_ready(now_ms=1_500)
    assert preparing is not None
    store.initialize(now_ms=1_600)
    recovered_preparing = store.claim_ready(now_ms=1_600)
    assert recovered_preparing is not None
    assert recovered_preparing.state == "preparing"

    exact = PreparedReply(ReplyDecision.SENT, "已生成的准确回复", 17)
    store.mark_prepared(recovered_preparing.batch_id, exact, now_ms=1_700)
    sending = store.claim_ready(now_ms=1_700)
    assert sending is not None
    assert sending.state == "sending"
    assert sending.prepared == exact

    store.initialize(now_ms=1_800)
    recovered_sending = store.claim_ready(now_ms=1_800)
    assert recovered_sending is not None
    assert recovered_sending.state == "sending"
    assert recovered_sending.prepared == exact


@pytest.mark.asyncio
async def test_cancelled_delivery_replays_persisted_preparation_not_model(
    tmp_path: Path,
) -> None:
    path = tmp_path / "official_processing.sqlite"
    store = OfficialProcessingStore(path)
    store.initialize(now_ms=1_000)
    store.enqueue(event("m1", "输入"), accepted(), quiet_seconds=0.5, now_ms=1_000)
    prepare_calls: list[str] = []
    delivered: list[str] = []

    async def prepare(inbound: InboundEvent, result: IngestResult) -> PreparedReply:
        prepare_calls.append(inbound.message_id)
        return PreparedReply(ReplyDecision.SENT, "固定回复", 9)

    async def cancelled_delivery(inbound: InboundEvent, prepared: PreparedReply) -> ReplyPlan:
        assert inbound.message_id == "m1"
        delivered.append(prepared.text or "")
        raise asyncio.CancelledError

    async def finalize(inbound: InboundEvent, plan: ReplyPlan) -> None:
        raise AssertionError("cancelled delivery must not finalize")

    processor = OfficialDurableProcessor(
        store=store,
        prepare=prepare,
        deliver=cancelled_delivery,
        finalize=finalize,
    )
    assert await processor.process_one()
    with pytest.raises(asyncio.CancelledError):
        await processor.process_one()
    assert prepare_calls == ["m1"]
    assert delivered == ["固定回复"]

    restarted = OfficialProcessingStore(path)
    restarted.initialize()

    async def recovered_delivery(inbound: InboundEvent, prepared: PreparedReply) -> ReplyPlan:
        delivered.append(prepared.text or "")
        return ReplyPlan(ReplyDecision.SEND_FAILED, prepared.text)

    finalized: list[ReplyPlan] = []

    async def recovered_finalize(inbound: InboundEvent, plan: ReplyPlan) -> None:
        finalized.append(plan)

    recovery = OfficialDurableProcessor(
        store=restarted,
        prepare=prepare,
        deliver=recovered_delivery,
        finalize=recovered_finalize,
    )
    assert await recovery.process_one()
    assert await recovery.process_one()
    assert restarted.state_counts() == {"complete": 1}
    assert prepare_calls == ["m1"]
    assert delivered == ["固定回复", "固定回复"]
    assert finalized == [ReplyPlan(ReplyDecision.SEND_FAILED, "固定回复")]


@pytest.mark.asyncio
async def test_offline_preparation_completes_without_outbound_delivery(tmp_path: Path) -> None:
    store = OfficialProcessingStore(tmp_path / "official_processing.sqlite")
    store.initialize(now_ms=1_000)
    store.enqueue(event("m1", "输入"), accepted(), quiet_seconds=0.5, now_ms=1_000)
    delivered = False
    finalized: list[ReplyPlan] = []

    async def prepare(inbound: InboundEvent, result: IngestResult) -> PreparedReply:
        return PreparedReply(ReplyDecision.QQ_OFFLINE)

    async def deliver(inbound: InboundEvent, prepared: PreparedReply) -> ReplyPlan:
        nonlocal delivered
        delivered = True
        raise AssertionError("offline work must not be delivered")

    async def finalize(inbound: InboundEvent, plan: ReplyPlan) -> None:
        finalized.append(plan)

    processor = OfficialDurableProcessor(
        store=store,
        prepare=prepare,
        deliver=deliver,
        finalize=finalize,
    )
    assert await processor.process_one()
    assert await processor.process_one()
    assert not delivered
    assert finalized == [ReplyPlan(ReplyDecision.QQ_OFFLINE)]
    assert store.state_counts() == {"complete": 1}
    assert store.purge_completed(before_ms=2**62) == 1
    assert store.state_counts() == {}


@pytest.mark.asyncio
async def test_finalizing_recovery_keeps_audit_and_history_single_row(tmp_path: Path) -> None:
    store = OfficialProcessingStore(tmp_path / "official_processing.sqlite")
    store.initialize(now_ms=1_000)
    inbound = event("m1", "输入")
    store.enqueue(inbound, accepted(), quiet_seconds=0.5, now_ms=1_000)
    audit = ReplyAudit(tmp_path / "reply_audit.sqlite")
    audit.initialize()
    history = ConversationStore(tmp_path / "conversation.sqlite")
    history.initialize()
    finalize_calls = 0

    async def prepare(item: InboundEvent, result: IngestResult) -> PreparedReply:
        return PreparedReply(ReplyDecision.SENT, "固定回复", 1)

    async def deliver(item: InboundEvent, prepared: PreparedReply) -> ReplyPlan:
        return ReplyPlan(ReplyDecision.SENT, prepared.text)

    async def crash_after_writes(item: InboundEvent, plan: ReplyPlan) -> None:
        nonlocal finalize_calls
        finalize_calls += 1
        audit.record(item, plan)
        history.record(
            item,
            principal_id="owner-principal",
            outcome=plan.decision.value,
            assistant_text=plan.text,
        )
        raise RuntimeError("simulated crash before complete")

    processor = OfficialDurableProcessor(
        store=store,
        prepare=prepare,
        deliver=deliver,
        finalize=crash_after_writes,
    )
    assert await processor.process_one()
    assert await processor.process_one()
    assert await processor.process_one()
    assert finalize_calls == 1

    recovered = store.claim_ready(now_ms=2**62)
    assert recovered is not None
    assert recovered.state == "finalizing"
    assert recovered.final_plan == ReplyPlan(ReplyDecision.SENT, "固定回复")
    audit.record(recovered.event, recovered.final_plan)
    history.record(
        recovered.event,
        principal_id="owner-principal",
        outcome=recovered.final_plan.decision.value,
        assistant_text=recovered.final_plan.text,
    )
    store.mark_complete(recovered.batch_id)

    with sqlite3.connect(audit.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM reply_audit").fetchone()[0] == 1
    with sqlite3.connect(history.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM conversation_turns").fetchone()[0] == 1
    assert store.state_counts() == {"complete": 1}
