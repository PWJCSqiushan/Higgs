"""Live official QQ Bot adapter kept behind Higgs transport-neutral types."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from r_agent.events import AttachmentRef, ConversationKind, InboundEvent
from r_agent.transport import (
    DeliveryReceipt,
    DeliveryState,
    OutboundTarget,
    TransportStatus,
    TransportUnavailable,
)


class ApiClient(Protocol):
    def setup(self, http_client: Any) -> None: ...

    def ensure_token_sync(self) -> str: ...

    def get_gateway_url_sync(self) -> str: ...

    def clear_token(self) -> None: ...

    async def send_text(
        self,
        chat_type: str,
        chat_id: str,
        content: str,
        *,
        reply_to: str | None = None,
        markdown: bool = False,
        retries: int = 1,
    ) -> dict[str, Any]: ...


class Gateway(Protocol):
    def start(self, gateway_url: str, main_loop: asyncio.AbstractEventLoop) -> None: ...

    async def async_stop(self) -> None: ...


class SessionStore(Protocol):
    def get(self, app_id: str) -> Any: ...

    def save(
        self,
        app_id: str,
        session: str,
        seq: int | None = None,
        intents: int = 0,
        bot_username: str = "",
    ) -> None: ...

    def clear(self, app_id: str) -> None: ...

    def touch(self, app_id: str) -> None: ...


EventHandler = Callable[[InboundEvent], Awaitable[None]]
GatewayFactory = Callable[[Any], Gateway]
Parser = Callable[[str, dict[str, Any]], Any | None]


def _timestamp_ms(value: str) -> int:
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return int(parsed.timestamp() * 1000)
        except (TypeError, ValueError, OverflowError):
            pass
    return int(time.time() * 1000)


class OfficialQQAdapter:
    """Official Gateway/OpenAPI adapter with explicit owner and group bindings."""

    channel = "qq_official"

    def __init__(
        self,
        config: Any,
        *,
        event_handler: EventHandler | None = None,
        data_dir: Path | None = None,
        api_client: ApiClient | None = None,
        gateway_factory: GatewayFactory | None = None,
        session_store: SessionStore | None = None,
        parser: Parser | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.config = config
        self._event_handler = event_handler
        self._data_dir = data_dir or Path("data")
        self._api = api_client
        self._gateway_factory = gateway_factory
        self._session_store = session_store
        self._parser = parser
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._gateway: Gateway | None = None
        self._http_client: Any = None
        self._lock = threading.RLock()
        self._connected = False
        self._authenticated = False
        self._account_id: str | None = None
        self._reason = "disabled" if not config.enabled else "not_started"
        self._last_heartbeat_ack_at_ms: int | None = None
        self._last_event_at_ms: int | None = None
        self._heartbeat_interval_seconds = 30.0
        self._connected_at_ms: int | None = None
        self._receipts: dict[str, DeliveryReceipt] = {}

    def _ensure_dependencies(self) -> None:
        from qqbot_agent_sdk import EventParser, QQApiClient, QQWebSocket, WSSessionStore

        if self._api is None:
            assert self.config.app_id is not None
            assert self.config.client_secret is not None
            self._api = QQApiClient(
                self.config.app_id,
                self.config.client_secret,
                log_tag="HiggsOfficialQQ",
            )
        if self._gateway_factory is None:
            self._gateway_factory = lambda callbacks: QQWebSocket(
                callbacks=callbacks,
                log_tag="HiggsOfficialQQ",
            )
        if self._session_store is None:
            self._session_store = WSSessionStore(
                base_dir=str(self._data_dir), filename="official_qq_sessions.json"
            )
        if self._parser is None:
            self._parser = EventParser().parse

    async def start(self) -> None:
        if not self.config.enabled:
            raise TransportUnavailable("official QQ is disabled")
        if not self.config.app_id or not self.config.client_secret or not self.config.owner_openid:
            raise TransportUnavailable("official QQ configuration is incomplete")
        self._ensure_dependencies()
        assert self._api is not None
        assert self._gateway_factory is not None
        if self._http_client is None:
            import httpx

            self._http_client = httpx.AsyncClient(timeout=30.0)
            self._api.setup(self._http_client)
        try:
            await asyncio.to_thread(self._api.ensure_token_sync)
            gateway_url = await asyncio.to_thread(self._api.get_gateway_url_sync)
        except Exception as exc:
            with self._lock:
                self._authenticated = False
                self._connected = False
                self._reason = f"startup_failed:{type(exc).__name__}"
            raise TransportUnavailable("official QQ authentication failed") from exc

        from qqbot_agent_sdk import WSCallbacks

        callbacks = WSCallbacks(
            on_message_event=self._on_message_event,
            on_connected=self._on_connected,
            on_disconnected=self._on_disconnected,
            on_fatal_error=self._on_fatal_error,
            get_token=self._api.ensure_token_sync,
            get_session=self._get_session,
            set_session=self._set_session,
            set_heartbeat_interval=self._set_heartbeat_interval,
            clear_token=self._api.clear_token,
            fail_pending=lambda _reason: None,
            get_gateway_url=self._api.get_gateway_url_sync,
            on_heartbeat_ack=self._on_heartbeat_ack,
            on_ready=self._on_ready,
        )
        self._gateway = self._gateway_factory(callbacks)
        with self._lock:
            self._authenticated = True
            self._reason = "connecting"
        self._gateway.start(gateway_url, asyncio.get_running_loop())

    async def stop(self) -> None:
        if self._gateway is not None:
            await self._gateway.async_stop()
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
        with self._lock:
            self._connected = False
            self._authenticated = False
            self._reason = "stopped"

    async def status(self) -> TransportStatus:
        with self._lock:
            self._apply_heartbeat_timeout_locked()
            return TransportStatus(
                channel=self.channel,
                configured=bool(self.config.app_id and self.config.client_secret),
                connected=self._connected,
                authenticated=self._authenticated,
                account_id=self._account_id,
                reason=self._reason,
                last_heartbeat_ack_at_ms=self._last_heartbeat_ack_at_ms,
                last_event_at_ms=self._last_event_at_ms,
            )

    def _get_session(self) -> tuple[str | None, int | None]:
        assert self._session_store is not None
        assert self.config.app_id is not None
        session = self._session_store.get(self.config.app_id)
        fresh = getattr(session, "is_fresh", lambda: False)()
        if getattr(session, "is_resumable", False) and fresh:
            return str(session.session_id), int(session.seq)
        return None, None

    def _set_session(self, session_id: str | None, seq: int | None) -> None:
        assert self._session_store is not None
        assert self.config.app_id is not None
        if session_id is None:
            self._session_store.clear(self.config.app_id)
        else:
            self._session_store.save(self.config.app_id, session_id, seq)

    def _on_connected(self) -> None:
        with self._lock:
            self._connected = True
            self._authenticated = True
            self._connected_at_ms = self._clock_ms()
            self._reason = "ready"

    def _on_disconnected(self) -> None:
        with self._lock:
            self._connected = False
            self._connected_at_ms = None
            self._reason = "gateway_disconnected"

    def _on_fatal_error(self, code: str, _message: str) -> None:
        with self._lock:
            self._connected = False
            self._authenticated = False
            self._reason = f"fatal:{code}"

    def _set_heartbeat_interval(self, interval: float) -> None:
        if 0 < interval <= 300:
            with self._lock:
                self._heartbeat_interval_seconds = interval

    def _apply_heartbeat_timeout_locked(self) -> None:
        if not self._connected or self._connected_at_ms is None:
            return
        latest = self._last_heartbeat_ack_at_ms or self._connected_at_ms
        timeout_ms = int(max(self._heartbeat_interval_seconds * 3, 15.0) * 1000)
        if self._clock_ms() - latest > timeout_ms:
            self._connected = False
            self._reason = "heartbeat_ack_timeout"

    def _on_ready(self, ready: Any) -> None:
        user = getattr(ready, "user", None)
        account_id = str(getattr(user, "id", "") or "")
        if account_id:
            with self._lock:
                self._account_id = account_id

    def _on_heartbeat_ack(self) -> None:
        with self._lock:
            self._last_heartbeat_ack_at_ms = self._clock_ms()
        if self._session_store is not None and self.config.app_id is not None:
            self._session_store.touch(self.config.app_id)

    async def _on_message_event(self, event_type: str, raw: dict[str, Any]) -> None:
        if self._parser is None:
            return
        event = self._normalize_event(self._parser(event_type, raw))
        if event is None:
            return
        with self._lock:
            self._last_event_at_ms = self._clock_ms()
        if self._event_handler is not None:
            await self._event_handler(event)

    def _normalize_event(self, parsed: Any | None) -> InboundEvent | None:
        if parsed is None:
            return None
        scope = str(getattr(parsed, "chat_scope", ""))
        sender_id = str(getattr(parsed, "user_id", "") or "")
        chat_id = str(getattr(parsed, "chat_id", "") or "")
        message_id = str(getattr(parsed, "message_id", "") or "")
        if not sender_id or not chat_id or not message_id:
            return None
        if scope == "c2c":
            if sender_id != self.config.owner_openid:
                return None
            kind = ConversationKind.PRIVATE
            group_id = None
            mentioned = False
        elif scope == "group":
            if chat_id not in self.config.allowed_group_openids:
                return None
            kind = ConversationKind.GROUP
            group_id = chat_id
            mentioned = True
        else:
            return None
        account_id = self._account_id or self.config.app_id or "unknown"
        attachments = tuple(
            AttachmentRef(
                kind=str(getattr(item, "content_type", "attachment") or "attachment"),
                file_name=(str(getattr(item, "filename", "") or "") or None),
            )
            for item in (getattr(parsed, "attachments", None) or [])
        )
        return InboundEvent(
            channel=self.channel,
            account_id=account_id,
            sender_id=sender_id,
            message_id=message_id,
            occurred_at_ms=_timestamp_ms(str(getattr(parsed, "timestamp", "") or "")),
            conversation_kind=kind,
            conversation_id=f"{self.channel}:{kind.value}:{account_id}:{chat_id}",
            group_id=group_id,
            text=str(getattr(parsed, "content", "") or "").strip(),
            mentioned=mentioned,
            attachments=attachments,
        )

    async def send_text(
        self,
        target: OutboundTarget,
        text: str,
        *,
        idempotency_key: str,
        reply_message_id: str | None = None,
    ) -> DeliveryReceipt:
        with self._lock:
            prior = self._receipts.get(idempotency_key)
            self._apply_heartbeat_timeout_locked()
            ready = self._connected and self._authenticated
        if prior is not None:
            return prior
        if target.channel.casefold() != self.channel:
            raise TransportUnavailable("official QQ target channel mismatch")
        if not ready or self._api is None:
            raise TransportUnavailable("official QQ is not ready")
        if not idempotency_key.strip():
            raise ValueError("idempotency key is required")
        content = text.strip()
        if not content or len(content) > 2000:
            raise ValueError("official QQ text must contain 1-2000 characters")
        if not reply_message_id:
            raise TransportUnavailable("official QQ MVP only permits passive replies")
        chat_type = "c2c" if target.conversation_kind is ConversationKind.PRIVATE else "group"
        chat_id = target.conversation_id.rsplit(":", 1)[-1]
        if chat_type == "c2c" and chat_id != self.config.owner_openid:
            raise TransportUnavailable("official QQ private target is not the configured owner")
        if chat_type == "group" and chat_id not in self.config.allowed_group_openids:
            raise TransportUnavailable("official QQ group target is not allowlisted")
        try:
            raw = await self._api.send_text(
                chat_type,
                chat_id,
                content,
                reply_to=reply_message_id,
                markdown=False,
                retries=1,
            )
        except Exception:
            receipt = DeliveryReceipt(self.channel, DeliveryState.UNKNOWN, idempotency_key)
        else:
            provider_id = str(raw.get("id", "") or "")
            receipt = DeliveryReceipt(
                self.channel,
                DeliveryState.SENT if provider_id else DeliveryState.UNKNOWN,
                idempotency_key,
                provider_id or None,
            )
        with self._lock:
            self._receipts[idempotency_key] = receipt
        return receipt
