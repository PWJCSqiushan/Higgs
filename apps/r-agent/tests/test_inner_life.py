import json
from datetime import datetime
from pathlib import Path

from r_agent.events import ConversationKind, InboundEvent
from r_agent.group_timeline import GroupTimeline, speaker_alias
from r_agent.inner_life import SHANGHAI, InnerLife, InnerLifeScheduler, InnerLifeStore

NOW = datetime(2026, 10, 29, 23, 40, tzinfo=SHANGHAI)
NOW_MS = int(NOW.timestamp() * 1000)


def ev(mid: str, sender: str, name: str, text: str, minutes_ago: int) -> InboundEvent:
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
        sender_name=name,
    )


class Client:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    async def complete_messages(self, *, messages, max_tokens=400):
        self.prompts.append(messages)
        return self.replies.pop(0)


def setup(tmp_path: Path, replies):
    timeline = GroupTimeline(tmp_path / "tl.sqlite")
    timeline.initialize()
    store = InnerLifeStore(tmp_path / "inner.sqlite")
    store.initialize()
    client = Client(replies)
    life = InnerLife(store=store, timeline=timeline, client=client, persona="我是 Higgs。")
    return life, timeline, client


def seed(timeline: GroupTimeline) -> None:
    for i in range(4):
        timeline.record_inbound(ev(f"a{i}", "800001", "小明", f"今天又调了一晚上 bug {i}", 50 - i))
    timeline.record_inbound(ev("b0", "800002", "小红", "路过", 30))
    a = ev("a0", "800001", "小明", "x", 50)
    timeline.record_outbound(
        a, text="早点睡，bug 明天再修。", provider_message_id="s1", now_ms=NOW_MS - 40 * 60_000
    )


async def test_impressions_update_only_frequent_speakers_and_filter_privacy(tmp_path: Path) -> None:
    alias = speaker_alias("900001", "700001", "800001")
    red = speaker_alias("900001", "700001", "800002")
    reply = json.dumps(
        {
            "people": [
                {"tag": f"小明#{alias}", "impression": "程序员，常熬夜修 bug，说话直接"},
                {"tag": red, "impression": "不该出现"},
            ]
        },
        ensure_ascii=False,
    )
    life, timeline, client = setup(tmp_path, [reply])
    seed(timeline)
    assert await life.update_impressions(now_ms=NOW_MS) == 1
    assert "800001" not in client.prompts[0][1]["content"]
    items = life.store.impressions_for_group("700001")
    assert [(i.display_name, i.notes) for i in items] == [
        ("小明", "程序员，常熬夜修 bug，说话直接")
    ]
    # cursor advanced: no new messages → no model call
    assert await life.update_impressions(now_ms=NOW_MS + 1000) == 0

    current = ev("c1", "800001", "小明", "@Higgs 在吗", 0)
    _title, lines = life.people_context(current, "p")
    assert "当前发言人" in lines[0] and "熬夜" in lines[0]

    life.store.upsert_impression(
        key="k", group_id="700001", display_name="x", alias="zz", notes="n"
    )
    assert life.store.forget_alias("zz") == 1


async def test_sensitive_impression_rejected(tmp_path: Path) -> None:
    alias = speaker_alias("900001", "700001", "800001")
    reply = json.dumps(
        {"people": [{"tag": alias, "impression": "手机号是 123"}]}, ensure_ascii=False
    )
    life, timeline, _ = setup(tmp_path, [reply])
    seed(timeline)
    assert await life.update_impressions(now_ms=NOW_MS) == 0


async def test_diary_mood_context_and_once_per_day(tmp_path: Path) -> None:
    reply = json.dumps(
        {
            "diary": "今天陪小明熬到很晚，看他一点点把问题找出来，挺有意思。",
            "reflections": ["熬夜不值得，但陪伴值得"],
            "mood": {"label": "安静", "valence": 0.4, "energy": 5, "note": "有点累但满足"},
        },
        ensure_ascii=False,
    )
    life, timeline, client = setup(tmp_path, [reply])
    seed(timeline)
    entry = await life.write_diary(now=NOW)
    assert entry is not None and entry.reflections == ("熬夜不值得，但陪伴值得",)
    assert "早点睡，bug 明天再修。" in client.prompts[0][1]["content"]
    mood = life.store.mood()
    assert mood.label == "安静" and mood.energy == 1.0
    assert await life.write_diary(now=NOW) is None  # already written today
    _title, lines = life.self_context(ev("x", "1", "a", "b", 0), "p")
    assert "安静" in lines[0] and "陪小明" in lines[1] and "陪伴值得" in lines[2]
    assert "心情：安静" in await life.material()
    assert "安静" in await life.handle_command("/higgs inner")
    assert "陪小明" in await life.handle_command("/higgs inner diary")


async def test_scheduler_writes_diary_after_configured_time(tmp_path: Path) -> None:
    reply = json.dumps(
        {"diary": "平平淡淡的一天。", "reflections": [], "mood": {}}, ensure_ascii=False
    )
    life, _timeline, _ = setup(tmp_path, [reply])
    scheduler = InnerLifeScheduler(life, diary_hour=23, diary_minute=30)
    await scheduler.tick(datetime(2026, 10, 29, 22, 0, tzinfo=SHANGHAI))
    assert life.store.diary() == []
    await scheduler.tick(NOW)
    assert life.store.diary()[0].text == "平平淡淡的一天。"
