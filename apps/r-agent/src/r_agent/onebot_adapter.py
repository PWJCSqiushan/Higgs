"""OneBot/NapCat implementation of the shared Higgs transport boundary."""

from __future__ import annotations

from r_agent.events import ConversationKind
from r_agent.phase2_outbound import (
    OutboundError,
    get_onebot_account_status,
    send_onebot_group_message,
    send_onebot_private_message,
)
from r_agent.transport import (
    DeliveryReceipt,
    DeliveryState,
    OutboundTarget,
    TransportStatus,
    TransportUnavailable,
)


class OneBotAdapter:
    channel = "qq"

    def __init__(self, ws_url: str, token: str | None, *, expected_account_id: str | None = None):
        self.ws_url = ws_url
        self.token = token
        self.expected_account_id = expected_account_id

    async def status(self) -> TransportStatus:
        try:
            current = await get_onebot_account_status(self.ws_url, self.token)
        except OutboundError as exc:
            return TransportStatus(
                channel=self.channel,
                configured=bool(self.ws_url),
                connected=False,
                authenticated=False,
                reason=f"status_failed:{type(exc).__name__}",
            )
        account_matches = not self.expected_account_id or (
            current.account_id == self.expected_account_id
        )
        healthy = current.online and current.good and account_matches
        reason = "ready" if healthy else "wrong_account" if not account_matches else "qq_offline"
        return TransportStatus(
            channel=self.channel,
            configured=bool(self.ws_url),
            connected=current.good,
            authenticated=current.online and account_matches,
            account_id=current.account_id,
            reason=reason,
        )

    async def send_text(
        self,
        target: OutboundTarget,
        text: str,
        *,
        idempotency_key: str,
        reply_message_id: str | None = None,
    ) -> DeliveryReceipt:
        del reply_message_id
        if target.channel.casefold() != self.channel:
            raise TransportUnavailable("OneBot target channel mismatch")
        target_id = target.conversation_id.rsplit(":", 1)[-1]
        try:
            if target.conversation_kind is ConversationKind.PRIVATE:
                provider_id = await send_onebot_private_message(
                    self.ws_url,
                    self.token,
                    user_id=target_id,
                    text=text,
                    idempotency_key=idempotency_key,
                )
            else:
                provider_id = await send_onebot_group_message(
                    self.ws_url,
                    self.token,
                    group_id=target_id,
                    text=text,
                    idempotency_key=idempotency_key,
                )
        except OutboundError as exc:
            return DeliveryReceipt(
                channel=self.channel,
                state=(DeliveryState.UNKNOWN if exc.delivery_unknown else DeliveryState.FAILED),
                idempotency_key=idempotency_key,
            )
        return DeliveryReceipt(
            channel=self.channel,
            state=DeliveryState.SENT if provider_id else DeliveryState.UNKNOWN,
            idempotency_key=idempotency_key,
            provider_message_id=provider_id,
        )
