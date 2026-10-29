import asyncio
import contextlib
import random
from datetime import datetime
from pathlib import Path

import pytest
from napcat_sim import OWNER_QQ, FakeNapCat, RecordingModel, live_env

from r_agent import phase2_cli, willingness
from r_agent.events import ConversationKind, InboundEvent
from r_agent.group_timeline import GroupTimeline
from r_agent.willingness import (
    SHANGHAI,
    InterestFeatures,
    InterestGate,
    ProactiveChatter,
    interest_probability,
    is_react,
    is_skip,
)

NOW = datetime(2026, 10, 29, 15, 0, tzinfo=SHANGHAI)
NOW_MS = int(NOW.timestamp() * 1000)


def ev(mid, sender, text, *, minutes_ago=0, mentioned_ids=()):
    return InboundEvent(
        channel="qq",
        account_id="900001",
        sender_id=sender,
        message_id=mid,
        occurred_at_ms=NOW_MS - minutes_ago * 60_000,
        conversation_kind=ConversationKind.GROUP,
        conversation_id="qq:group:900001:700001",
        group_id="700001",
        text=text,
        mentioned=False,
        sender_name="群友",
        mentioned_ids=mentioned_ids,
    )


class Always(random.Random):
    def random(self):
        return 0.0


def base(**kw):
    values = dict(
        mentions_name=False,
        has_question=False,
        mentions_other=False,
        media_only=False,
        self_ratio=0.0,
        seconds_since_self=86_400,
        pending_messages=1,
    )
    values.update(kw)
    return InterestFeatures(**values)


def test_probability_shape() -> None:
    idle = interest_probability(base())
    assert idle < 0.05
    assert interest_probability(base(mentions_name=True, has_question=True)) > 0.4
    assert interest_probability(base(mentions_other=True)) < idle
    assert interest_probability(base(self_ratio=0.5, seconds_since_self=30)) > idle * 3
    assert is_skip("SKIP。") and is_react(" react ") and not is_skip("skip一下")


def test_gate_caps_and_scope(tmp_path: Path) -> None:
    timeline = GroupTimeline(tmp_path / "t.sqlite")
    timeline.initialize()
    gate = InterestGate(
        timeline=timeline,
        groups=frozenset({"700001"}),
        rng=Always(),
        hourly_cap=2,
        min_gap_seconds=60,
    )
    assert gate.should_interject(ev("1", "800001", "x"), now=0)
    assert not gate.should_interject(ev("2", "800001", "x"), now=30)  # min gap
    assert gate.should_interject(ev("3", "800001", "x"), now=100)
    assert not gate.should_interject(ev("4", "800001", "x"), now=200)  # hourly cap
    assert not gate.should_interject(ev("5", "800001", "/higgs status"), now=9_999)
    other = ev("6", "800001", "x")
    object.__setattr__(other, "group_id", "1")
    assert not gate.should_interject(other, now=9_999)
    features = gate.features(ev("7", "800001", "Higgs 你觉得呢？", mentioned_ids=("1",)))
    assert features.mentions_name and features.has_question and features.mentions_other


class Client:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    async def complete_messages(self, *, messages, max_tokens=400):
        self.calls.append(messages)
        return self.reply


async def test_proactive_chatter(tmp_path: Path) -> None:
    timeline = GroupTimeline(tmp_path / "t.sqlite")
    timeline.initialize()
    timeline.record_inbound(ev("1", "800001", "今天降温了", minutes_ago=120))
    sent = []

    async def send(group_id, text):
        sent.append((group_id, text))
        return "9001"

    client = Client("降温了正好看星星，空气透。")
    chatter = ProactiveChatter(
        timeline=timeline,
        client=client,
        persona="我是 Higgs。",
        send_group=send,
        account_id="900001",
        groups=frozenset({"700001"}),
        rng=Always(),
        daily_cap=1,
    )
    assert await chatter.tick(NOW) == ["700001"]
    assert sent == [("700001", "降温了正好看星星，空气透。")]
    assert "今天降温了" in client.calls[0][0]["content"]
    assert timeline.recent(
        channel="qq", account_id="900001", group_id="700001", until_ms=NOW_MS + 1
    )[-1].is_self
    # last message is Higgs's own → silent; daily cap also reached
    assert await chatter.tick(NOW) == []
    assert await chatter.tick(datetime(2026, 10, 29, 3, 0, tzinfo=SHANGHAI)) == []


async def test_proactive_skip(tmp_path: Path) -> None:
    timeline = GroupTimeline(tmp_path / "t.sqlite")
    timeline.initialize()
    timeline.record_inbound(ev("1", "800001", "嗯", minutes_ago=200))

    async def send(group_id, text):
        raise AssertionError("must not send")

    chatter = ProactiveChatter(
        timeline=timeline,
        client=Client("SKIP"),
        persona="p",
        send_group=send,
        account_id="900001",
        groups=frozenset({"700001"}),
        rng=Always(),
    )
    assert await chatter.tick(NOW) == []


async def _wait_until(predicate, timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError("condition not reached")
        await asyncio.sleep(0.05)


def _respond(call):
    user = call[-1]["content"]
    if "这条消息没有直接叫你" not in call[0]["content"]:
        return "直接回答"
    if "相机" in user:
        return "我拍星空用的是广角，先看镜头。"
    if "哈哈" in user:
        return "REACT"
    return "SKIP"


@pytest.mark.asyncio
async def test_interjection_reply_react_and_skip_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "sim.env").write_text("", encoding="utf-8")
    model = RecordingModel(responder=_respond)
    monkeypatch.setattr(phase2_cli, "_model_client", lambda *, required: model)
    monkeypatch.setattr(willingness, "interest_probability", lambda features: 1.0)
    async with FakeNapCat() as napcat:
        live_env(monkeypatch, data_dir=str(tmp_path), ws_url=napcat.url)
        monkeypatch.setenv("R_AGENT_QZONE_MODE", "off")
        monkeypatch.setenv("R_AGENT_INTEREST_MIN_GAP_SECONDS", "0")
        runtime = asyncio.create_task(phase2_cli.listen())
        try:
            await napcat.wait_for_clients()
            await asyncio.sleep(0.3)
            texts = [
                (401, 800001, "有人懂相机吗"),
                (402, 800002, "哈哈哈哈"),
                (403, 800003, "吃饭去了"),
            ]
            for mid, uid, text in texts:
                await napcat.push_group_message(
                    message_id=mid,
                    user_id=uid,
                    card=f"u{uid}",
                    segments=[{"type": "text", "data": {"text": text}}],
                )
                await asyncio.sleep(0.8)
            await _wait_until(lambda: len(model.calls) >= 3)
            await asyncio.sleep(0.5)
            await napcat.push_private_message(message_id=404, user_id=OWNER_QQ, text="在吗")
            await _wait_until(lambda: len(napcat.sent("send_private_msg")) >= 1)
        finally:
            runtime.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await runtime
    group_texts = [
        "".join(s["data"].get("text", "") for s in m["params"]["message"] if s["type"] == "text")
        if isinstance(m["params"]["message"], list)
        else m["params"]["message"]
        for m in napcat.sent()
    ]
    assert group_texts == ["我拍星空用的是广角，先看镜头。"]
    likes = napcat.sent("set_msg_emoji_like")
    assert [like["params"]["message_id"] for like in likes] == ["402"]
    assert napcat.sent("set_input_status")[0]["params"]["user_id"] == str(OWNER_QQ)
