import sqlite3
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


def test_initialize_migrates_existing_risk_events_for_source_hash(tmp_path: Path) -> None:
    path = tmp_path / "risk.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE risk_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                outcome TEXT NOT NULL,
                actor_class TEXT NOT NULL,
                account_hash TEXT,
                conversation_hash TEXT,
                reason_code TEXT,
                client_version TEXT,
                transport_version TEXT,
                egress_asn TEXT,
                created_at_ms INTEGER NOT NULL
            )
            """
        )

    risk = RiskLedger(path)
    risk.initialize()
    with sqlite3.connect(path) as conn:
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(risk_events)")}
        indexes = {str(row[1]) for row in conn.execute("PRAGMA index_list(risk_events)")}
    assert "source_hash" in columns
    assert "idx_risk_source_time" in indexes


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


def test_group_robot_detection_isolated_per_sender(tmp_path: Path) -> None:
    risk = ledger(tmp_path)
    conversation = "qq:group:bot:group"
    for index in range(11):
        assert risk.note_inbound(
            conversation,
            actor_class="non_owner",
            account_id="bot",
            source_id="member-a",
            now_ms=1_000 + index,
        )
        assert risk.note_inbound(
            conversation,
            actor_class="non_owner",
            account_id="bot",
            source_id="member-b",
            now_ms=1_100 + index,
        )

    assert not risk.note_inbound(
        conversation,
        actor_class="non_owner",
        account_id="bot",
        source_id="member-a",
        now_ms=2_000,
    )
    assert risk.learning_allowed(conversation, source_id="member-b", now_ms=2_000)
    blocked = risk.reserve_send(
        event_type="reply",
        actor_class="non_owner",
        account_id="bot",
        conversation_id=conversation,
        source_id="member-a",
        now_ms=2_000,
    )
    allowed = risk.reserve_send(
        event_type="reply",
        actor_class="non_owner",
        account_id="bot",
        conversation_id=conversation,
        source_id="member-b",
        now_ms=2_000,
    )
    assert not blocked.allowed
    assert blocked.reason == "suspected_robot_source"
    assert allowed.allowed
    blob = (tmp_path / "risk.sqlite").read_bytes()
    assert b"member-a" not in blob
    assert b"member-b" not in blob


def test_online_transition_ledger_deduplicates_probes_and_counts_kicks(tmp_path: Path) -> None:
    risk = ledger(tmp_path)
    assert risk.record_online_transition(online=True, reason="probe_ok", now_ms=1_000)
    assert not risk.record_online_transition(online=True, reason="probe_ok", now_ms=2_000)
    assert risk.record_online_transition(online=False, reason="KickedOffLine", now_ms=3_000)
    assert risk.stats(now_ms=4_000)["kicked_offline_24h"] == 1
