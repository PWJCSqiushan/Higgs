"""End-to-end M1 check: real ``listen()`` runtime against a fake NapCat."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import pytest
from napcat_sim import BOT_QQ, FakeNapCat, RecordingModel, live_env

from r_agent import phase2_cli


async def _wait_until(predicate, timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError("condition not reached")
        await asyncio.sleep(0.05)


def _text(value: str) -> dict:
    return {"type": "text", "data": {"text": value}}


def _at_bot() -> dict:
    return {"type": "at", "data": {"qq": str(BOT_QQ)}}


def _respond(call) -> str:
    system = call[0]["content"]
    if "- 发言人：小红#" in system:
        return "答小红" if "谢谢" not in call[-1]["content"] else "不客气"
    return "答小明"


def _sent_messages(napcat: FakeNapCat) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for send in napcat.sent():
        message = send["params"]["message"]
        segments = message if isinstance(message, list) else [_text(message)]
        quote = next((s["data"]["id"] for s in segments if s["type"] == "reply"), None)
        text = "".join(s["data"]["text"] for s in segments if s["type"] == "text").strip()
        result[text] = quote
    return result


@pytest.mark.asyncio
async def test_group_replies_land_on_the_right_person(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "sim.env").write_text("", encoding="utf-8")
    model = RecordingModel(responder=_respond)
    monkeypatch.setattr(phase2_cli, "_model_client", lambda *, required: model)
    async with FakeNapCat() as napcat:
        live_env(monkeypatch, data_dir=str(tmp_path), ws_url=napcat.url)
        runtime = asyncio.create_task(phase2_cli.listen())
        try:
            await asyncio.sleep(1.0)
            if runtime.done():
                raise AssertionError(repr(runtime.exception()))
            await napcat.wait_for_clients()
            await asyncio.sleep(0.3)
            # 小明 asks without @: not answered, but visible as shared context.
            await napcat.push_group_message(
                message_id=101, user_id=800001, card="小明", segments=[_text("Python 怎么读文件？")]
            )
            # 小红 and 小明 both @Higgs almost simultaneously; 小明 quotes himself.
            await napcat.push_group_message(
                message_id=102,
                user_id=800002,
                card="小红",
                segments=[_at_bot(), _text("相机怎么选？")],
            )
            await napcat.push_group_message(
                message_id=103,
                user_id=800001,
                card="小明",
                segments=[{"type": "reply", "data": {"id": "101"}}, _at_bot(), _text("帮我看看")],
            )
            await _wait_until(lambda: len(napcat.sent()) >= 2)
            await napcat.push_group_message(
                message_id=104, user_id=800002, card="小红", segments=[_at_bot(), _text("谢谢")]
            )
            await _wait_until(lambda: len(napcat.sent()) >= 3)
        finally:
            runtime.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await runtime

    systems = {call[-1]["content"]: call[0]["content"] for call in model.calls}
    red_first = next(s for user, s in systems.items() if user.endswith("相机怎么选？"))
    ming = next(s for user, s in systems.items() if user.endswith("帮我看看"))
    red_thanks = next(s for user, s in systems.items() if user.endswith("谢谢"))

    # Shared timeline: 小红's turn sees 小明's unanswered question.
    assert "Python 怎么读文件" in red_first and "- 发言人：小红#" in red_first
    # 小明's turn knows exactly what he quoted.
    assert "- 发言人：小明#" in ming
    assert "对方引用了 小明#" in ming and "Python 怎么读文件" in ming
    # Later turn sees what Higgs already said to both people.
    assert red_thanks.count("Higgs(你自己)") >= 2
    assert "答小红" in red_thanks and "答小明" in red_thanks
    for system in systems.values():
        assert "800001" not in system and "800002" not in system

    sent = _sent_messages(napcat)
    # 小红 was "interrupted" by 小明's message → quoted; the others stay plain.
    assert sent == {"答小红": "102", "答小明": None, "不客气": None}
