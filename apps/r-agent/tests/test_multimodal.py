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


async def test_caption_falls_back_to_url(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []
    monkeypatch.setattr(VisionCaptioner, "_fetch_data_url", lambda self, url: None)
    monkeypatch.setattr(VisionCaptioner, "_ask", lambda self, ref: seen.append(ref) or "猫")
    captioner = VisionCaptioner(base_url="https://v", model="m", api_key="k")
    assert await captioner.caption("https://cdn.example/x") == "猫"
    assert seen == ["https://cdn.example/x"]
    captioner.url_fallback = False
    assert await captioner.caption("https://cdn.example/y") is None


def test_recent_image_cache_freshness_and_exclusions() -> None:
    from dataclasses import replace

    from r_agent.multimodal import RecentImageCache

    base = InboundEvent(
        channel="qq",
        account_id="1",
        sender_id="2",
        message_id="10",
        occurred_at_ms=1,
        conversation_kind=ConversationKind.GROUP,
        conversation_id="c",
        group_id="g",
        text="",
        mentioned=False,
        image_urls=("https://a",),
    )
    cache = RecentImageCache(max_age_seconds=60)
    cache.remember(base, now=0)
    later = replace(base, message_id="11", text="这是什么", image_urls=())
    assert cache.take(replace(later, merged_message_ids=("10",)), now=5) is None
    assert cache.take(later, now=5) == ("10", ("https://a",))
    assert cache.take(later, now=6) is None  # consumed once
    cache.remember(base, now=0)
    assert cache.take(later, now=120) is None  # expired
    other = replace(later, sender_id="3")
    cache.remember(base, now=0)
    assert cache.take(other, now=1) is None  # different sender


def _image_brain(call):
    joined = call[0]["content"] + call[-1]["content"]
    if "被引用的图片内容：一只橘猫" in joined and "[图片：一只橘猫" in joined:
        return "引用的是橘猫"
    if "对方刚才发的图片内容：一只橘猫" in joined:
        return "刚才那张是橘猫"
    return "看不到图"


@pytest.mark.asyncio
async def test_quoted_and_separately_sent_images_are_captioned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "sim.env").write_text("", encoding="utf-8")
    model = RecordingModel(responder=_image_brain)
    monkeypatch.setattr(phase2_cli, "_model_client", lambda *, required: model)
    seen_urls = []

    async def fake_caption(self, url):
        seen_urls.append(url)
        return "一只橘猫趴在键盘上"

    monkeypatch.setattr(VisionCaptioner, "caption", fake_caption)
    image = {"type": "image", "data": {"file": "c.jpg", "url": "https://cdn.example/c"}}
    async with FakeNapCat() as napcat:
        live_env(monkeypatch, data_dir=str(tmp_path), ws_url=napcat.url)
        monkeypatch.setenv("R_AGENT_VISION_ENABLED", "true")
        monkeypatch.setenv("R_AGENT_QZONE_MODE", "off")
        monkeypatch.setenv("R_AGENT_INTEREST_ENABLED", "false")
        runtime = asyncio.create_task(phase2_cli.listen())
        try:
            await napcat.wait_for_clients()
            await asyncio.sleep(0.3)
            # 1) image alone, later someone quotes it and @Higgs
            await napcat.push_group_message(
                message_id=601, user_id=800001, card="小明", segments=[image]
            )
            await asyncio.sleep(1.0)
            await napcat.push_group_message(
                message_id=602,
                user_id=800002,
                card="小红",
                segments=[
                    {"type": "reply", "data": {"id": "601"}},
                    {"type": "at", "data": {"qq": str(BOT_QQ)}},
                    {"type": "text", "data": {"text": "这是什么"}},
                ],
            )
            await _wait_until(lambda: len(napcat.sent()) >= 1)
            # 2) image, then a separate @Higgs message from the same person
            await napcat.push_group_message(
                message_id=603, user_id=800003, card="阿杰", segments=[image]
            )
            await asyncio.sleep(1.0)
            await napcat.push_group_message(
                message_id=604,
                user_id=800003,
                card="阿杰",
                segments=[
                    {"type": "at", "data": {"qq": str(BOT_QQ)}},
                    {"type": "text", "data": {"text": "帮我看看"}},
                ],
            )
            await _wait_until(lambda: len(napcat.sent()) >= 2)
        finally:
            runtime.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await runtime
    texts = []
    for item in napcat.sent():
        message = item["params"]["message"]
        texts.append(
            message
            if isinstance(message, str)
            else "".join(s["data"].get("text", "") for s in message if s["type"] == "text").strip()
        )
    assert texts == ["引用的是橘猫", "刚才那张是橘猫"]
    assert seen_urls == ["https://cdn.example/c", "https://cdn.example/c"]
    for call in model.calls:
        assert "cdn.example" not in call[0]["content"] + call[-1]["content"]


@pytest.mark.asyncio
async def test_reply_to_higgs_still_triggers_with_vision_on_and_timeline_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the image cache must not swallow natural-trigger reply-author lookup."""
    (tmp_path / "sim.env").write_text("", encoding="utf-8")
    model = RecordingModel(["接着说。"])
    monkeypatch.setattr(phase2_cli, "_model_client", lambda *, required: model)
    async with FakeNapCat() as napcat:
        live_env(monkeypatch, data_dir=str(tmp_path), ws_url=napcat.url)
        monkeypatch.setenv("R_AGENT_VISION_ENABLED", "true")
        monkeypatch.setenv("R_AGENT_GROUP_TIMELINE_ENABLED", "false")
        monkeypatch.setenv("R_AGENT_REPLY_NATURAL_TRIGGER_GROUPS", "700001")
        monkeypatch.setenv("R_AGENT_INTEREST_ENABLED", "false")
        monkeypatch.setenv("R_AGENT_QZONE_MODE", "off")
        # A previous Higgs message the member will reply to (no @, no trigger term).
        napcat.messages[777] = {
            "self_id": BOT_QQ,
            "user_id": BOT_QQ,
            "time": 1,
            "group_id": 700001,
            "sender": {"user_id": BOT_QQ, "nickname": "Higgs"},
            "message": [{"type": "text", "data": {"text": "之前的话"}}],
        }
        runtime = asyncio.create_task(phase2_cli.listen())
        try:
            await napcat.wait_for_clients()
            await asyncio.sleep(0.3)
            await napcat.push_group_message(
                message_id=778,
                user_id=800001,
                card="小明",
                segments=[
                    {"type": "reply", "data": {"id": "777"}},
                    {"type": "text", "data": {"text": "然后呢"}},
                ],
            )
            await _wait_until(lambda: len(napcat.sent()) >= 1)
        finally:
            runtime.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await runtime
    assert napcat.sent("get_msg")
    assert len(napcat.sent()) == 1
