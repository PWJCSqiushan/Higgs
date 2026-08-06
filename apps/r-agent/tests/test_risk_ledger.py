from pathlib import Path

from r_agent.risk_ledger import RiskLedger, RiskLimits


def ledger(tmp_path: Path) -> RiskLedger:
    result = RiskLedger(
        tmp_path / "risk.sqlite",
        limits=RiskLimits(
            conversation_per_minute=2,
            global_per_minute=6,
            non_owner_per_hour=8,
            non_owner_per_day=8,
            owner_conversation_per_minute=4,
            owner_per_hour=6,
            owner_per_day=6,
            global_per_hour=12,
            global_per_day=12,
        ),
    )
    result.initialize()
    return result


def test_persistent_send_budget_is_shared_and_content_free(tmp_path: Path) -> None:
    risk = ledger(tmp_path)
    first = risk.reserve_send(
        event_type="reply",
        actor_class="non_owner",
        account_id="900001",
        conversation_id="qq:private:900001:800001",
        now_ms=1_000,
    )
    assert first.allowed and first.reservation_id is not None
    risk.finish_send(first.reservation_id, outcome="sent")
    second = risk.reserve_send(
        event_type="reply",
        actor_class="non_owner",
        account_id="900001",
        conversation_id="qq:private:900001:800001",
        now_ms=2_000,
    )
    assert second.allowed and second.reservation_id is not None
    risk.finish_send(second.reservation_id, outcome="sent")
    blocked = risk.reserve_send(
        event_type="proactive",
        actor_class="non_owner",
        account_id="900001",
        conversation_id="qq:private:900001:800001",
        now_ms=3_000,
    )
    assert not blocked.allowed
    assert blocked.reason == "self_continuation_blocked"

    blob = (tmp_path / "risk.sqlite").read_bytes()
    assert b"900001" not in blob
    assert b"qq:private" not in blob


def test_robot_like_source_is_blocked_from_reply_and_learning(tmp_path: Path) -> None:
    risk = ledger(tmp_path)
    conversation = "qq:private:bot:peer"
    for index in range(12):
        risk.note_inbound(
            conversation,
            actor_class="non_owner",
            account_id="bot",
            now_ms=1_000 + index,
        )
    assert not risk.learning_allowed(conversation, now_ms=2_000)
    decision = risk.reserve_send(
        event_type="reply",
        actor_class="non_owner",
        account_id="agent",
        conversation_id=conversation,
        now_ms=2_000,
    )
    assert not decision.allowed
    assert decision.reason == "suspected_robot_source"
    assert risk.stats(now_ms=2_000)["suspected_robot_sources"] == 1


def test_online_transition_ledger_deduplicates_probes_and_counts_kicks(tmp_path: Path) -> None:
    risk = ledger(tmp_path)
    assert risk.record_online_transition(online=True, reason="probe_ok", now_ms=1_000)
    assert not risk.record_online_transition(online=True, reason="probe_ok", now_ms=2_000)
    assert risk.record_online_transition(online=False, reason="KickedOffLine", now_ms=3_000)
    assert risk.stats(now_ms=4_000)["kicked_offline_24h"] == 1
