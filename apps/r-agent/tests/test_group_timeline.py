from dataclasses import replace
from pathlib import Path

from r_agent.events import ConversationKind, InboundEvent, QuotedMessage
from r_agent.group_timeline import (
    GroupTimeline,
    render_current,
    render_timeline,
    speaker_alias,
)

BASE = 1_767_225_600_000


def _event(message_id: str, sender: str, text: str, *, at: int, **extra) -> InboundEvent:
    return InboundEvent(
        channel="qq",
        account_id="900001",
        sender_id=sender,
        message_id=message_id,
        occurred_at_ms=BASE + at * 1000,
        conversation_kind=ConversationKind.GROUP,
        conversation_id="qq:group:900001:700001",
        group_id="700001",
        text=text,
        mentioned=False,
        **extra,
    )


def _timeline(tmp_path: Path) -> GroupTimeline:
    timeline = GroupTimeline(tmp_path / "group_timeline.sqlite", per_group_cap=100)
    timeline.initialize()
    return timeline


def test_records_all_members_and_self_in_order(tmp_path: Path) -> None:
    timeline = _timeline(tmp_path)
    a = _event("1", "800001", "今晚几点开会？", at=0, sender_name="小明")
    b = _event("2", "800002", "我觉得八点", at=5, sender_name="小红")
    assert timeline.record_inbound(a)
    assert timeline.record_inbound(b)
    assert not timeline.record_inbound(b)  # idempotent
    assert timeline.record_outbound(a, text="八点吧", provider_message_id="3", now_ms=BASE + 9000)
    entries = timeline.recent(
        channel="qq", account_id="900001", group_id="700001", until_ms=BASE + 10_000
    )
    assert [e.message_id for e in entries] == ["1", "2", "3"]
    assert entries[-1].is_self and entries[-1].reply_to_message_id == "1"


def test_private_events_are_ignored(tmp_path: Path) -> None:
    timeline = _timeline(tmp_path)
    private = replace(
        _event("1", "800001", "hi", at=0),
        conversation_kind=ConversationKind.PRIVATE,
        group_id=None,
    )
    assert not timeline.record_inbound(private)


def test_cap_and_retention(tmp_path: Path) -> None:
    timeline = _timeline(tmp_path)
    for index in range(130):
        timeline.record_inbound(_event(str(index), "800001", f"m{index}", at=index))
    entries = timeline.recent(
        channel="qq", account_id="900001", group_id="700001", until_ms=BASE + 999_000, limit=200
    )
    assert len(entries) == 100
    assert entries[0].message_id == "30"
    assert timeline.purge_expired(now_ms=BASE + 8 * 86_400_000) == 100


def test_render_labels_speakers_quotes_and_excludes_current(tmp_path: Path) -> None:
    timeline = _timeline(tmp_path)
    q1 = _event("1", "800001", "Python 怎么读文件？", at=0, sender_name="小明")
    q2 = _event("2", "800002", "相机推荐？", at=3, sender_name="小红")
    q3 = _event("3", "800003", "同问", at=4, sender_name="阿杰", reply_message_id="2")
    current = _event("4", "800001", "@Higgs 帮我看下", at=6, sender_name="小明")
    for item in (q1, q2, q3, current):
        timeline.record_inbound(item)
    entries = timeline.recent(
        channel="qq", account_id="900001", group_id="700001", until_ms=current.occurred_at_ms
    )
    lines = render_timeline(entries, current=current, owner_ids=frozenset({"800002"}))
    assert len(lines) == 3
    alias_a = speaker_alias("900001", "700001", "800001")
    assert lines[0].endswith(f"小明#{alias_a}: Python 怎么读文件？")
    assert "·主人" in lines[1]
    assert "(回复 小红#" in lines[2] and "相机推荐？" in lines[2]
    assert all("@Higgs 帮我看下" not in line for line in lines)
    assert all("800001" not in line for line in lines)  # raw QQ never rendered


def test_merged_fragments_are_not_duplicated(tmp_path: Path) -> None:
    timeline = _timeline(tmp_path)
    first = _event("1", "800001", "这个报错", at=0, sender_name="小明")
    second = _event("2", "800001", "@Higgs 怎么办", at=1, sender_name="小明")
    timeline.record_inbound(first)
    timeline.record_inbound(second)
    merged = replace(second, text="这个报错\n怎么办", merged_message_ids=("1",))
    entries = timeline.recent(
        channel="qq", account_id="900001", group_id="700001", until_ms=second.occurred_at_ms
    )
    assert render_timeline(entries, current=merged, owner_ids=frozenset()) == []


def test_render_budget_keeps_newest(tmp_path: Path) -> None:
    timeline = _timeline(tmp_path)
    for index in range(40):
        timeline.record_inbound(_event(str(index), "800002", "长" * 150, at=index))
    current = _event("99", "800001", "?", at=100)
    entries = timeline.recent(
        channel="qq",
        account_id="900001",
        group_id="700001",
        until_ms=current.occurred_at_ms,
        limit=40,
    )
    lines = render_timeline(entries, current=current, owner_ids=frozenset(), max_chars=1_000)
    assert 0 < len(lines) < 40
    assert sum(len(line) + 1 for line in lines) <= 1_000


def test_others_after_counts_interleaving(tmp_path: Path) -> None:
    timeline = _timeline(tmp_path)
    target = _event("1", "800001", "问题", at=0)
    timeline.record_inbound(target)
    timeline.record_inbound(_event("2", "800001", "补充", at=1))
    assert timeline.others_after(target, sender_id="800001") == 0
    timeline.record_inbound(_event("3", "800002", "插话", at=2))
    assert timeline.others_after(target, sender_id="800001") == 1


def test_render_current_describes_quote() -> None:
    event = _event(
        "5",
        "800001",
        "这个对吗",
        at=0,
        sender_name="小明",
        quoted=QuotedMessage(message_id="2", sender_id="900001", sender_name=None, text="八点"),
    )
    lines = render_current(event, owner_ids=frozenset())
    assert lines[0].startswith("- 发言人：小明#")
    assert "Higgs(你自己)" in lines[1] and "八点" in lines[1]
