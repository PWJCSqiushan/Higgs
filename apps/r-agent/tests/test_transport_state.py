import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from r_agent.health import HealthReporter, check_health
from r_agent.online_reliability import OnlineState
from r_agent.transport_state import TransportStateError, TransportStateStore


class FakeNotifier:
    enabled = True

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def send(self, *, title: str, content: str) -> None:
        self.messages.append((title, content))


def test_transport_store_persists_redacted_transitions_and_duration(tmp_path: Path) -> None:
    store = TransportStateStore(tmp_path / "transport.sqlite")
    store.initialize()

    pending = store.snapshot(now_ms=1_000)
    assert pending.state == "pending"
    assert pending.container_alive is None
    assert pending.duration_ms == 0

    online = store.record_transition(
        "verified",
        reason="get_status_ok",
        now_ms=2_000,
        container_alive=True,
        onebot_reachable=True,
        qq_online=True,
        account_match=True,
        health_receipt=("ok", "get_status_ok"),
    )
    assert online.state == "verified"
    assert online.duration_ms == 0
    assert online.account_match is True
    assert online.last_health_state == "ok"

    offline = store.record_transition(
        "rejected",
        reason="KickedOffLine",
        now_ms=62_000,
        container_alive=True,
        onebot_reachable=True,
        qq_online=False,
        account_match=None,
        kick_reason="KickedOffLine",
    )
    assert offline.incident_id == 1
    assert offline.fault_duration_ms == 0
    assert offline.kick_reason == "KickedOffLine"
    assert offline.account_match is None

    recovered = store.record_transition(
        "verified",
        reason="get_status_ok",
        now_ms=70_000,
        container_alive=True,
        onebot_reachable=True,
        qq_online=True,
        account_match=True,
        health_receipt=("ok", "get_status_ok"),
    )
    assert recovered.recovery_result == "recovered"
    assert recovered.recovery_at_ms == 70_000
    history = store.transitions()
    rejected = next(item for item in history if item.to_state == "rejected")
    assert rejected.ended_at_ms == 70_000
    assert rejected.duration_ms == 8_000

    status = store.status(now_ms=75_000)
    assert status["duration_ms"] == 5_000
    encoded = json.dumps(status, ensure_ascii=False)
    assert "123456" not in encoded
    assert "message" not in encoded.casefold()
    with sqlite3.connect(store.path) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"transport_state", "transport_transitions"} <= tables


def test_transport_alert_claim_is_once_per_incident_and_recovery(tmp_path: Path) -> None:
    store = TransportStateStore(tmp_path / "transport.sqlite")
    store.record_transition(
        "verified",
        reason="online",
        now_ms=1_000,
        onebot_reachable=True,
        qq_online=True,
        account_match=True,
    )
    offline = store.record_transition(
        "rejected",
        reason="probe_failed",
        now_ms=2_000,
        onebot_reachable=True,
        qq_online=False,
    )
    assert store.claim_alert("incident", offline.incident_id, now_ms=2_000)
    assert not store.claim_alert("incident", offline.incident_id, now_ms=2_001)

    recovered = store.record_transition(
        "verified",
        reason="online",
        now_ms=3_000,
        onebot_reachable=True,
        qq_online=True,
        account_match=True,
    )
    assert store.claim_alert("recovery", recovered.incident_id, now_ms=3_000)
    assert not store.claim_alert("recovery", recovered.incident_id, now_ms=3_001)

    second_offline = store.record_transition(
        "rejected",
        reason="probe_failed",
        now_ms=4_000,
        onebot_reachable=True,
        qq_online=False,
    )
    assert second_offline.incident_id == 2
    assert store.claim_alert("incident", second_offline.incident_id, now_ms=4_000)


def test_online_state_persists_wrong_account_kick_and_recovery_without_restart(
    tmp_path: Path,
) -> None:
    health = HealthReporter(tmp_path / "health.json", interval_seconds=5)
    notifier = FakeNotifier()
    store = TransportStateStore(tmp_path / "transport.sqlite")
    online = OnlineState(health, notifier, transport_state=store)  # type: ignore[arg-type]

    async def run() -> None:
        await online.set_transport(True)
        await online.set_qq_online(True, reason="get_status_ok")
        await online.set_qq_online(False, reason="wrong_qq_account")
        await online.set_qq_online(False, reason="wrong_qq_account")
        await online.set_qq_online(True, reason="get_status_ok")
        await online.set_qq_online(False, reason="KickedOffLine", health_receipt=False)
        await online.set_qq_online(False, reason="KickedOffLine", health_receipt=False)
        await online.set_qq_online(True, reason="get_status_ok")

    asyncio.run(run())
    assert len(notifier.messages) == 4
    snapshot = store.snapshot()
    assert snapshot.state == "verified"
    assert snapshot.account_match is True
    assert snapshot.kick_reason == "KickedOffLine"
    assert snapshot.recovery_result == "recovered"
    payload = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    assert payload["account_match"] is True
    assert payload["last_action_state"] == "ok"
    assert check_health(tmp_path / "health.json", require_qq_online=True) == (True, "ok")


def test_online_state_marks_wrong_account_as_not_matching(tmp_path: Path) -> None:
    health = HealthReporter(tmp_path / "health.json", interval_seconds=5)
    store = TransportStateStore(tmp_path / "transport.sqlite")
    online = OnlineState(health, FakeNotifier(), transport_state=store)  # type: ignore[arg-type]

    async def run() -> None:
        await online.set_transport(True)
        await online.set_qq_online(True, reason="get_status_ok")
        await online.set_qq_online(False, reason="wrong_qq_account")

    asyncio.run(run())
    snapshot = store.snapshot()
    assert snapshot.qq_online is False
    assert snapshot.account_match is False
    payload = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    assert payload["account_match"] is False
    health.set_qq_online(True, reason="probe")
    health.set_account_match(False)
    assert check_health(tmp_path / "health.json", require_qq_online=True) == (
        False,
        "wrong_qq_account",
    )


def test_health_dimensions_fail_closed_for_unreachable_or_dead_container(
    tmp_path: Path,
) -> None:
    path = tmp_path / "health.json"
    health = HealthReporter(path, interval_seconds=5)
    health.set_transport_connected(True)
    assert check_health(path) == (True, "ok")
    health.set_container_alive(False)
    assert check_health(path) == (False, "container_not_alive")
    health.set_container_alive(True)
    health.set_transport_connected(False)
    assert check_health(path) == (False, "onebot_disconnected")


def test_transport_state_rejects_unknown_values(tmp_path: Path) -> None:
    store = TransportStateStore(tmp_path / "transport.sqlite")
    with pytest.raises(TransportStateError):
        store.record_transition("offline", reason="bad")
    with pytest.raises(TransportStateError):
        store.record_health_receipt("sent", reason="bad")


def test_transport_store_does_not_persist_free_form_reason_text(tmp_path: Path) -> None:
    store = TransportStateStore(tmp_path / "transport.sqlite")
    snapshot = store.record_health_receipt(
        "failed",
        reason="token=secret-message payload should never be stored",
        now_ms=1_000,
    )
    assert snapshot.last_health_reason == "unspecified"
    with sqlite3.connect(store.path) as conn:
        values = conn.execute(
            "SELECT last_health_reason, last_action_reason FROM transport_state"
        ).fetchone()
    assert values == ("unspecified", "unspecified")
