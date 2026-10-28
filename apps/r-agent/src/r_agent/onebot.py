"""Strict OneBot v11 message-event parser."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from r_agent.events import AttachmentRef, ConversationKind, InboundEvent


class OneBotParseError(ValueError):
    """Malformed or unsupported event."""


_MEDIA_TYPES = frozenset({"image", "record", "video", "file"})
_PLACEHOLDERS = {
    "image": "[图片]",
    "record": "[语音]",
    "video": "[视频]",
    "file": "[文件]",
    "face": "[表情]",
    "mface": "[表情包]",
    "forward": "[合并转发]",
    "json": "[卡片消息]",
    "xml": "[卡片消息]",
    "poke": "[戳一戳]",
    "dice": "[骰子]",
    "rps": "[猜拳]",
    "markdown": "[富文本]",
}
_NAME_LIMIT = 32


def clean_display_name(raw: Any) -> str | None:
    """Return a single-line, bounded display name or ``None``.

    Group cards and nicknames are attacker-controlled; they are rendered as
    data only, so we merely strip control characters and bound the length.
    """
    if not isinstance(raw, str):
        return None
    cleaned = "".join(char if char.isprintable() else " " for char in raw)
    cleaned = " ".join(cleaned.split())
    for forbidden in ("<", ">", "[", "]"):
        cleaned = cleaned.replace(forbidden, "")
    cleaned = cleaned.strip()
    if not cleaned:
        return None
    return cleaned[:_NAME_LIMIT]


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

    sender = payload.get("sender")
    sender_name: str | None = None
    if isinstance(sender, Mapping):
        sender_name = clean_display_name(sender.get("card")) or clean_display_name(
            sender.get("nickname")
        )

    text_parts: list[str] = []
    display_parts: list[str] = []
    attachments: list[AttachmentRef] = []
    mentioned = False
    mentioned_ids: list[str] = []
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
                display_parts.append(text)
        elif segment_type == "at":
            target = str(data.get("qq"))
            if target in {account_id, "all"}:
                mentioned = True
            label = clean_display_name(data.get("name"))
            if target == "all":
                display_parts.append("@全体成员 ")
            elif target == account_id:
                display_parts.append("@Higgs ")
            else:
                if target.isascii() and target.isdigit() and len(target) <= 20:
                    if target not in mentioned_ids and len(mentioned_ids) < 16:
                        mentioned_ids.append(target)
                display_parts.append(f"@{label or '某人'} ")
        elif segment_type == "reply" and reply_message_id is None:
            reply_message_id = _digits(data.get("id"), "reply.id")
        elif segment_type in _MEDIA_TYPES:
            name = data.get("file")
            safe_name = name[:255] if isinstance(name, str) else None
            attachments.append(AttachmentRef(kind=segment_type, file_name=safe_name))
            display_parts.append(_PLACEHOLDERS[segment_type])
        elif segment_type in _PLACEHOLDERS:
            display_parts.append(_PLACEHOLDERS[segment_type])

    text = "".join(text_parts).strip()
    if len(text) > 16_000:
        text = text[:16_000]
    display_text = " ".join("".join(display_parts).split()).strip()[:4_000]
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
        sender_name=sender_name,
        mentioned_ids=tuple(mentioned_ids),
        display_text=display_text or None,
    )
