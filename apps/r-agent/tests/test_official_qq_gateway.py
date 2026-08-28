from __future__ import annotations

import asyncio
import logging
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


class BlockingFakeApi(FakeApi):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

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
        self.entered.set()
        await self.release.wait()
        return await super().send_text(
            chat_type,
            chat_id,
            content,
            reply_to=reply_to,
            markdown=markdown,
            retries=retries,
        )


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
    fresh: bool = True

    @property
    def is_resumable(self) -> bool:
        return bool(self.session_id) and self.seq is not None

    def is_fresh(self) -> bool:
        return self.fresh


class FakeSessionStore:
    def __init__(self) -> None:
        self.session = FakePersistedSession()
        self.touches = 0
        self.account_id: str | None = None

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
        self.account_id = None

    def touch(self, _app_id: str) -> None:
        self.touches += 1

    def get_account_id(self, _app_id: str) -> str | None:
        return self.account_id

    def set_account_id(self, _app_id: str, account_id: str) -> None:
        self.account_id = account_id


class FakeTransportState:
    def __init__(self) -> None:
        self.transitions: list[dict[str, Any]] = []

    def record_transition(self, state: str, **kwargs: Any) -> None:
        self.transitions.append({"state": state, **kwargs})


def config() -> OfficialQQConfig:
    return OfficialQQConfig(
        enabled=True,
        app_id="123456",
        client_secret="a-secure-client-secret",
        owner_openid="owner-openid",
        allowed_group_openids=frozenset({"group-openid"}),
    )


def test_sdk_logging_is_suppressed_before_live_dependencies_are_created(tmp_path: Path) -> None:
    from qqbot_agent_sdk import websocket as sdk_websocket
    from qqbot_agent_sdk.dto import Intent

    logger_names = (
        "qqbot_agent_sdk",
        "qqbot_agent_sdk.api_client",
        "qqbot_agent_sdk.websocket",
    )
    previous = {name: logging.getLogger(name).level for name in logger_names}
    try:
        for name in logger_names:
            logging.getLogger(name).setLevel(logging.NOTSET)
        adapter = OfficialQQAdapter(config(), data_dir=tmp_path)
        adapter._ensure_dependencies()  # type: ignore[attr-defined]
        assert all(logging.getLogger(name).level == logging.CRITICAL for name in logger_names)
        assert sdk_websocket.DEFAULT_INTENTS == Intent.GROUP_MESSAGES
        assert sdk_websocket.MAX_RECONNECT_ATTEMPTS == 5
    finally:
        for name, level in previous.items():
            logging.getLogger(name).setLevel(level)


def test_live_gateway_rejects_malformed_invalid_session_payload(tmp_path: Path) -> None:
    from qqbot_agent_sdk.dto import OPCode

    adapter = OfficialQQAdapter(config(), data_dir=tmp_path)
    adapter._ensure_dependencies()  # type: ignore[attr-defined]
    fatal_codes: list[str] = []
    callbacks = SimpleNamespace(
        on_fatal_error=lambda code, _message: fatal_codes.append(code),
    )
    assert adapter._gateway_factory is not None  # type: ignore[attr-defined]
    gateway = adapter._gateway_factory(callbacks)  # type: ignore[attr-defined]
    close_calls: list[bool] = []
    gateway._running = True
    gateway._close_ws_async = lambda: close_calls.append(True)

    gateway._dispatch_payload({"op": OPCode.INVALID_SESSION, "d": {}})
    assert fatal_codes == ["invalid_session_payload"]
    assert gateway._stop_requested is True
    assert gateway._running is False
    assert close_calls == [True]


def test_live_gateway_marks_valid_reconnect_and_invalid_session_disconnected(
    tmp_path: Path,
) -> None:
    from qqbot_agent_sdk.dto import OPCode

    adapter = OfficialQQAdapter(config(), data_dir=tmp_path)
    adapter._ensure_dependencies()  # type: ignore[attr-defined]
    disconnects: list[bool] = []
    callbacks = SimpleNamespace(
        get_session=lambda: (None, None),
        set_session=lambda _session, _seq: None,
        on_disconnected=lambda: disconnects.append(True),
    )
    assert adapter._gateway_factory is not None  # type: ignore[attr-defined]
    gateway = adapter._gateway_factory(callbacks)  # type: ignore[attr-defined]
    gateway._close_ws_async = lambda: None

    gateway._dispatch_payload({"op": OPCode.RECONNECT, "d": None})
    gateway._dispatch_payload({"op": OPCode.INVALID_SESSION, "d": False})

    assert disconnects == [True, True]


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
async def test_fake_gateway_rejects_unknown_or_mismatched_message_event_types(
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

    parsed = SimpleNamespace(
        chat_scope="c2c",
        user_id="owner-openid",
        chat_id="owner-openid",
        message_id="m1",
        timestamp="2026-08-26T00:00:00Z",
        content="status",
        attachments=[],
    )
    adapter = OfficialQQAdapter(
        config(),
        event_handler=handle_event,
        data_dir=tmp_path,
        api_client=FakeApi(),
        gateway_factory=gateway_factory,
        session_store=FakeSessionStore(),
        parser=lambda _event_type, _raw: parsed,
    )
    await adapter.start()
    assert gateway is not None
    gateway.callbacks.on_connected()

    await gateway.callbacks.on_message_event("C2C_MESSAGE_CREATE", {})
    assert received == []
    gateway.callbacks.on_ready(SimpleNamespace(user=SimpleNamespace(id="bot-openid")))
    await gateway.callbacks.on_message_event("MESSAGE_CREATE", {})
    await gateway.callbacks.on_message_event("GROUP_AT_MESSAGE_CREATE", {})
    assert received == []

    await gateway.callbacks.on_message_event("C2C_MESSAGE_CREATE", {})
    assert len(received) == 1
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
    gateway.callbacks.on_ready(SimpleNamespace(user=SimpleNamespace(id="bot-openid")))
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
    gateway.callbacks.on_ready(SimpleNamespace(user=SimpleNamespace(id="bot-openid")))
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
async def test_concurrent_duplicate_idempotency_key_sends_once(tmp_path: Path) -> None:
    api = BlockingFakeApi()
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
    gateway.callbacks.on_ready(SimpleNamespace(user=SimpleNamespace(id="bot-openid")))
    target = OutboundTarget(
        "qq_official",
        ConversationKind.PRIVATE,
        "qq_official:private:bot-openid:owner-openid",
    )
    first = asyncio.create_task(
        adapter.send_text(
            target,
            "hello",
            idempotency_key="same-key",
            reply_message_id="incoming-message",
        )
    )
    await api.entered.wait()
    second = asyncio.create_task(
        adapter.send_text(
            target,
            "hello",
            idempotency_key="same-key",
            reply_message_id="incoming-message",
        )
    )
    await asyncio.sleep(0)
    api.release.set()

    receipts = await asyncio.gather(first, second)
    assert receipts[0] == receipts[1]
    assert receipts[0].state is DeliveryState.SENT
    assert len(api.calls) == 1

    with pytest.raises(ValueError, match="conflicts"):
        await adapter.send_text(
            target,
            "different text",
            idempotency_key="same-key",
            reply_message_id="incoming-message",
        )
    await adapter.stop()


@pytest.mark.asyncio
async def test_send_rejects_noncanonical_conversation_target(tmp_path: Path) -> None:
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
    )
    await adapter.start()
    assert gateway is not None
    gateway.callbacks.on_connected()
    gateway.callbacks.on_ready(SimpleNamespace(user=SimpleNamespace(id="bot-openid")))

    with pytest.raises(TransportUnavailable, match="canonical"):
        await adapter.send_text(
            OutboundTarget(
                "qq_official",
                ConversationKind.PRIVATE,
                "qq_official:private:wrong-bot:owner-openid",
            ),
            "hello",
            idempotency_key="k-canonical",
            reply_message_id="incoming-message",
        )
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
    pre_ready = await adapter.status()
    assert pre_ready.connected is False
    assert pre_ready.authenticated is False
    assert pre_ready.reason == "connecting"
    gateway.callbacks.set_heartbeat_interval(1.0)
    gateway.callbacks.on_connected()
    gateway.callbacks.on_ready(SimpleNamespace(user=SimpleNamespace(id="bot-openid")))
    assert (await adapter.status()).authenticated is True
    now = 17_000

    status = await adapter.status()
    assert status.connected is False
    assert status.authenticated is False
    assert status.reason == "heartbeat_ack_timeout"
    await adapter.stop()


@pytest.mark.asyncio
async def test_disconnect_clears_authentication_and_persists_offline(tmp_path: Path) -> None:
    gateway: FakeGateway | None = None
    transport_state = FakeTransportState()

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
        transport_state=transport_state,  # type: ignore[arg-type]
    )
    await adapter.start()
    assert gateway is not None
    gateway.callbacks.on_ready(SimpleNamespace(user=SimpleNamespace(id="bot-openid")))
    gateway.callbacks.on_connected()
    adapter._persist_status(await adapter.status())  # type: ignore[attr-defined]
    assert transport_state.transitions[-1]["state"] == "verified"
    assert transport_state.transitions[-1]["qq_online"] is True
    assert transport_state.transitions[-1]["account_match"] is True

    gateway.callbacks.on_disconnected()
    status = await adapter.status()
    assert status.connected is False
    assert status.authenticated is False
    adapter._persist_status(status)  # type: ignore[attr-defined]
    assert transport_state.transitions[-1]["state"] == "pending"
    assert transport_state.transitions[-1]["qq_online"] is False
    assert transport_state.transitions[-1]["account_match"] is None
    await adapter.stop()


@pytest.mark.asyncio
async def test_resume_restores_persisted_bot_identity_before_connected(tmp_path: Path) -> None:
    session_store = FakeSessionStore()
    session_store.session = FakePersistedSession("resume-session", 7)
    session_store.account_id = "bot-openid"
    adapter = OfficialQQAdapter(
        config(),
        data_dir=tmp_path,
        api_client=FakeApi(),
        gateway_factory=FakeGateway,
        session_store=session_store,
        parser=lambda _event_type, _raw: None,
    )
    await adapter.start()

    assert adapter._get_session() == ("resume-session", 7)  # type: ignore[attr-defined]
    adapter._on_connected()  # type: ignore[attr-defined]
    status = await adapter.status()
    assert status.connected is True
    assert status.authenticated is True
    assert status.account_id == "bot-openid"
    await adapter.stop()


@pytest.mark.asyncio
async def test_session_invalidation_clears_connected_identity_immediately(tmp_path: Path) -> None:
    session_store = FakeSessionStore()
    session_store.session = FakePersistedSession("resume-session", 7)
    session_store.account_id = "bot-openid"
    adapter = OfficialQQAdapter(
        config(),
        data_dir=tmp_path,
        api_client=FakeApi(),
        gateway_factory=FakeGateway,
        session_store=session_store,
        parser=lambda _event_type, _raw: None,
    )
    await adapter.start()
    assert adapter._get_session() == ("resume-session", 7)  # type: ignore[attr-defined]
    adapter._on_connected()  # type: ignore[attr-defined]

    adapter._set_session(None, None)  # type: ignore[attr-defined]

    status = await adapter.status()
    assert status.connected is False
    assert status.authenticated is False
    assert status.account_id is None
    assert status.reason == "session_invalidated"
    await adapter.stop()


@pytest.mark.asyncio
async def test_stale_resume_identity_is_cleared_before_fresh_identify(tmp_path: Path) -> None:
    session_store = FakeSessionStore()
    session_store.session = FakePersistedSession("stale-session", 7, fresh=False)
    session_store.account_id = "old-bot-openid"
    adapter = OfficialQQAdapter(
        config(),
        data_dir=tmp_path,
        api_client=FakeApi(),
        gateway_factory=FakeGateway,
        session_store=session_store,
        parser=lambda _event_type, _raw: None,
    )
    await adapter.start()

    assert adapter._get_session() == (None, None)  # type: ignore[attr-defined]
    adapter._on_connected()  # type: ignore[attr-defined]
    status = await adapter.status()
    assert status.connected is True
    assert status.authenticated is False
    assert status.account_id is None
    assert status.reason == "ready_identity_pending"
    assert session_store.session.is_resumable is False
    assert session_store.account_id is None
    await adapter.stop()


@pytest.mark.asyncio
async def test_invalid_ready_identity_is_terminal_and_never_authenticated(tmp_path: Path) -> None:
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
    )
    await adapter.start()
    assert gateway is not None
    gateway.callbacks.on_connected()
    gateway.callbacks.on_ready(SimpleNamespace(user=SimpleNamespace(id="")))

    status = await adapter.status()
    assert status.connected is False
    assert status.authenticated is False
    assert status.reason == "ready_identity_invalid"
    await adapter.supervise(poll_interval_seconds=0.1, base_delay_seconds=0.1)
    await adapter.stop()


@pytest.mark.asyncio
async def test_production_mode_is_disabled_even_with_complete_config(tmp_path: Path) -> None:
    production = OfficialQQConfig(
        enabled=True,
        app_id="123456",
        client_secret="a-secure-client-secret",
        sandbox=False,
        owner_openid="owner-openid",
    )
    adapter = OfficialQQAdapter(production, data_dir=tmp_path)

    with pytest.raises(TransportUnavailable, match="production mode"):
        await adapter.start()
    status = await adapter.status()
    assert status.authenticated is False
    assert status.reason == "production_mode_disabled"


@pytest.mark.asyncio
async def test_supervisor_does_not_restart_after_fatal_error(tmp_path: Path) -> None:
    starts = 0
    gateway: FakeGateway | None = None

    def gateway_factory(callbacks: Any) -> FakeGateway:
        nonlocal starts, gateway
        starts += 1
        gateway = FakeGateway(callbacks)
        return gateway

    adapter = OfficialQQAdapter(
        config(),
        data_dir=tmp_path,
        api_client=FakeApi(),
        gateway_factory=gateway_factory,
        session_store=FakeSessionStore(),
        parser=lambda _event_type, _raw: None,
    )
    await adapter.start()
    assert gateway is not None
    gateway.callbacks.on_fatal_error("4013", "invalid intents")
    await adapter.supervise(
        poll_interval_seconds=0.1,
        base_delay_seconds=0.1,
        max_consecutive_restarts=3,
    )
    assert starts == 1
    assert (await adapter.status()).reason == "fatal:4013"
    await adapter.stop()


@pytest.mark.asyncio
async def test_supervisor_caps_ordinary_restart_backoff(tmp_path: Path) -> None:
    starts = 0

    def gateway_factory(callbacks: Any) -> FakeGateway:
        nonlocal starts
        starts += 1
        return FakeGateway(callbacks)

    adapter = OfficialQQAdapter(
        config(),
        data_dir=tmp_path,
        api_client=FakeApi(),
        gateway_factory=gateway_factory,
        session_store=FakeSessionStore(),
        parser=lambda _event_type, _raw: None,
    )
    await adapter.start()
    await asyncio.wait_for(
        adapter.supervise(
            poll_interval_seconds=0.1,
            base_delay_seconds=0.1,
            max_delay_seconds=0.2,
            max_consecutive_restarts=2,
        ),
        timeout=2.0,
    )
    assert starts == 3  # initial start plus two bounded ordinary retries
    assert (await adapter.status()).reason == "restart_budget_exhausted"
    await adapter.stop()
