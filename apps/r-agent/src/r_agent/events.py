"""Transport-neutral event vocabulary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ConversationKind(StrEnum):
    PRIVATE = "private"
    GROUP = "group"


@dataclass(frozen=True, slots=True)
class AttachmentRef:
    """Non-secret attachment metadata; remote URLs are deliberately omitted.

    Local paths and remote URLs are intentionally absent.  A trusted ingress
    binds an opaque ``attachment_id`` to an isolated path in a private,
    short-lived handle store; that path must never enter an event or durable
    queue.  Existing adapters may continue to emit only the original
    ``kind``/``file_name`` pair while attachment support is unavailable.
    """

    kind: str
    file_name: str | None = None
    attachment_id: str | None = None
    media_type: str | None = None
    declared_size_bytes: int | None = None

    def __post_init__(self) -> None:
        limits = {
            "kind": 64,
            "file_name": 512,
            "attachment_id": 256,
            "media_type": 128,
        }
        for name, maximum in limits.items():
            value = getattr(self, name)
            if value is None and name != "kind":
                continue
            if (
                not isinstance(value, str)
                or not value
                or len(value) > maximum
                or any(ord(char) < 32 or ord(char) == 127 for char in value)
            ):
                raise ValueError(f"attachment {name} is invalid")
        if self.declared_size_bytes is not None and (
            isinstance(self.declared_size_bytes, bool)
            or not isinstance(self.declared_size_bytes, int)
            or not 0 <= self.declared_size_bytes <= 16 * 1024 * 1024
        ):
            raise ValueError("attachment declared size is invalid")


@dataclass(frozen=True, slots=True)
class InboundEvent:
    channel: str
    account_id: str
    sender_id: str
    message_id: str
    occurred_at_ms: int
    conversation_kind: ConversationKind
    conversation_id: str
    group_id: str | None
    text: str
    mentioned: bool
    reply_message_id: str | None = None
    replied_to_account: bool = False
    attachments: tuple[AttachmentRef, ...] = ()

    @property
    def source_key(self) -> tuple[str, str, str]:
        return (self.channel, self.account_id, self.message_id)
