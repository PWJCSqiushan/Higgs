from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from r_agent.access import IngressDecision
from r_agent.conversation import ConversationStore
from r_agent.events import AttachmentRef, ConversationKind, InboundEvent
from r_agent.ingest import IngestResult
from r_agent.official_processing import (
    OfficialDurableProcessor,
    OfficialProcessingError,
    OfficialProcessingStore,
    _event_from_json,
)
from r_agent.phase2_cli import deliver_prepared_reply
from r_agent.phase2_reply import PreparedReply, ReplyAudit, ReplyDecision, ReplyPlan
from r_agent.risk_ledger import RiskLedger
from r_agent.safe_tools import AttachmentHandleStore, DocumentSecurityError, SafeReadOnlyTools
from r_agent.transport import DeliveryReceipt, DeliveryState


def event(
    message_id: str,
    text: str,
    *,
    occurred_at_ms: int = 1_000,
    sender_id: str = "owner-openid",
    group_id: str | None = None,
    attachments: tuple[AttachmentRef, ...] = (),
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
        attachments=attachments,
    )


def accepted(*, stored: bool = True, duplicate: bool = False) -> IngestResult:
    return IngestResult(IngressDecision.ACCEPT, stored=stored, duplicate=duplicate)


def test_durable_event_redacts_attachment_path_and_replay_uses_private_handle_scope(
    tmp_path: Path,
) -> None:
    root = tmp_path / "attachments"
    root.mkdir()
    (root / "note.txt").write_text("private attachment", encoding="utf-8")
    reference = AttachmentRef(
        kind="document",
        file_name="note.txt",
        attachment_id="opaque-replay-handle",
        media_type="text/plain",
    )
    original = event("attachment-replay", "读取附件", attachments=(reference,))
    handles = AttachmentHandleStore()
    handles.bind(
        original,
        reference,
        relative_path="note.txt",
        session_id="session-replay",
        principal_id="principal-replay",
    )

    store = OfficialProcessingStore(tmp_path / "official_processing.sqlite")
    store.initialize(now_ms=1_000)
    assert store.enqueue(original, accepted(), quiet_seconds=0.5, now_ms=1_000)
    with sqlite3.connect(store.path) as connection:
        raw = connection.execute(
            "SELECT event_json FROM official_processing_batches ORDER BY created_at_ms LIMIT 1",
        ).fetchone()[0]
    assert '"relative_path"' not in raw
    assert '"url"' not in raw
    replayed = _event_from_json(raw)
    assert not hasattr(replayed.attachments[0], "relative_path")

    tools = SafeReadOnlyTools(
        document_root=root,
        attachment_handles=handles,
        enabled=True,
    )
    result = tools.document_read(
        replayed,
        attachment_id="opaque-replay-handle",
        session_id="session-replay",
        principal_id="principal-replay",
    )
    assert result["text"] == "private attachment"

    for changed in (
        replace(replayed, account_id="different-bot"),
        replace(replayed, sender_id="different-sender"),
        replace(replayed, message_id="different-event"),
    ):
        with pytest.raises(DocumentSecurityError):
            tools.document_read(
                changed,
                attachment_id="opaque-replay-handle",
                session_id="session-replay",
                principal_id="principal-replay",
            )
    with pytest.raises(DocumentSecurityError):
        tools.document_read(
            replayed,
            attachment_id="opaque-replay-handle",
            session_id="different-session",
            principal_id="principal-replay",
        )
    with pytest.raises(DocumentSecurityError):
        tools.document_read(
            replayed,
            attachment_id="opaque-replay-handle",
            session_id="session-replay",
            principal_id="different-principal",
        )

    legacy = json.loads(raw)
    legacy["attachments"][0]["relative_path"] = "note.txt"
    with pytest.raises(OfficialProcessingError):
        _event_from_json(json.dumps(legacy))
    legacy["attachments"][0].pop("relative_path")
    legacy["attachments"][0]["url"] = "https://public.example/"
    with pytest.raises(OfficialProcessingError):
        _event_from_json(json.dumps(legacy))


@pytest.mark.asyncio
async def test_post_sent_observer_failure_cannot_turn_delivery_into_retry() -> None:
    inbound = event("sent-observer-failure", "输入")
    provider_calls = 0

    async def sender(item: InboundEvent, _text: str) -> DeliveryReceipt:
        nonlocal provider_calls
        provider_calls += 1
        return DeliveryReceipt(
            channel=item.channel,
            state=DeliveryState.SENT,
            idempotency_key="reply:sent-observer-failure",
            provider_message_id="provider-sent-observer-failure",
        )

    async def broken_observer(
        _event: InboundEvent,
        _text: str,
        _receipt: DeliveryReceipt,
    ) -> None:
        raise RuntimeError("post-send memory failure")

    plan = await deliver_prepared_reply(
        event=inbound,
        prepared=PreparedReply(ReplyDecision.SENT, "已经发送"),
        sender=sender,
        retry_transport_unavailable=True,
        on_sent=broken_observer,
    )

    assert plan.decision is ReplyDecision.SENT
    assert provider_calls == 1


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

    # A completed source remains a compact hashed tombstone after batch cleanup,
    # so an upstream replay after a long outage cannot produce a second reply.
    assert not store.enqueue(
        event("m1", "输入"),
        accepted(stored=False, duplicate=True),
        quiet_seconds=0.5,
        now_ms=2**62,
    )
    with sqlite3.connect(store.path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM official_processing_tombstones").fetchone()[0] == 1
        )
        tombstone = conn.execute(
            "SELECT source_hash FROM official_processing_tombstones"
        ).fetchone()[0]
    assert len(tombstone) == 64
    assert "m1" not in tombstone


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


@pytest.mark.asyncio
async def test_unknown_receipt_finishes_risk_audit_history_and_never_retries(
    tmp_path: Path,
) -> None:
    store = OfficialProcessingStore(tmp_path / "official_processing.sqlite")
    store.initialize(now_ms=1_000)
    inbound = event("unknown-boundary", "输入")
    store.enqueue(inbound, accepted(), quiet_seconds=0.5, now_ms=1_000)
    preparing = store.claim_ready(now_ms=1_500)
    assert preparing is not None

    risk = RiskLedger(tmp_path / "risk.sqlite")
    risk.initialize()
    budget = risk.reserve_send(
        event_type="reply",
        actor_class="owner",
        account_id=inbound.account_id,
        conversation_id=inbound.conversation_id,
        idempotency_key="reply:unknown-boundary",
        now_ms=1_500,
    )
    assert budget.allowed and budget.reservation_id is not None
    store.mark_prepared(
        preparing.batch_id,
        PreparedReply(ReplyDecision.SENT, "固定回复", budget.reservation_id),
        now_ms=1_600,
    )

    audit = ReplyAudit(tmp_path / "reply_audit.sqlite")
    audit.initialize()
    history = ConversationStore(tmp_path / "conversation.sqlite")
    history.initialize()
    provider_calls = 0

    async def prepare_never(_event: InboundEvent, _result: IngestResult) -> PreparedReply:
        raise AssertionError("persisted preparation must not be regenerated")

    async def sender(item: InboundEvent, _text: str) -> DeliveryReceipt:
        nonlocal provider_calls
        provider_calls += 1
        return DeliveryReceipt(
            channel=item.channel,
            state=DeliveryState.UNKNOWN,
            idempotency_key="reply:unknown-boundary",
        )

    async def deliver(item: InboundEvent, prepared: PreparedReply) -> ReplyPlan:
        return await deliver_prepared_reply(
            event=item,
            prepared=prepared,
            sender=sender,
            risk_ledger=risk,
            retry_transport_unavailable=True,
        )

    async def finalize(item: InboundEvent, plan: ReplyPlan) -> None:
        audit.record(item, plan)
        history.record(
            item,
            principal_id="owner-principal",
            outcome=plan.decision.value,
            assistant_text=plan.text,
        )

    processor = OfficialDurableProcessor(
        store=store,
        prepare=prepare_never,
        deliver=deliver,
        finalize=finalize,
    )
    assert await processor.process_one()
    assert await processor.process_one()
    assert not await processor.process_one()
    assert provider_calls == 1
    assert store.state_counts() == {"complete": 1}
    with sqlite3.connect(risk.path) as conn:
        assert (
            conn.execute(
                "SELECT outcome FROM risk_events WHERE id=?", (budget.reservation_id,)
            ).fetchone()[0]
            == "unknown"
        )
    with sqlite3.connect(audit.path) as conn:
        assert conn.execute("SELECT decision FROM reply_audit").fetchone()[0] == "send_failed"
    with sqlite3.connect(history.path) as conn:
        assert conn.execute("SELECT outcome FROM conversation_turns").fetchone()[0] == "send_failed"


@pytest.mark.asyncio
async def test_prepare_crash_reuses_one_real_risk_reservation(tmp_path: Path) -> None:
    store = OfficialProcessingStore(tmp_path / "official_processing.sqlite")
    store.initialize(now_ms=1_000)
    inbound = event("prepare-crash", "输入")
    store.enqueue(inbound, accepted(), quiet_seconds=0.5, now_ms=1_000)
    risk = RiskLedger(tmp_path / "risk.sqlite")
    risk.initialize()
    prepare_calls = 0

    async def prepare(item: InboundEvent, _result: IngestResult) -> PreparedReply:
        nonlocal prepare_calls
        prepare_calls += 1
        budget = risk.reserve_send(
            event_type="reply",
            actor_class="owner",
            account_id=item.account_id,
            conversation_id=item.conversation_id,
            idempotency_key="reply:prepare-crash",
            now_ms=1_500 + prepare_calls,
        )
        assert budget.allowed and budget.reservation_id is not None
        if prepare_calls == 1:
            raise RuntimeError("simulated crash after reservation")
        return PreparedReply(ReplyDecision.SENT, "第二次生成", budget.reservation_id)

    async def deliver(_event: InboundEvent, prepared: PreparedReply) -> ReplyPlan:
        assert prepared.text == "第二次生成"
        assert prepared.reservation_id is not None
        risk.finish_send(prepared.reservation_id, outcome="sent")
        return ReplyPlan(ReplyDecision.SENT, prepared.text)

    async def finalize(_event: InboundEvent, _plan: ReplyPlan) -> None:
        return None

    processor = OfficialDurableProcessor(
        store=store,
        prepare=prepare,
        deliver=deliver,
        finalize=finalize,
    )
    assert await processor.process_one()
    with sqlite3.connect(store.path) as conn:
        conn.execute("UPDATE official_processing_batches SET retry_at_ms=0 WHERE state='pending'")
    assert await processor.process_one()
    assert await processor.process_one()
    assert await processor.process_one()
    assert prepare_calls == 2
    with sqlite3.connect(risk.path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM risk_events WHERE event_type='reply'").fetchone()[0]
            == 1
        )
        assert (
            conn.execute("SELECT outcome FROM risk_events WHERE event_type='reply'").fetchone()[0]
            == "sent"
        )
