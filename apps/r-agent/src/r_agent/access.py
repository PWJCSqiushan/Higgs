"""Deterministic ingress policy. The model is never consulted."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from r_agent.events import ConversationKind, InboundEvent


class IngressDecision(StrEnum):
    ACCEPT = "accept"
    DISABLED = "disabled"
    SELF_MESSAGE = "self_message"
    OWNER_UNCONFIGURED = "owner_unconfigured"
    PRIVATE_NOT_ALLOWED = "private_not_allowed"
    GROUP_NOT_ALLOWED = "group_not_allowed"


@dataclass(frozen=True, slots=True)
class IngressPolicy:
    enabled: bool
    owner_qq: str | None
    allowed_private_qqs: frozenset[str]
    allowed_groups: frozenset[str]

    def decide(self, event: InboundEvent) -> IngressDecision:
        if not self.enabled:
            return IngressDecision.DISABLED
        if event.sender_id == event.account_id:
            return IngressDecision.SELF_MESSAGE
        if event.conversation_kind is ConversationKind.PRIVATE:
            if self.owner_qq is None:
                return IngressDecision.OWNER_UNCONFIGURED
            if event.sender_id != self.owner_qq and event.sender_id not in self.allowed_private_qqs:
                return IngressDecision.PRIVATE_NOT_ALLOWED
            return IngressDecision.ACCEPT
        if event.group_id not in self.allowed_groups:
            return IngressDecision.GROUP_NOT_ALLOWED
        return IngressDecision.ACCEPT
