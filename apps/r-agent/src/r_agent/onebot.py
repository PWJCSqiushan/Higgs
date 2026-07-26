"""Strict OneBot v11 message-event parser."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from r_agent.events import AttachmentRef, ConversationKind, InboundEvent


class OneBotParseError(ValueError):
    """Malformed or unsupported event."""


_MEDIA_TYPES = frozenset({"image", "record", "video", "file"})


def _digits(raw: Any, field: str) -> str:
    if isinstance(raw, bool):
        raise OneBotParseError(f"{field} must be numeric")
    if isinstance(raw, int):
        value = str(raw)
    elif isinstance(raw, str) and raw.isascii() and raw.isdigit():
        value = raw
    else:
        raise OneBotParseError(f"{field} must be numeric")
    if not value or len(value) > 20:
        raise OneBotParseError(f"{field} is out of range")
    return value


def _segments(raw: Any) -> Sequence[Mapping[str, Any]]:
    if not isinstance(raw, list):
        raise OneBotParseError("message must be an array of segments")
    if len(raw) > 256:
        raise OneBotParseError("message has too many segments")
    result: list[Mapping[str, Any]] = []
    for segment in raw:
        if not isinstance(segment, Mapping):
            raise OneBotParseError("message segment must be an object")
        result.append(segment)
    return result


def parse_message_event(payload: Mapping[str, Any]) -> InboundEvent:
    if payload.get("post_type") != "message":
        raise OneBotParseError("not a message event")

    account_id = _digits(payload.get("self_id"), "self_id")
    sender_id = _digits(payload.get("user_id"), "user_id")
    message_id = _digits(payload.get("message_id"), "message_id")
    try:
        occurred_at_ms = int(payload.get("time")) * 1000
    except (TypeError, ValueError) as exc:
        raise OneBotParseError("time must be unix seconds") from exc
    if occurred_at_ms <= 0:
        raise OneBotParseError("time must be positive")

    raw_type = payload.get("message_type")
    if raw_type == "private":
        kind = ConversationKind.PRIVATE
        group_id = None
        conversation_id = f"qq:private:{account_id}:{sender_id}"
    elif raw_type == "group":
        kind = ConversationKind.GROUP
        group_id = _digits(payload.get("group_id"), "group_id")
        conversation_id = f"qq:group:{account_id}:{group_id}"
    else:
        raise OneBotParseError("unsupported message_type")

    text_parts: list[str] = []
    attachments: list[AttachmentRef] = []
    mentioned = False
    reply_message_id: str | None = None
    for segment in _segments(payload.get("message")):
        segment_type = segment.get("type")
        data = segment.get("data")
        if not isinstance(segment_type, str) or not isinstance(data, Mapping):
            raise OneBotParseError("segment type/data is malformed")
        if segment_type == "text":
            text = data.get("text")
            if isinstance(text, str):
                text_parts.append(text)
        elif segment_type == "at":
            target = data.get("qq")
            if str(target) in {account_id, "all"}:
                mentioned = True
        elif segment_type == "reply" and reply_message_id is None:
            reply_message_id = _digits(data.get("id"), "reply.id")
        elif segment_type in _MEDIA_TYPES:
            name = data.get("file")
            safe_name = name[:255] if isinstance(name, str) else None
            attachments.append(AttachmentRef(kind=segment_type, file_name=safe_name))

    text = "".join(text_parts).strip()
    if len(text) > 16_000:
        text = text[:16_000]
    return InboundEvent(
        channel="qq",
        account_id=account_id,
        sender_id=sender_id,
        message_id=message_id,
        occurred_at_ms=occurred_at_ms,
        conversation_kind=kind,
        conversation_id=conversation_id,
        group_id=group_id,
        text=text,
        mentioned=mentioned,
        reply_message_id=reply_message_id,
        attachments=tuple(attachments),
    )
