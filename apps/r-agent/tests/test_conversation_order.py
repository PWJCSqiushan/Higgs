from pathlib import Path

from r_agent.conversation import ConversationStore
from r_agent.events import ConversationKind, InboundEvent


def event(message_id: str) -> InboundEvent:
    return InboundEvent(
        channel="qq",
        account_id="900001",
        sender_id="800001",
        message_id=message_id,
        occurred_at_ms=1_767_225_600_000,
        conversation_kind=ConversationKind.PRIVATE,
        conversation_id="qq:private:900001:800001",
        group_id=None,
        text=f"message-{message_id}",
        mentioned=False,
    )


def test_same_millisecond_turns_keep_insertion_order(tmp_path: Path) -> None:
    history = ConversationStore(tmp_path / "conversation.sqlite")
    history.initialize()
    for message_id in ("9", "10", "11"):
        history.record(
            event(message_id),
            principal_id="owner",
            outcome="sent",
            assistant_text=f"reply-{message_id}",
            now_ms=123,
        )

    turns = history.recent(
        channel="qq",
        account_id="900001",
        conversation_kind="private",
        conversation_id="qq:private:900001:800001",
        principal_id="owner",
        outcome="sent",
        limit=20,
    )
    assert [turn.inbound_message_id for turn in turns] == ["9", "10", "11"]
