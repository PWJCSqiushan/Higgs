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
