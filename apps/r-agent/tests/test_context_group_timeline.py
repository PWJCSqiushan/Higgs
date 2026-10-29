from pathlib import Path

from r_agent.context import ContextBuilder
from r_agent.conversation import ConversationStore
from r_agent.events import ConversationKind, InboundEvent, QuotedMessage
from r_agent.group_timeline import GroupTimeline
from r_agent.memory import MemoryStore
from r_agent.recall import RecallLedger

BASE = 1_767_225_600_000


def _event(message_id: str, sender: str, name: str, text: str, at: int, **extra) -> InboundEvent:
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
        mentioned=True,
        sender_name=name,
        **extra,
    )


def _builder(tmp_path: Path, timeline: GroupTimeline | None) -> ContextBuilder:
    history = ConversationStore(tmp_path / "conversation.sqlite")
    history.initialize()
    memory = MemoryStore(tmp_path / "memory.sqlite")
    memory.initialize()
    recall = RecallLedger(tmp_path / "memory.sqlite")
    recall.initialize()
    return ContextBuilder(
        history=history,
        memory=memory,
        recall=recall,
        persona="你是 Higgs。",
        group_timeline=timeline,
        owner_ids=frozenset({"800009"}),
    )


def test_group_context_shows_shared_timeline_and_targets_current_speaker(tmp_path: Path) -> None:
    timeline = GroupTimeline(tmp_path / "group_timeline.sqlite")
    timeline.initialize()
    a = _event("1", "800001", "小明", "Python 怎么读文件", 0)
    b = _event("2", "800002", "小红", "有人知道相机怎么选吗", 3)
    timeline.record_inbound(a)
    timeline.record_inbound(b)
    timeline.record_outbound(a, text="用 open() 就行", provider_message_id="3", now_ms=BASE + 4000)
    current = _event(
        "4",
        "800002",
        "小红",
        "预算五千",
        6,
        display_text="@Higgs 预算五千",
        quoted=QuotedMessage("2", "800002", "小红", "有人知道相机怎么选吗"),
    )
    timeline.record_inbound(current)
    context = _builder(tmp_path, timeline).build(current, principal_id="p-red")
    system = context.messages[0]["content"]
    assert "# 群聊近况" in system
    assert "小明#" in system and "Python 怎么读文件" in system
    assert "Higgs(你自己)" in system and "用 open() 就行" in system
    assert "- 发言人：小红#" in system
    assert "对方引用了 小红#" in system
    assert "800001" not in system and "800002" not in system
    user = context.messages[-1]
    assert user["role"] == "user"
    assert user["content"].startswith("小红#") and user["content"].endswith("@Higgs 预算五千")


def test_without_timeline_group_context_is_unchanged(tmp_path: Path) -> None:
    current = _event("4", "800002", "小红", "预算五千", 6)
    context = _builder(tmp_path, None).build(current, principal_id="p-red")
    assert "# 群聊近况" not in context.messages[0]["content"]
    assert context.messages[-1]["content"] == "预算五千"


def test_private_events_ignore_timeline(tmp_path: Path) -> None:
    timeline = GroupTimeline(tmp_path / "group_timeline.sqlite")
    timeline.initialize()
    private = InboundEvent(
        channel="qq",
        account_id="900001",
        sender_id="800001",
        message_id="9",
        occurred_at_ms=BASE,
        conversation_kind=ConversationKind.PRIVATE,
        conversation_id="qq:private:900001:800001",
        group_id=None,
        text="你好",
        mentioned=False,
    )
    context = _builder(tmp_path, timeline).build(private, principal_id="p")
    assert "# 群聊近况" not in context.messages[0]["content"]
    assert context.messages[-1]["content"] == "你好"
