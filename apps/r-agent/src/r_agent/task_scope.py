"""Principal and delivery-target boundaries for user-owned tasks.

Reminders and plans are durable side effects.  A short ID is useful in chat,
but it is not an authorization boundary: the caller, Bot account, channel and
surface must all remain bound to the original conversation.  This module is a
small, dependency-free vocabulary shared by both task stores.
"""

from __future__ import annotations

from r_agent.events import ConversationKind, InboundEvent
from r_agent.transport import DeliveryTarget, DeliveryTargetError

TaskScopeError = DeliveryTargetError


def ordinary_user_task_target(event: InboundEvent) -> DeliveryTarget:
    """Require the narrow ordinary-user surface: official private C2C only."""

    if event.channel.strip().casefold() != "qq_official":
        raise TaskScopeError("ordinary user tasks require official QQ C2C")
    if event.conversation_kind is not ConversationKind.PRIVATE:
        raise TaskScopeError("ordinary user tasks are private C2C only")
    return DeliveryTarget.from_event(event)


__all__ = ["DeliveryTarget", "TaskScopeError", "ordinary_user_task_target"]
