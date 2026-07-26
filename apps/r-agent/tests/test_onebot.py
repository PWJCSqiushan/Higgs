import json
from pathlib import Path

import pytest

from r_agent.events import ConversationKind
from r_agent.onebot import OneBotParseError, parse_message_event


def test_parse_sanitized_private_fixture() -> None:
    path = Path(__file__).parent / "fixtures" / "onebot_private_message.json"
    event = parse_message_event(json.loads(path.read_text(encoding="utf-8")))
    assert event.channel == "qq"
    assert event.conversation_kind is ConversationKind.PRIVATE
    assert event.text == "这是一条完全脱敏的回放消息"
    assert event.group_id is None


def test_mentions_and_media_are_normalized_without_remote_url() -> None:
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
                {"type": "at", "data": {"qq": "900001"}},
                {"type": "text", "data": {"text": "你好"}},
                {
                    "type": "image",
                    "data": {
                        "file": "safe.png",
                        "url": "https://example.invalid/private-token",
                    },
                },
            ],
        }
    )
    assert event.mentioned is True
    assert event.attachments[0].file_name == "safe.png"
    assert not hasattr(event.attachments[0], "url")


def test_reply_segment_is_normalized_without_trusting_its_sender() -> None:
    event = parse_message_event(
        {
            "time": 1767225600,
            "self_id": 900001,
            "post_type": "message",
            "message_type": "group",
            "group_id": 700001,
            "message_id": 2,
            "user_id": 800001,
            "message": [
                {"type": "reply", "data": {"id": "42"}},
                {"type": "text", "data": {"text": "继续"}},
            ],
        }
    )
    assert event.reply_message_id == "42"
    assert event.replied_to_account is False


def test_rejects_non_message_event() -> None:
    with pytest.raises(OneBotParseError):
        parse_message_event({"post_type": "meta_event"})
