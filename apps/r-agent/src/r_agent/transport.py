"""Transport-neutral boundaries for running Higgs on more than one QQ channel.

The existing NapCat/OneBot runtime remains the only live adapter.  This module
keeps channel-specific credentials and delivery semantics out of the memory,
reminder, and skill layers so an official QQ Bot adapter can be introduced
without duplicating the Higgs brain.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from r_agent.events import ConversationKind


class DeliveryState(StrEnum):
    """Provider acknowledgement state for an outbound side effect."""

    SENT = "sent"
    FAILED = "failed"
    UNKNOWN = "unknown"


class TransportUnavailable(RuntimeError):
    """The requested channel is disabled, unconfigured, or unhealthy."""


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
