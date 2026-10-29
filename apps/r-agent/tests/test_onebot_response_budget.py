import json

import pytest

from r_agent.phase2_outbound import (
    QZONE_RESPONSE_BYTES,
    OutboundError,
    _wait_for_action_response,
    call_onebot_action,
)


class Socket:
    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = None

    async def send(self, raw):
        self.sent = json.loads(raw)

    async def recv(self):
        return self.frames.pop(0)


class Conn:
    def __init__(self, socket, record):
        self.socket, self.record = socket, record

    async def __aenter__(self):
        return self.socket

    async def __aexit__(self, *a):
        return None


def big_response(echo: str, approx_bytes: int) -> str:
    feed = {"cell_summary": {"summary": [{"content": "银河" * 50}]}}
    count = approx_bytes // len(json.dumps(feed, ensure_ascii=False).encode()) + 1
    return json.dumps(
        {"status": "ok", "retcode": 0, "echo": echo, "data": {"feeds": [feed] * count}},
        ensure_ascii=False,
    )


async def test_large_legal_response_within_budget_is_returned() -> None:
    raw = big_response("e1", 200_000)
    assert len(raw.encode()) > 190_000 and len(raw) < len(raw.encode())  # CJK: bytes > chars
    unrelated = json.dumps({"post_type": "message", "x": "y" * 100_000})
    socket = Socket([unrelated, raw])
    response = await _wait_for_action_response(socket, echo="e1", max_bytes=QZONE_RESPONSE_BYTES)
    assert len(response["data"]["feeds"]) > 100


async def test_over_budget_echo_fails_fast_not_timeout() -> None:
    raw = big_response("e2", 80_000)
    with pytest.raises(OutboundError, match="size budget"):
        await _wait_for_action_response(Socket([raw]), echo="e2", max_bytes=64 * 1024)


async def test_budget_counts_utf8_bytes_not_characters() -> None:
    body = json.dumps(
        {"status": "ok", "retcode": 0, "echo": "e3", "data": "汉" * 30_000}, ensure_ascii=False
    )
    assert len(body) < 64 * 1024 < len(body.encode())
    with pytest.raises(OutboundError, match="size budget"):
        await _wait_for_action_response(Socket([body]), echo="e3", max_bytes=64 * 1024)


async def test_oversized_unrelated_frames_are_ignored() -> None:
    junk = json.dumps({"post_type": "message", "x": "y" * 100_000})
    ok = json.dumps({"status": "ok", "retcode": 0, "echo": "e4", "data": {}})
    response = await _wait_for_action_response(Socket([junk, ok]), echo="e4", max_bytes=64 * 1024)
    assert response["echo"] == "e4"


async def test_call_onebot_action_passes_budget_to_reader(monkeypatch) -> None:
    seen = {}
    raw = big_response("r-agent:qzone:x", 200_000)
    socket = Socket([raw])

    def connect(*args, **kwargs):
        seen.update(kwargs)
        return Conn(socket, seen)

    monkeypatch.setattr("websockets.connect", connect)
    response = await call_onebot_action(
        "ws://x",
        None,
        action="get_qzone_public_feeds",
        params={},
        echo="r-agent:qzone:x",
        max_size=QZONE_RESPONSE_BYTES,
        timeout_seconds=20,
    )
    assert response["data"]["feeds"]
    assert seen["max_size"] > QZONE_RESPONSE_BYTES
