import json

import pytest

from r_agent.events import ConversationKind, InboundEvent
from r_agent.phase2_outbound import (
    OutboundError,
    get_onebot_quoted_message,
    send_onebot_reply,
)


class FakeSocket:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = [json.dumps(item) for item in responses]
        self.sent: dict | None = None

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


def group_event() -> InboundEvent:
    return InboundEvent(
        channel="qq",
        account_id="900001",
        sender_id="800001",
        message_id="42",
        occurred_at_ms=1_767_225_600_000,
        conversation_kind=ConversationKind.GROUP,
        conversation_id="qq:group:900001:700001",
        group_id="700001",
        text="hello",
        mentioned=True,
    )


def ack(echo: str, data: dict) -> dict:
    return {"status": "ok", "retcode": 0, "echo": echo, "data": data}


async def test_group_reply_quotes_and_mentions_asker(monkeypatch: pytest.MonkeyPatch) -> None:
    socket = FakeSocket([ack("r-agent-phase2:900001:42", {"message_id": 7})])
    monkeypatch.setattr("websockets.connect", lambda *a, **k: FakeConnection(socket))
    provider_id = await send_onebot_reply(
        "ws://x", None, group_event(), "答案", quote=True, mention=True
    )
    assert provider_id == "7"
    assert socket.sent is not None
    assert socket.sent["params"]["message"] == [
        {"type": "reply", "data": {"id": "42"}},
        {"type": "at", "data": {"qq": "800001"}},
        {"type": "text", "data": {"text": " 答案"}},
    ]


async def test_group_reply_without_quote_stays_plain(monkeypatch: pytest.MonkeyPatch) -> None:
    socket = FakeSocket([ack("r-agent-phase2:900001:42", {"message_id": 7})])
    monkeypatch.setattr("websockets.connect", lambda *a, **k: FakeConnection(socket))
    await send_onebot_reply("ws://x", None, group_event(), "答案")
    assert socket.sent is not None
    assert socket.sent["params"]["message"] == "答案"


async def test_quoted_message_lookup_normalizes_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    socket = FakeSocket(
        [
            ack(
                "r-agent-phase2:get-quote:55",
                {
                    "self_id": 900001,
                    "time": 1767225600,
                    "group_id": 700001,
                    "sender": {"user_id": 800002, "nickname": "n", "card": "小红"},
                    "raw_message": "[CQ:image,url=https://secret.invalid/token]",
                    "message": [
                        {"type": "text", "data": {"text": "看这个"}},
                        {"type": "image", "data": {"file": "a.png", "url": "https://x/t"}},
                    ],
                },
            )
        ]
    )
    monkeypatch.setattr("websockets.connect", lambda *a, **k: FakeConnection(socket))
    quoted = await get_onebot_quoted_message("ws://x", None, "55")
    assert quoted.sender_id == "800002"
    assert quoted.sender_name == "小红"
    assert quoted.text == "看这个[图片]"
    assert "secret" not in quoted.text
    assert quoted.is_self is False


async def test_quoted_message_lookup_rejects_bad_ids() -> None:
    with pytest.raises(OutboundError):
        await get_onebot_quoted_message("ws://x", None, "../1")
