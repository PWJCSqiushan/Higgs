"""Transport-neutral boundaries for running Higgs on more than one QQ channel.

The existing NapCat/OneBot runtime remains the only live adapter.  This module
keeps channel-specific credentials and delivery semantics out of the memory,
reminder, and skill layers so an official QQ Bot adapter can be introduced
without duplicating the Higgs brain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from r_agent.events import ConversationKind

if TYPE_CHECKING:
    from r_agent.events import InboundEvent


class DeliveryState(StrEnum):
    """Provider acknowledgement state for an outbound side effect."""

    SENT = "sent"
    FAILED = "failed"
    UNKNOWN = "unknown"


class TransportUnavailable(RuntimeError):
    """The requested channel is disabled, unconfigured, or unhealthy."""


class DeliveryTargetError(ValueError):
    """A durable task target is incomplete or unsafe."""


_DELIVERY_ID = re.compile(r"^[!-~]{1,256}$")


@dataclass(frozen=True, slots=True)
class DeliveryTarget:
    """Canonical channel, Bot account, surface and destination binding.

    Durable reminders and plans must carry this value all the way from the
    inbound conversation to delivery.  In particular, an external identity is
    never sufficient without the Bot account namespace.
    """

    channel: str
    bot_account: str
    target_id: str
    surface: str

    def __post_init__(self) -> None:
        channel = str(self.channel).strip().casefold()
        surface = str(self.surface).strip().casefold()
        if channel not in {"qq", "qq_official"}:
            raise DeliveryTargetError("invalid delivery channel")
        if surface not in {"private", "group"}:
            raise DeliveryTargetError("invalid delivery surface")
        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "surface", surface)
        for name, value in (("Bot account", self.bot_account), ("target", self.target_id)):
            clean = str(value).strip()
            if not clean or ":" in clean or not _DELIVERY_ID.fullmatch(clean):
                raise DeliveryTargetError(f"invalid delivery {name}")
            object.__setattr__(self, "bot_account" if name == "Bot account" else "target_id", clean)

    @property
    def conversation_id(self) -> str:
        return f"{self.channel}:{self.surface}:{self.bot_account}:{self.target_id}"

    @classmethod
    def from_event(cls, event: InboundEvent) -> DeliveryTarget:
        target_id = (
            event.sender_id if event.conversation_kind.value == "private" else event.group_id
        )
        target = cls(
            channel=event.channel,
            bot_account=event.account_id,
            target_id=target_id or "",
            surface=event.conversation_kind.value,
        )
        if event.conversation_id.strip() != target.conversation_id:
            raise DeliveryTargetError("event conversation is not canonical")
        return target

    def as_mapping(self) -> dict[str, str]:
        return {
            "channel": self.channel,
            "bot_account": self.bot_account,
            "target_id": self.target_id,
            "surface": self.surface,
        }

    def matches_event(self, event: InboundEvent) -> bool:
        try:
            return self == self.from_event(event)
        except (DeliveryTargetError, ValueError):
            return False


@dataclass(frozen=True, slots=True)
class OutboundTarget:
    channel: str
    conversation_kind: ConversationKind
    conversation_id: str


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    channel: str
    state: DeliveryState
    idempotency_key: str
    provider_message_id: str | None = None


@dataclass(frozen=True, slots=True)
class TransportStatus:
    channel: str
    configured: bool
    connected: bool
    authenticated: bool = False
    account_id: str | None = None
    reason: str = ""
    last_heartbeat_ack_at_ms: int | None = None
    last_event_at_ms: int | None = None


class TransportAdapter(Protocol):
    """Small surface required by reminders and future transport routing."""

    @property
    def channel(self) -> str: ...

    async def status(self) -> TransportStatus: ...

    async def send_text(
        self,
        target: OutboundTarget,
        text: str,
        *,
        idempotency_key: str,
        reply_message_id: str | None = None,
    ) -> DeliveryReceipt: ...


class TransportRegistry:
    """Explicit channel registry; unknown and duplicate channels fail closed."""

    def __init__(self) -> None:
        self._adapters: dict[str, TransportAdapter] = {}

    def register(self, adapter: TransportAdapter) -> None:
        channel = adapter.channel.strip().casefold()
        if not channel or channel in self._adapters:
            raise ValueError("transport channel must be non-empty and unique")
        self._adapters[channel] = adapter

    def get(self, channel: str) -> TransportAdapter:
        normalized = channel.strip().casefold()
        try:
            return self._adapters[normalized]
        except KeyError as exc:
            raise TransportUnavailable("transport channel is not registered") from exc

    def channels(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))


__all__ = [
    "DeliveryReceipt",
    "DeliveryState",
    "DeliveryTarget",
    "DeliveryTargetError",
    "OutboundTarget",
    "TransportAdapter",
    "TransportRegistry",
    "TransportStatus",
    "TransportUnavailable",
]
