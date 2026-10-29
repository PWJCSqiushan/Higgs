import asyncio
import contextlib
from pathlib import Path

import pytest
from napcat_sim import BOT_QQ, OWNER_QQ, FakeNapCat, RecordingModel, live_env

from r_agent import phase2_cli
from r_agent.events import ConversationKind, InboundEvent
from r_agent.multimodal import MSG_BREAK, VisionCaptioner, split_bubbles, strip_breaks
from r_agent.onebot import parse_message_event


def test_split_bubbles_bounds() -> None:
    assert split_bubbles("一[MSG_BREAK] 二 [MSG_BREAK][MSG_BREAK]三") == ["一", "二", "三"]
    assert split_bubbles(MSG_BREAK.join("abcde")) == ["a", "b", "c\nd\ne"]
    long = ("句子。" * 400).strip()
    parts = split_bubbles(long, max_chars=500)
    assert all(len(p) <= 500 for p in parts) and "".join(parts) == long
    assert strip_breaks("a [MSG_BREAK] b") == "a\nb"
    assert split_bubbles("  [MSG_BREAK] ") == []


def test_parser_keeps_image_urls_transiently() -> None:
    event = parse_message_event(
        {
            "time": 1767225600,
            "self_id": 900001,
            "post_type": "message",
            "message_type": "group",
            "group_id": 700001,
            "message_id": 1,
            "user_id": 800001,
            "message": [
                {"type": "image", "data": {"file": "a.jpg", "url": "https://cdn.example/a?rkey=x"}},
                {"type": "image", "data": {"file": "b.jpg", "url": "http://insecure/b"}},
            ],
        }
    )
    assert event.image_urls == ("https://cdn.example/a?rkey=x",)
    assert event.display_text == "[图片][图片]"


async def test_annotate_folds_caption_into_text(monkeypatch: pytest.MonkeyPatch) -> None:
    captioner = VisionCaptioner(base_url="https://v.example", model="m", api_key="k", daily_limit=1)
    monkeypatch.setattr(
        VisionCaptioner, "_fetch_data_url", lambda self, url: "data:image/png;base64,AA"
    )
    monkeypatch.setattr(VisionCaptioner, "_ask", lambda self, data_url: "一只橘猫趴在键盘上")
    event = InboundEvent(
        channel="qq",
        account_id="1",
        sender_id="2",
        message_id="3",
        occurred_at_ms=1,
        conversation_kind=ConversationKind.GROUP,
        conversation_id="c",
        group_id="g",
        text="看",
        mentioned=True,
        display_text="看[图片]",
        image_urls=("https://a", "https://b"),
    )
    annotated, captions = await captioner.annotate(event)
    assert captions == ["一只橘猫趴在键盘上"]  # daily limit 1 → second image skipped
    assert annotated.display_text == "看[图片：一只橘猫趴在键盘上]"
    assert annotated.text.endswith("（图片内容：一只橘猫趴在键盘上）")
    assert annotated.image_urls == ()


async def _wait_until(predicate, timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError("condition not reached")
        await asyncio.sleep(0.05)


def _respond(call):
    if "图片：一只橘猫" in call[0]["content"] + call[-1]["content"]:
        return "好胖的猫。[MSG_BREAK]它是不是又踩你键盘了"
    if "/higgs" in call[-1]["content"]:
        return "不应该到这里"
    return "嗯"


@pytest.mark.asyncio
async def test_caption_and_multi_bubble_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "sim.env").write_text("", encoding="utf-8")
    model = RecordingModel(responder=_respond)
    monkeypatch.setattr(phase2_cli, "_model_client", lambda *, required: model)

    async def fake_caption(self, url):
        return "一只橘猫趴在键盘上"

    monkeypatch.setattr(VisionCaptioner, "caption", fake_caption)
    async with FakeNapCat() as napcat:
        live_env(monkeypatch, data_dir=str(tmp_path), ws_url=napcat.url)
        monkeypatch.setenv("R_AGENT_VISION_ENABLED", "true")
        monkeypatch.setenv("R_AGENT_QZONE_MODE", "off")
        runtime = asyncio.create_task(phase2_cli.listen())
        try:
            await napcat.wait_for_clients()
            await asyncio.sleep(0.3)
            await napcat.push_group_message(
                message_id=501,
                user_id=800001,
                card="小明",
                segments=[
                    {"type": "at", "data": {"qq": str(BOT_QQ)}},
                    {"type": "text", "data": {"text": "看我家猫"}},
                    {"type": "image", "data": {"file": "c.jpg", "url": "https://cdn.example/c"}},
                ],
            )
            await _wait_until(lambda: len(napcat.sent()) >= 2)
            await napcat.push_private_message(
                message_id=502, user_id=OWNER_QQ, text="/higgs overview"
            )
            await _wait_until(lambda: len(napcat.sent("send_private_msg")) >= 1)
        finally:
            runtime.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await runtime
    first, second = napcat.sent()[:2]
    first_text = (
        "".join(
            s["data"].get("text", "") for s in first["params"]["message"] if s["type"] == "text"
        )
        if isinstance(first["params"]["message"], list)
        else first["params"]["message"]
    )
    assert first_text.strip() == "好胖的猫。"
    assert second["params"]["message"] == "它是不是又踩你键盘了"
    overview = napcat.sent("send_private_msg")[0]["params"]["message"]
    assert "Higgs 3.0 总览" in overview and "看图：开" in overview
