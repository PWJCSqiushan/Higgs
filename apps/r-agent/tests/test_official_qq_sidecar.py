from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from r_agent.events import ConversationKind, InboundEvent
from r_agent.official_qq import OfficialQQConfig
from r_agent.official_qq_sidecar import (
    OfficialQQSidecarAdapter,
    SidecarProtocolViolation,
)
from r_agent.phase2_cli import _build_official_adapter
from r_agent.transport import DeliveryState, OutboundTarget, TransportUnavailable


class FakeSidecarClient:
    def __init__(self, responses: list[tuple[int, Mapping[str, Any]]]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, str, Mapping[str, object] | None]] = []
        self.closed = False

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, object] | None = None,
    ) -> tuple[int, Mapping[str, Any]]:
        self.requests.append((method, path, json_body))
        if not self.responses:
            raise AssertionError("unexpected sidecar request")
        return self.responses.pop(0)

    async def close(self) -> None:
        self.closed = True


def sidecar_config() -> OfficialQQConfig:
    return OfficialQQConfig(
        enabled=True,
        app_id=None,
        client_secret=None,
        owner_openid="owner-id",
        allowed_group_openids=frozenset({"allowed-group"}),
        transport="sidecar",
    )


def status_payload(*, generation: str = "generation-1") -> dict[str, object]:
    return {
        "protocol_version": 1,
        "generation": generation,
        "configured": True,
        "gateway_connected": True,
        "authenticated": True,
        "bot_id": "bot-id",
        "capture_only": False,
        "last_event_at_ms": 1000,
        "last_heartbeat_ack_at_ms": int(time.time() * 1000),
        "heartbeat_ack_observable": True,
        "reason": "ready",
    }


def event_payload(
    cursor: int,
    *,
    event_type: str = "C2C_MESSAGE_CREATE",
    kind: str = "c2c",
    sender_id: str = "owner-id",
    group_id: str | None = None,
) -> dict[str, object]:
    return {
        "cursor": cursor,
        "event_type": event_type,
        "kind": kind,
        "bot_id": "bot-id",
        "sender_id": sender_id,
        "group_id": group_id,
        "message_id": f"message-{cursor}",
        "occurred_at_ms": 1000 + cursor,
        "received_at_ms": 1100 + cursor,
        "text": "hello",
        "attachments": [],
    }


@pytest.mark.asyncio
async def test_start_requires_exact_versioned_ready_status() -> None:
    client = FakeSidecarClient(
        [
            (200, {"protocol_version": 1, "generation": "generation-1"}),
            (200, status_payload()),
        ]
    )
    adapter = OfficialQQSidecarAdapter(sidecar_config(), event_handler=_discard, client=client)

    await adapter.start()

    status = await adapter.status()
    assert status.configured is True
    assert status.connected is True
    assert status.authenticated is True
    assert status.account_id == "bot-id"
    assert client.requests[:2] == [("GET", "/v1/hello", None), ("GET", "/v1/status", None)]


@pytest.mark.asyncio
async def test_start_accepts_connected_status_while_first_heartbeat_is_pending() -> None:
    pending = {
        **status_payload(),
        "authenticated": False,
        "last_heartbeat_ack_at_ms": None,
        "reason": "heartbeat_pending",
    }
    client = FakeSidecarClient(
        [
            (200, {"protocol_version": 1, "generation": "generation-1"}),
            (200, pending),
        ]
    )
    adapter = OfficialQQSidecarAdapter(sidecar_config(), event_handler=_discard, client=client)

    await adapter.start()

    status = await adapter.status()
    assert status.connected is True
    assert status.authenticated is False
    assert status.account_id == "bot-id"
    assert status.reason == "heartbeat_pending"


@pytest.mark.asyncio
async def test_capture_only_sidecar_is_rejected_from_business_pipeline() -> None:
    client = FakeSidecarClient(
        [
            (200, {"protocol_version": 1, "generation": "generation-1"}),
            (200, {**status_payload(), "capture_only": True, "bot_id": None}),
        ]
    )
    adapter = OfficialQQSidecarAdapter(sidecar_config(), event_handler=_discard, client=client)

    with pytest.raises(TransportUnavailable, match="protocol"):
        await adapter.start()
    assert (await adapter.status()).reason == "protocol_error"


@pytest.mark.asyncio
async def test_events_route_only_owner_and_allowlisted_group() -> None:
    received: list[InboundEvent] = []

    async def capture(event: InboundEvent) -> None:
        received.append(event)

    events = [
        event_payload(1),
        event_payload(2, sender_id="not-owner"),
        event_payload(
            3,
            event_type="GROUP_AT_MESSAGE_CREATE",
            kind="group",
            sender_id="member-id",
            group_id="not-allowed",
        ),
        event_payload(
            4,
            event_type="GROUP_AT_MESSAGE_CREATE",
            kind="group",
            sender_id="member-id",
            group_id="allowed-group",
        ),
    ]
    client = FakeSidecarClient(
        [
            (200, {"protocol_version": 1, "generation": "generation-1"}),
            (200, status_payload()),
            (
                200,
                {
                    "protocol_version": 1,
                    "generation": "generation-1",
                    "events": events,
                },
            ),
        ]
    )
    adapter = OfficialQQSidecarAdapter(sidecar_config(), event_handler=capture, client=client)

    await adapter.start()
    await adapter._poll_events()

    assert [(event.conversation_kind, event.sender_id) for event in received] == [
        (ConversationKind.PRIVATE, "owner-id"),
        (ConversationKind.GROUP, "member-id"),
    ]
    assert received[1].mentioned is True
    assert adapter._cursor == 4


@pytest.mark.asyncio
async def test_cursor_gap_and_generation_change_fail_closed() -> None:
    client = FakeSidecarClient(
        [
            (200, {"protocol_version": 1, "generation": "generation-1"}),
            (200, status_payload()),
            (
                200,
                {
                    "protocol_version": 1,
                    "generation": "generation-1",
                    "events": [event_payload(2)],
                },
            ),
        ]
    )
    adapter = OfficialQQSidecarAdapter(sidecar_config(), event_handler=_discard, client=client)
    await adapter.start()

    with pytest.raises(SidecarProtocolViolation, match="contiguous"):
        await adapter._poll_events()

    client.responses.append(
        (
            200,
            {
                "protocol_version": 1,
                "generation": "generation-2",
                "events": [],
            },
        )
    )
    with pytest.raises(SidecarProtocolViolation, match="generation changed"):
        await adapter._poll_events()


@pytest.mark.asyncio
async def test_authenticated_bot_identity_cannot_change() -> None:
    client = FakeSidecarClient(
        [
            (200, {"protocol_version": 1, "generation": "generation-1"}),
            (200, status_payload()),
            (200, {**status_payload(generation="generation-2"), "bot_id": "other-bot"}),
        ]
    )
    adapter = OfficialQQSidecarAdapter(sidecar_config(), event_handler=_discard, client=client)
    await adapter.start()

    with pytest.raises(SidecarProtocolViolation, match="identity changed"):
        await adapter._refresh_status()


@pytest.mark.asyncio
async def test_new_generation_requires_verified_resume_with_same_identity() -> None:
    client = FakeSidecarClient(
        [
            (200, {"protocol_version": 1, "generation": "generation-1"}),
            (200, status_payload()),
            (200, {**status_payload(generation="generation-2"), "reason": "resumed"}),
        ]
    )
    adapter = OfficialQQSidecarAdapter(sidecar_config(), event_handler=_discard, client=client)
    await adapter.start()
    adapter._cursor = 7

    status = await adapter._refresh_status()
    assert status.reason == "resumed_new_generation"
    assert adapter._cursor == 0

    client.responses.append((200, status_payload(generation="generation-3")))
    with pytest.raises(SidecarProtocolViolation, match="without a verified Resume"):
        await adapter._refresh_status()


@pytest.mark.asyncio
async def test_transport_state_failure_is_explicit_and_terminal() -> None:
    class BrokenStateStore:
        def record_transition(self, *_args: object, **_kwargs: object) -> None:
            raise OSError("database unavailable")

    client = FakeSidecarClient(
        [
            (200, {"protocol_version": 1, "generation": "generation-1"}),
            (200, status_payload()),
        ]
    )
    adapter = OfficialQQSidecarAdapter(
        sidecar_config(),
        event_handler=_discard,
        client=client,
        transport_state=BrokenStateStore(),  # type: ignore[arg-type]
    )

    with pytest.raises(TransportUnavailable, match="transport state"):
        await adapter.start()
    status = await adapter.status()
    assert status.connected is False
    assert status.authenticated is False
    assert status.reason == "transport_state_failure"


@pytest.mark.asyncio
async def test_send_is_passive_canonical_and_idempotent() -> None:
    client = FakeSidecarClient(
        [
            (200, {"protocol_version": 1, "generation": "generation-1"}),
            (200, status_payload()),
            (
                200,
                {
                    "protocol_version": 1,
                    "generation": "generation-1",
                    "receipt": {
                        "request_id": "filled-by-test",
                        "state": "sent",
                        "provider_message_id": "provider-id",
                    },
                },
            ),
        ]
    )
    adapter = OfficialQQSidecarAdapter(sidecar_config(), event_handler=_discard, client=client)
    await adapter.start()
    target = OutboundTarget(
        channel="qq_official",
        conversation_kind=ConversationKind.PRIVATE,
        conversation_id="qq_official:private:bot-id:owner-id",
    )

    # The request id is deliberately unpredictable; make the fake echo it.
    original_request = client.request

    async def echo_request(
        method: str,
        path: str,
        *,
        json_body: Mapping[str, object] | None = None,
    ) -> tuple[int, Mapping[str, Any]]:
        if method == "POST" and client.responses:
            response_status, response_payload = client.responses[0]
            response_payload["receipt"]["request_id"] = json_body["request_id"]  # type: ignore[index]
            client.responses[0] = (response_status, response_payload)
        return await original_request(method, path, json_body=json_body)

    client.request = echo_request  # type: ignore[method-assign]
    receipt = await adapter.send_text(
        target,
        "reply",
        idempotency_key="reply-key",
        reply_message_id="incoming-id",
    )
    cached = await adapter.send_text(
        target,
        "reply",
        idempotency_key="reply-key",
        reply_message_id="incoming-id",
    )

    assert receipt.state is DeliveryState.SENT
    assert receipt.provider_message_id == "provider-id"
    assert cached == receipt
    assert len([request for request in client.requests if request[0] == "POST"]) == 1
    sent_body = next(request[2] for request in client.requests if request[0] == "POST")
    assert sent_body is not None
    assert (
        sent_body["request_id"] == hashlib.sha256(b"higgs-official-request\0reply-key").hexdigest()
    )
    with pytest.raises(TransportUnavailable, match="conflicts"):
        await adapter.send_text(
            target,
            "different",
            idempotency_key="reply-key",
            reply_message_id="incoming-id",
        )
    collision_status = await adapter.status()
    assert collision_status.connected is True
    assert collision_status.authenticated is True
    with pytest.raises(TransportUnavailable, match="passive"):
        await adapter.send_text(target, "reply", idempotency_key="new-key")


@pytest.mark.asyncio
async def test_unknown_or_rejected_send_never_claims_sent() -> None:
    for response in (
        (
            200,
            {
                "protocol_version": 1,
                "generation": "generation-1",
                "receipt": {
                    "request_id": "wrong-request",
                    "state": "sent",
                    "provider_message_id": "provider-id",
                },
            },
        ),
        (503, {"error": "gateway_unavailable"}),
    ):
        client = FakeSidecarClient(
            [
                (200, {"protocol_version": 1, "generation": "generation-1"}),
                (200, status_payload()),
                response,
            ]
        )
        adapter = OfficialQQSidecarAdapter(sidecar_config(), event_handler=_discard, client=client)
        await adapter.start()
        target = OutboundTarget(
            channel="qq_official",
            conversation_kind=ConversationKind.PRIVATE,
            conversation_id="qq_official:private:bot-id:owner-id",
        )
        if response[0] == 503:
            with pytest.raises(TransportUnavailable):
                await adapter.send_text(
                    target,
                    "reply",
                    idempotency_key="reply-key",
                    reply_message_id="incoming-id",
                )
            rejected_status = await adapter.status()
            assert rejected_status.connected is True
            assert rejected_status.authenticated is True
        else:
            with pytest.raises(TransportUnavailable, match="protocol failed"):
                await adapter.send_text(
                    target,
                    "reply",
                    idempotency_key="reply-key",
                    reply_message_id="incoming-id",
                )
            failed_status = await adapter.status()
            assert failed_status.connected is False
            assert failed_status.authenticated is False
            assert failed_status.reason == "protocol_error"


def test_phase2_builds_only_the_configured_official_transport(tmp_path: Path) -> None:
    adapter = _build_official_adapter(
        sidecar_config(),
        event_handler=_discard,
        data_dir=tmp_path,
        transport_state=None,
    )

    assert isinstance(adapter, OfficialQQSidecarAdapter)
    assert adapter._client is None


async def _discard(_event: InboundEvent) -> None:
    return None
