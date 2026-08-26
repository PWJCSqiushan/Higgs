from __future__ import annotations

import pytest

from r_agent.events import ConversationKind, InboundEvent
from r_agent.onebot_adapter import OneBotAdapter
from r_agent.phase2_outbound import OneBotAccountStatus, OutboundError
from r_agent.transport import DeliveryState, OutboundTarget


@pytest.mark.asyncio
async def test_onebot_status_requires_expected_account(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_status(_url: str, _token: str | None) -> OneBotAccountStatus:
        return OneBotAccountStatus(True, True, "20002", "bot")

    monkeypatch.setattr("r_agent.onebot_adapter.get_onebot_account_status", fake_status)
    status = await OneBotAdapter("ws://onebot", None, expected_account_id="10001").status()
    assert status.connected is True
    assert status.authenticated is False
    assert status.reason == "wrong_account"


@pytest.mark.asyncio
async def test_onebot_adapter_never_reports_missing_receipt_as_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_send(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("r_agent.onebot_adapter.send_onebot_private_message", fake_send)
    receipt = await OneBotAdapter("ws://onebot", None).send_text(
        OutboundTarget("qq", ConversationKind.PRIVATE, "qq:private:bot:10001"),
        "hello",
        idempotency_key="k1",
    )
    assert receipt.state is DeliveryState.UNKNOWN


@pytest.mark.asyncio
async def test_onebot_known_rejection_is_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def reject(*_args: object, **_kwargs: object) -> None:
        raise OutboundError("rejected", delivery_unknown=False)

    monkeypatch.setattr("r_agent.onebot_adapter.send_onebot_group_message", reject)
    receipt = await OneBotAdapter("ws://onebot", None).send_text(
        OutboundTarget("qq", ConversationKind.GROUP, "qq:group:bot:30001"),
        "hello",
        idempotency_key="k2",
    )
    assert receipt.state is DeliveryState.FAILED


@pytest.mark.asyncio
async def test_onebot_reply_adapter_maps_missing_provider_id_to_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_reply(*_args: object, **_kwargs: object) -> None:
        raise OutboundError("provider acknowledgement omitted message id")

    event = InboundEvent(
        channel="qq",
        account_id="900001",
        sender_id="800001",
        message_id="42",
        occurred_at_ms=1,
        conversation_kind=ConversationKind.PRIVATE,
        conversation_id="qq:private:900001:800001",
        group_id=None,
        text="hello",
        mentioned=False,
    )
    monkeypatch.setattr("r_agent.onebot_adapter.send_onebot_reply", fake_reply)
    receipt = await OneBotAdapter("ws://onebot", None).send_reply(event, "hello")
    assert receipt.state is DeliveryState.UNKNOWN
    assert receipt.provider_message_id is None
