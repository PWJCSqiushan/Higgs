import json

import pytest

from r_agent.events import ConversationKind, InboundEvent
from r_agent.phase2_outbound import (
    OutboundError,
    get_onebot_account_status,
    get_onebot_message_sender,
    send_onebot_group_message,
    send_onebot_reply,
)


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
