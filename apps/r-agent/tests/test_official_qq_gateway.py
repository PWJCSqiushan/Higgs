from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from r_agent.events import ConversationKind
from r_agent.official_qq import OfficialQQAdapter, OfficialQQConfig
from r_agent.transport import DeliveryState, OutboundTarget, TransportUnavailable


class FakeApi:
    def __init__(self, *, result: dict[str, Any] | None = None, error: Exception | None = None):
        self.result = result if result is not None else {"id": "provider-message"}
        self.error = error
        self.calls: list[tuple[str, str, str, str | None]] = []
        self.http_client: Any = None

    def setup(self, http_client: Any) -> None:
        self.http_client = http_client

    def ensure_token_sync(self) -> str:
        return "token"

    def get_gateway_url_sync(self) -> str:
        return "wss://gateway.invalid"

    def clear_token(self) -> None:
        return None

    async def send_text(
        self,
        chat_type: str,
        chat_id: str,
        content: str,
        *,
        reply_to: str | None = None,
        markdown: bool = False,
        retries: int = 1,
    ) -> dict[str, Any]:
        del markdown, retries
        self.calls.append((chat_type, chat_id, content, reply_to))
        if self.error is not None:
            raise self.error
        return self.result


class FakeGateway:
    def __init__(self, callbacks: Any):
        self.callbacks = callbacks
        self.started_url: str | None = None
        self.stopped = False

    def start(self, gateway_url: str, _main_loop: Any) -> None:
        self.started_url = gateway_url

    async def async_stop(self) -> None:
        self.stopped = True


@dataclass
class FakePersistedSession:
    session_id: str = ""
    seq: int | None = None

    @property
    def is_resumable(self) -> bool:
        return bool(self.session_id) and self.seq is not None

    def is_fresh(self) -> bool:
        return True


class FakeSessionStore:
    def __init__(self) -> None:
        self.session = FakePersistedSession()
        self.touches = 0

    def get(self, _app_id: str) -> FakePersistedSession:
        return self.session

    def save(
        self,
        _app_id: str,
        session: str,
        seq: int | None = None,
        intents: int = 0,
        bot_username: str = "",
    ) -> None:
        del intents, bot_username
        self.session = FakePersistedSession(session, seq)

    def clear(self, _app_id: str) -> None:
        self.session = FakePersistedSession()

    def touch(self, _app_id: str) -> None:
        self.touches += 1


def config() -> OfficialQQConfig:
    return OfficialQQConfig(
        enabled=True,
        app_id="123456",
        client_secret="a-secure-client-secret",
        owner_openid="owner-openid",
        allowed_group_openids=frozenset({"group-openid"}),
    )


@pytest.mark.asyncio
async def test_fake_gateway_normalizes_only_bound_owner_and_allowlisted_group(
    tmp_path: Path,
) -> None:
    received = []
    gateway: FakeGateway | None = None

    def gateway_factory(callbacks: Any) -> FakeGateway:
        nonlocal gateway
        gateway = FakeGateway(callbacks)
        return gateway

    async def handle_event(event: Any) -> None:
        received.append(event)

    parsed: Any = None
    adapter = OfficialQQAdapter(
        config(),
        event_handler=handle_event,
        data_dir=tmp_path,
        api_client=FakeApi(),
        gateway_factory=gateway_factory,
        session_store=FakeSessionStore(),
        parser=lambda _event_type, _raw: parsed,
        clock_ms=lambda: 1234,
    )
    await adapter.start()
    assert gateway is not None
    gateway.callbacks.on_connected()
    gateway.callbacks.on_ready(SimpleNamespace(user=SimpleNamespace(id="bot-openid")))

    parsed = SimpleNamespace(
        chat_scope="c2c",
        user_id="stranger-openid",
        chat_id="stranger-openid",
        message_id="m0",
        timestamp="2026-08-26T00:00:00Z",
        content="ignored",
        attachments=[],
    )
    await gateway.callbacks.on_message_event("C2C_MESSAGE_CREATE", {})
    assert received == []

    parsed = SimpleNamespace(
        chat_scope="c2c",
        user_id="owner-openid",
        chat_id="owner-openid",
        message_id="m1",
        timestamp="2026-08-26T00:00:00Z",
        content=" status ",
        attachments=[],
    )
    await gateway.callbacks.on_message_event("C2C_MESSAGE_CREATE", {})
    assert received[0].channel == "qq_official"
    assert received[0].account_id == "bot-openid"
    assert received[0].conversation_kind is ConversationKind.PRIVATE

    parsed = SimpleNamespace(
        chat_scope="group",
        user_id="member-openid",
        chat_id="group-openid",
        message_id="m2",
        timestamp="2026-08-26T00:00:01Z",
        content="hello",
        attachments=[],
    )
    await gateway.callbacks.on_message_event("GROUP_AT_MESSAGE_CREATE", {})
    assert received[1].mentioned is True
    assert received[1].group_id == "group-openid"
    status = await adapter.status()
    assert status.authenticated is True
    assert status.connected is True
    assert status.last_event_at_ms == 1234

    gateway.callbacks.on_heartbeat_ack()
    assert (await adapter.status()).last_heartbeat_ack_at_ms == 1234
    await adapter.stop()


@pytest.mark.asyncio
async def test_passive_reply_requires_message_id_and_preserves_unknown_receipt(
    tmp_path: Path,
) -> None:
    api = FakeApi(result={})
    gateway: FakeGateway | None = None

    def gateway_factory(callbacks: Any) -> FakeGateway:
        nonlocal gateway
        gateway = FakeGateway(callbacks)
        return gateway

    adapter = OfficialQQAdapter(
        config(),
        data_dir=tmp_path,
        api_client=api,
        gateway_factory=gateway_factory,
        session_store=FakeSessionStore(),
        parser=lambda _event_type, _raw: None,
    )
    await adapter.start()
    assert gateway is not None
    gateway.callbacks.on_connected()
    target = OutboundTarget(
        channel="qq_official",
        conversation_kind=ConversationKind.PRIVATE,
        conversation_id="qq_official:private:bot-openid:owner-openid",
    )
    with pytest.raises(TransportUnavailable, match="passive"):
        await adapter.send_text(target, "hello", idempotency_key="k1")

    receipt = await adapter.send_text(
        target,
        "hello",
        idempotency_key="k1",
        reply_message_id="incoming-message",
    )
    assert receipt.state is DeliveryState.UNKNOWN
    assert receipt.provider_message_id is None
    again = await adapter.send_text(
        target,
        "hello",
        idempotency_key="k1",
        reply_message_id="incoming-message",
    )
    assert again == receipt
    assert len(api.calls) == 1
    await adapter.stop()


@pytest.mark.asyncio
async def test_sdk_exception_after_send_attempt_is_unknown(tmp_path: Path) -> None:
    api = FakeApi(error=RuntimeError("rate limited after uncertain delivery"))
    gateway: FakeGateway | None = None

    def gateway_factory(callbacks: Any) -> FakeGateway:
        nonlocal gateway
        gateway = FakeGateway(callbacks)
        return gateway

    adapter = OfficialQQAdapter(
        config(),
        data_dir=tmp_path,
        api_client=api,
        gateway_factory=gateway_factory,
        session_store=FakeSessionStore(),
        parser=lambda _event_type, _raw: None,
    )
    await adapter.start()
    assert gateway is not None
    gateway.callbacks.on_connected()
    receipt = await adapter.send_text(
        OutboundTarget(
            "qq_official",
            ConversationKind.GROUP,
            "qq_official:group:bot-openid:group-openid",
        ),
        "hello",
        idempotency_key="k2",
        reply_message_id="incoming-message",
    )
    assert receipt.state is DeliveryState.UNKNOWN
    await adapter.stop()


@pytest.mark.asyncio
async def test_heartbeat_ack_timeout_fails_closed(tmp_path: Path) -> None:
    now = 1000
    gateway: FakeGateway | None = None

    def gateway_factory(callbacks: Any) -> FakeGateway:
        nonlocal gateway
        gateway = FakeGateway(callbacks)
        return gateway

    adapter = OfficialQQAdapter(
        config(),
        data_dir=tmp_path,
        api_client=FakeApi(),
        gateway_factory=gateway_factory,
        session_store=FakeSessionStore(),
        parser=lambda _event_type, _raw: None,
        clock_ms=lambda: now,
    )
    await adapter.start()
    assert gateway is not None
    gateway.callbacks.set_heartbeat_interval(1.0)
    gateway.callbacks.on_connected()
    now = 17_000

    status = await adapter.status()
    assert status.connected is False
    assert status.reason == "heartbeat_ack_timeout"
    await adapter.stop()
