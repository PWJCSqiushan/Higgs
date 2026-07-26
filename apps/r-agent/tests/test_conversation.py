from pathlib import Path

import pytest

from r_agent.conversation import (
    ConversationConflictError,
    ConversationStore,
)
from r_agent.events import ConversationKind, InboundEvent


def event(message_id: str, text: str = "hello") -> InboundEvent:
    return InboundEvent(
        channel="qq",
        account_id="900001",
        sender_id="800001",
        message_id=message_id,
        occurred_at_ms=1_767_225_600_000 + int(message_id),
        conversation_kind=ConversationKind.PRIVATE,
        conversation_id="qq:private:900001:800001",
        group_id=None,
        text=text,
        mentioned=False,
    )


def store(tmp_path: Path) -> ConversationStore:
    result = ConversationStore(tmp_path / "conversation.sqlite")
    result.initialize()
    return result


def test_recent_history_is_scoped_ordered_and_outcome_specific(tmp_path: Path) -> None:
    history = store(tmp_path)
    history.record(
        event("1", "first"),
        principal_id="owner",
        outcome="sent",
        assistant_text="one",
        now_ms=100,
    )
    history.record(
        event("2", "failed"),
        principal_id="owner",
        outcome="send_failed",
        assistant_text="ghost reply",
        now_ms=200,
    )
    history.record(
        event("3", "second"),
        principal_id="owner",
        outcome="sent",
        assistant_text="two",
        now_ms=300,
    )

    recent = history.recent(
        channel="qq",
        account_id="900001",
        conversation_kind="private",
        conversation_id="qq:private:900001:800001",
        principal_id="owner",
        outcome="sent",
        limit=8,
    )
    assert [(turn.user_text, turn.assistant_text) for turn in recent] == [
        ("first", "one"),
        ("second", "two"),
    ]
    assert (
        history.recent(
            channel="qq",
            account_id="900001",
            conversation_kind="private",
            conversation_id="qq:private:900001:800001",
            principal_id="other",
            outcome="sent",
        )
        == []
    )


def test_draft_history_never_leaks_into_live_history(tmp_path: Path) -> None:
    history = store(tmp_path)
    history.record(
        event("1"),
        principal_id="owner",
        outcome="drafted",
        assistant_text="draft only",
    )
    common = {
        "channel": "qq",
        "account_id": "900001",
        "conversation_kind": "private",
        "conversation_id": "qq:private:900001:800001",
        "principal_id": "owner",
    }
    assert [item.assistant_text for item in history.recent(**common, outcome="drafted")] == [
        "draft only"
    ]
    assert history.recent(**common, outcome="sent") == []


def test_same_message_is_idempotent_but_conflicting_outcome_fails(tmp_path: Path) -> None:
    history = store(tmp_path)
    first = history.record(
        event("1"),
        principal_id="owner",
        outcome="sent",
        assistant_text="reply",
    )
    second = history.record(
        event("1"),
        principal_id="owner",
        outcome="sent",
        assistant_text="reply",
    )
    assert second.turn_id == first.turn_id
    with pytest.raises(ConversationConflictError):
        history.record(
            event("1"),
            principal_id="owner",
            outcome="send_failed",
            assistant_text="reply",
        )


def test_retention_and_principal_delete_remove_plaintext(tmp_path: Path) -> None:
    history = store(tmp_path)
    history.record(
        event("1"),
        principal_id="owner",
        outcome="sent",
        assistant_text="old reply",
        now_ms=0,
    )
    assert history.purge_expired(7, now_ms=8 * 86_400_000) == 1
    history.record(
        event("2"),
        principal_id="owner",
        outcome="sent",
        assistant_text="private reply",
    )
    assert history.delete_principal("owner") == 1
