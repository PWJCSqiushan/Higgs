import json

import pytest

from r_agent.events import ConversationKind, InboundEvent
from r_agent.phase2_cli import (
    ONLINE_PROBE_INTERVAL_SECONDS,
    ONLINE_PROBE_MAX_DETECTION_SECONDS,
    ONLINE_PROBE_TIMEOUT_SECONDS,
    _official_event_quiet_seconds,
    _official_reminder_target,
    _onebot_reminder_target,
)
from r_agent.phase2_outbound import (
    OutboundError,
    get_onebot_account_status,
    get_onebot_message_sender,
    send_onebot_group_message,
    send_onebot_reply,
)
from r_agent.reminders import DueOccurrence


class QuietWindowControl:
    def debounce_seconds_for(self, *, private: bool) -> float:
        return 1.25 if private else 3.5


def event() -> InboundEvent:
    return InboundEvent(
        channel="qq",
        account_id="900001",
        sender_id="800001",
        message_id="42",
        occurred_at_ms=1_767_225_600_000,
        conversation_kind=ConversationKind.PRIVATE,
        conversation_id="qq:private:900001:800001",
        group_id=None,
        text="hello",
        mentioned=False,
    )


def test_official_quiet_window_reads_live_control_for_each_surface() -> None:
    private = event()
    group = InboundEvent(
        channel="qq_official",
        account_id="bot-id",
        sender_id="member-id",
        message_id="43",
        occurred_at_ms=private.occurred_at_ms,
        conversation_kind=ConversationKind.GROUP,
        conversation_id="qq_official:group:bot-id:group-id",
        group_id="group-id",
        text="hello",
        mentioned=True,
    )
    control = QuietWindowControl()
    assert _official_event_quiet_seconds(private, control) == 1.25  # type: ignore[arg-type]
    assert _official_event_quiet_seconds(group, control) == 3.5  # type: ignore[arg-type]


def reminder_occurrence(*, channel: str = "qq_official") -> DueOccurrence:
    return DueOccurrence(
        occurrence_key="job:0",
        job_id="job",
        owner_qq="owner-id",
        content="study",
        attempt=0,
        scheduled_at_ms=1,
        origin_channel=channel,
        origin_surface="private",
        origin_conversation_id=f"{channel}:private:bot-id:owner-id",
        delivery_channel=channel,
        delivery_surface="private",
        delivery_account_id="bot-id",
        delivery_target_id="owner-id",
    )


def test_reminder_targets_require_exact_persisted_channel_account_and_owner() -> None:
    official = reminder_occurrence()
    target = _official_reminder_target(
        official,
        owner_openid="owner-id",
        account_id="bot-id",
        owner_proactive_enabled=True,
    )
    assert target is not None
    assert target.conversation_id == "qq_official:private:bot-id:owner-id"
    assert (
        _official_reminder_target(
            official,
            owner_openid="another-owner",
            account_id="bot-id",
            owner_proactive_enabled=True,
        )
        is None
    )
    assert (
        _official_reminder_target(
            official,
            owner_openid="owner-id",
            account_id="another-bot",
            owner_proactive_enabled=True,
        )
        is None
    )
    assert (
        _official_reminder_target(
            official,
            owner_openid="owner-id",
            account_id="bot-id",
            owner_proactive_enabled=False,
        )
        is None
    )

    onebot = reminder_occurrence(channel="qq")
    onebot_target = _onebot_reminder_target(onebot)
    assert onebot_target is not None
    assert onebot_target.conversation_id == "qq:private:bot-id:owner-id"
    assert _onebot_reminder_target(official) is None


class FakeSocket:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.sent: dict[str, object] | None = None

    async def send(self, raw: str) -> None:
        self.sent = json.loads(raw)

    async def recv(self) -> str:
        return self.responses.pop(0)


class FakeConnection:
    def __init__(self, socket: FakeSocket) -> None:
        self.socket = socket

    async def __aenter__(self) -> FakeSocket:
        return self.socket

    async def __aexit__(self, *args: object) -> None:
        return None


class BlackHoleSocket(FakeSocket):
    async def recv(self) -> str:
        raise TimeoutError("probe response unavailable")


async def test_outbound_ignores_event_before_matching_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = FakeSocket(
        [
            json.dumps({"post_type": "message"}),
            json.dumps(
                {
                    "status": "ok",
                    "retcode": 0,
                    "echo": "r-agent-phase2:900001:42",
                    "data": {"message_id": 1},
                }
            ),
        ]
    )
    monkeypatch.setattr("websockets.connect", lambda *args, **kwargs: FakeConnection(socket))
    await send_onebot_reply("ws://127.0.0.1:3001", "token", event(), "reply")
    assert socket.sent is not None
    assert socket.sent["action"] == "send_private_msg"
    assert socket.sent["echo"] == "r-agent-phase2:900001:42"


async def test_outbound_rejects_negative_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    socket = FakeSocket(
        [
            json.dumps(
                {
                    "status": "failed",
                    "retcode": 100,
                    "echo": "r-agent-phase2:900001:42",
                }
            )
        ]
    )
    monkeypatch.setattr("websockets.connect", lambda *args, **kwargs: FakeConnection(socket))
    with pytest.raises(OutboundError, match="rejected"):
        await send_onebot_reply("ws://127.0.0.1:3001", "token", event(), "reply")


async def test_outbound_rejects_missing_retcode_as_known_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = FakeSocket([json.dumps({"status": "ok", "echo": "r-agent-phase2:900001:42"})])
    monkeypatch.setattr("websockets.connect", lambda *args, **kwargs: FakeConnection(socket))
    with pytest.raises(OutboundError) as caught:
        await send_onebot_reply("ws://127.0.0.1:3001", "token", event(), "reply")
    assert caught.value.delivery_unknown is False


async def test_outbound_treats_missing_provider_message_id_as_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = FakeSocket(
        [
            json.dumps(
                {
                    "status": "ok",
                    "retcode": 0,
                    "echo": "r-agent-phase2:900001:42",
                    "data": {},
                }
            )
        ]
    )
    monkeypatch.setattr("websockets.connect", lambda *args, **kwargs: FakeConnection(socket))
    with pytest.raises(OutboundError) as caught:
        await send_onebot_reply("ws://127.0.0.1:3001", "token", event(), "reply")
    assert caught.value.delivery_unknown is True


async def test_get_message_sender_verifies_quoted_author(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = FakeSocket(
        [
            json.dumps(
                {
                    "status": "ok",
                    "retcode": 0,
                    "echo": "r-agent-phase2:get-msg:42",
                    "data": {"sender": {"user_id": 900001}},
                }
            )
        ]
    )
    monkeypatch.setattr("websockets.connect", lambda *args, **kwargs: FakeConnection(socket))
    sender = await get_onebot_message_sender(
        "ws://127.0.0.1:3001",
        "token",
        "42",
    )
    assert sender == "900001"
    assert socket.sent is not None
    assert socket.sent["action"] == "get_msg"


async def test_account_status_does_not_treat_login_info_as_online_when_status_is_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = FakeSocket(
        [
            json.dumps(
                {
                    "status": "ok",
                    "retcode": 0,
                    "echo": "r-agent:status-probe",
                    "data": {"online": False, "good": True},
                }
            )
        ]
    )
    monkeypatch.setattr("websockets.connect", lambda *args, **kwargs: FakeConnection(socket))

    status = await get_onebot_account_status("ws://127.0.0.1:3001", "token")

    assert status.online is False
    assert status.good is True
    assert status.account_id is None
    assert socket.sent is not None
    assert socket.sent["action"] == "get_status"


async def test_account_status_requires_online_status_before_login_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = FakeSocket(
        [
            json.dumps(
                {
                    "status": "ok",
                    "retcode": 0,
                    "echo": "r-agent:status-probe",
                    "data": {"online": True, "good": True},
                }
            ),
            json.dumps(
                {
                    "status": "ok",
                    "retcode": 0,
                    "echo": "r-agent:online-probe",
                    "data": {"user_id": 900001, "nickname": "Higgs"},
                }
            ),
        ]
    )
    monkeypatch.setattr("websockets.connect", lambda *args, **kwargs: FakeConnection(socket))

    status = await get_onebot_account_status("ws://127.0.0.1:3001", "token")

    assert status.online is True
    assert status.good is True
    assert status.account_id == "900001"
    assert status.nickname == "Higgs"


@pytest.mark.parametrize(
    ("online", "good"),
    [(False, True), (True, False)],
)
async def test_account_status_rejects_unhealthy_status_without_login_probe(
    monkeypatch: pytest.MonkeyPatch,
    online: bool,
    good: bool,
) -> None:
    socket = FakeSocket(
        [
            json.dumps(
                {
                    "status": "ok",
                    "retcode": 0,
                    "echo": "r-agent:status-probe",
                    "data": {"online": online, "good": good},
                }
            )
        ]
    )
    monkeypatch.setattr("websockets.connect", lambda *args, **kwargs: FakeConnection(socket))

    status = await get_onebot_account_status("ws://127.0.0.1:3001", "token")

    assert status.online is online
    assert status.good is good
    assert status.account_id is None


async def test_account_status_blackhole_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    socket = BlackHoleSocket([])
    monkeypatch.setattr("websockets.connect", lambda *args, **kwargs: FakeConnection(socket))

    with pytest.raises(OutboundError, match="action failed"):
        await get_onebot_account_status("ws://127.0.0.1:3001", "token")


def test_online_probe_detection_budget_stays_within_sixty_seconds() -> None:
    assert ONLINE_PROBE_INTERVAL_SECONDS == 30.0
    assert ONLINE_PROBE_TIMEOUT_SECONDS == 20.0
    assert ONLINE_PROBE_MAX_DETECTION_SECONDS == (
        ONLINE_PROBE_INTERVAL_SECONDS + ONLINE_PROBE_TIMEOUT_SECONDS
    )
    assert ONLINE_PROBE_MAX_DETECTION_SECONDS <= 60.0


async def test_group_reminder_requires_ack_and_uses_group_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = FakeSocket(
        [
            json.dumps(
                {
                    "status": "ok",
                    "retcode": 0,
                    "echo": "r-agent:group:job:0",
                    "data": {"message_id": 77},
                }
            )
        ]
    )
    monkeypatch.setattr("websockets.connect", lambda *args, **kwargs: FakeConnection(socket))

    message_id = await send_onebot_group_message(
        "ws://127.0.0.1:3001",
        "token",
        group_id="700001",
        text="reminder",
        idempotency_key="job:0",
    )

    assert message_id == "77"
    assert socket.sent is not None
    assert socket.sent["action"] == "send_group_msg"
    assert socket.sent["params"] == {"group_id": 700001, "message": "reminder"}
