"""Fail-closed official QQ adapter backed by the local Node UDS sidecar."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from r_agent.events import AttachmentRef, ConversationKind, InboundEvent
from r_agent.official_qq_policy import OfficialChannelGate
from r_agent.transport import (
    DeliveryReceipt,
    DeliveryState,
    OutboundTarget,
    TransportStatus,
    TransportUnavailable,
)
from r_agent.transport_state import TransportStateStore

PROTOCOL_VERSION = 2
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_TEXT_LENGTH = 4000
_SAFE_REASONS = {
    "disabled",
    "starting",
    "ready",
    "resumed",
    "ready_identity_invalid",
    "gateway_error",
    "gateway_reconnecting",
    "gateway_stopped",
    "heartbeat_pending",
    "heartbeat_ack_timeout",
    "reconnect_budget_exhausted",
    "session_store_error",
    "delivery_store_error",
    "protocol_error",
    "stopped",
}
_SAFE_ERROR_CODES = {
    "body_too_large",
    "capture_only",
    "cursor_gap",
    "empty_body",
    "event_queue_full",
    "gateway_unavailable",
    "idempotency_collision",
    "internal_error",
    "invalid_cursor",
    "invalid_idempotency_key",
    "invalid_delivery_mode",
    "invalid_json",
    "invalid_limit",
    "invalid_object",
    "invalid_request_identity",
    "invalid_reply_binding",
    "invalid_proactive_target",
    "private_channel_disabled",
    "group_channel_disabled",
    "channel_rate_limited",
    "channel_circuit_open",
    "invalid_target",
    "invalid_text",
    "not_found",
    "protocol_version_mismatch",
    "proactive_disabled",
    "reply_message_id_required",
    "sidecar_not_configured",
    "stale_generation",
    "unknown_field",
}

EventHandler = Callable[[InboundEvent], Awaitable[None]]


class SidecarProtocolViolation(RuntimeError):
    """The local sidecar returned a malformed or contradictory response."""


class SidecarResponseError(RuntimeError):
    """A bounded protocol error returned by the local sidecar."""

    def __init__(self, code: str, status: int) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class TransportStatePersistenceError(RuntimeError):
    """The redacted transport ledger could not persist a state change."""


class SidecarClient(Protocol):
    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, object] | None = None,
    ) -> tuple[int, Mapping[str, Any]]: ...

    async def close(self) -> None: ...


class SidecarConfig(Protocol):
    enabled: bool
    owner_openid: str | None
    allowed_group_openids: frozenset[str]
    allowed_private_openids: frozenset[str]
    active_private_openids: frozenset[str]
    active_group_openids: frozenset[str]
    ordinary_private_enabled: bool
    group_enabled: bool
    private_rate_per_minute: int
    group_rate_per_minute: int
    private_circuit_failure_limit: int
    group_circuit_failure_limit: int
    private_circuit_cooldown_seconds: int
    group_circuit_cooldown_seconds: int
    transport: str
    sidecar_socket_path: str
    proactive_enabled: bool
    active_private_allowlist_version: int | None
    active_private_allowlist_fingerprint: str | None


class HttpxSidecarClient:
    """Small HTTP/1.1 client whose only transport is a Unix domain socket."""

    def __init__(self, socket_path: str) -> None:
        import httpx

        self._client = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=socket_path, retries=0),
            base_url="http://higgs-official.local",
            timeout=httpx.Timeout(3.0, connect=1.0),
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
            follow_redirects=False,
            trust_env=False,
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, object] | None = None,
    ) -> tuple[int, Mapping[str, Any]]:
        response = await self._client.request(method, path, json=json_body)
        content = response.content
        if len(content) > MAX_RESPONSE_BYTES:
            raise SidecarProtocolViolation("sidecar response is too large")
        content_type = response.headers.get("content-type", "").casefold()
        if not content_type.startswith("application/json"):
            raise SidecarProtocolViolation("sidecar response is not JSON")
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SidecarProtocolViolation("sidecar response contains invalid JSON") from exc
        if not isinstance(payload, dict):
            raise SidecarProtocolViolation("sidecar response must be an object")
        return response.status_code, payload

    async def close(self) -> None:
        await self._client.aclose()


def _exact_keys(value: Mapping[str, Any], allowed: set[str]) -> None:
    if set(value) != allowed:
        raise SidecarProtocolViolation("sidecar response fields are invalid")


def _safe_id(value: object, *, maximum: int = 256) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise SidecarProtocolViolation("sidecar identity is invalid")
    if not value.isascii() or any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise SidecarProtocolViolation("sidecar identity is invalid")
    return value


def _optional_timestamp(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SidecarProtocolViolation("sidecar timestamp is invalid")
    return value


class OfficialQQSidecarAdapter:
    """Transport-neutral official QQ adapter using the sidecar UDS protocol."""

    channel = "qq_official"

    def __init__(
        self,
        config: SidecarConfig,
        *,
        event_handler: EventHandler | None = None,
        client: SidecarClient | None = None,
        transport_state: TransportStateStore | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.config = config
        self._event_handler = event_handler
        self._client = client
        self._transport_state = transport_state
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._private_gate = OfficialChannelGate(
            rate_per_minute=config.private_rate_per_minute,
            failure_limit=config.private_circuit_failure_limit,
            cooldown_seconds=config.private_circuit_cooldown_seconds,
            clock_ms=self._clock_ms,
        )
        self._group_gate = OfficialChannelGate(
            rate_per_minute=config.group_rate_per_minute,
            failure_limit=config.group_circuit_failure_limit,
            cooldown_seconds=config.group_circuit_cooldown_seconds,
            clock_ms=self._clock_ms,
        )
        self._stop_requested = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._generation: str | None = None
        self._cursor = 0
        self._configured = False
        self._connected = False
        self._authenticated = False
        self._account_id: str | None = None
        self._expected_account_id: str | None = None
        self._reason = "disabled" if not config.enabled else "starting"
        self._last_heartbeat_ack_at_ms: int | None = None
        self._last_event_at_ms: int | None = None
        self._terminal_failure = False
        self._receipts: dict[str, DeliveryReceipt] = {}
        self._receipt_fingerprints: dict[str, str] = {}
        self._last_persisted: tuple[object, ...] | None = None
        self._last_persisted_at_ms = 0
        self._cursor_resync_required = False

    def _get_client(self) -> SidecarClient:
        if self._client is None:
            self._client = HttpxSidecarClient(self.config.sidecar_socket_path)
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, object] | None = None,
    ) -> Mapping[str, Any]:
        status, payload = await self._get_client().request(method, path, json_body=json_body)
        if status == 200:
            return payload
        if set(payload) == {"error"} and payload.get("error") in _SAFE_ERROR_CODES:
            raise SidecarResponseError(str(payload["error"]), status)
        raise SidecarProtocolViolation("sidecar returned an unbounded error")

    @staticmethod
    def _validate_envelope(payload: Mapping[str, Any], allowed: set[str]) -> str:
        _exact_keys(payload, {"protocol_version", "generation", *allowed})
        if payload.get("protocol_version") != PROTOCOL_VERSION:
            raise SidecarProtocolViolation("sidecar protocol version mismatch")
        return _safe_id(payload.get("generation"))

    def _validate_private_allowlist_metadata(self, payload: Mapping[str, Any]) -> None:
        version = payload.get("private_allowlist_version")
        fingerprint = payload.get("private_allowlist_fingerprint")
        expected_version = getattr(self.config, "active_private_allowlist_version", None)
        expected_fingerprint = getattr(self.config, "active_private_allowlist_fingerprint", None)
        if expected_version is None:
            if version is not None or fingerprint is not None:
                raise SidecarProtocolViolation("inactive private allowlist metadata is exposed")
            return
        if (
            isinstance(version, bool)
            or not isinstance(version, int)
            or version < 1
            or not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in fingerprint)
        ):
            raise SidecarProtocolViolation("private allowlist metadata is invalid")
        if version != expected_version or fingerprint != expected_fingerprint:
            raise SidecarProtocolViolation("private allowlist metadata does not match")

    async def _hello(self) -> tuple[str, int]:
        payload = await self._request("GET", "/v1/hello")
        generation = self._validate_envelope(
            payload,
            {
                "event_cursor",
                "private_allowlist_version",
                "private_allowlist_fingerprint",
            },
        )
        self._validate_private_allowlist_metadata(payload)
        cursor = payload.get("event_cursor")
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise SidecarProtocolViolation("sidecar event cursor is invalid")
        return generation, cursor

    async def _refresh_status(self) -> TransportStatus:
        payload = await self._request("GET", "/v1/status")
        generation = self._validate_envelope(
            payload,
            {
                "configured",
                "gateway_connected",
                "authenticated",
                "bot_id",
                "capture_only",
                "last_event_at_ms",
                "last_heartbeat_ack_at_ms",
                "heartbeat_ack_observable",
                "reason",
                "private_allowlist_version",
                "private_allowlist_fingerprint",
            },
        )
        self._validate_private_allowlist_metadata(payload)
        for key in ("configured", "gateway_connected", "authenticated", "capture_only"):
            if not isinstance(payload.get(key), bool):
                raise SidecarProtocolViolation("sidecar status boolean is invalid")
        if not isinstance(payload.get("heartbeat_ack_observable"), bool):
            raise SidecarProtocolViolation("sidecar heartbeat visibility is invalid")
        reason = payload.get("reason")
        if reason not in _SAFE_REASONS:
            raise SidecarProtocolViolation("sidecar reason is invalid")
        bot_value = payload.get("bot_id")
        account_id = None if bot_value is None else _safe_id(bot_value)
        connected = bool(payload["gateway_connected"])
        authenticated = bool(payload["authenticated"])
        configured = bool(payload["configured"])
        if payload["capture_only"]:
            raise SidecarProtocolViolation(
                "capture-only sidecar cannot enter the business pipeline"
            )
        if authenticated and (not connected or account_id is None):
            raise SidecarProtocolViolation("sidecar authentication state is contradictory")
        heartbeat_ack = _optional_timestamp(payload.get("last_heartbeat_ack_at_ms"))
        if authenticated and (
            not payload["heartbeat_ack_observable"]
            or heartbeat_ack is None
            or not 0 <= self._clock_ms() - heartbeat_ack <= 90_000
        ):
            raise SidecarProtocolViolation("sidecar heartbeat state is not fresh")
        if (
            authenticated
            and self._expected_account_id is not None
            and account_id != self._expected_account_id
        ):
            raise SidecarProtocolViolation("sidecar bot identity changed")
        if authenticated:
            self._expected_account_id = account_id
        generation_changed = self._generation is not None and self._generation != generation
        if generation_changed and reason != "resumed":
            raise SidecarProtocolViolation("sidecar generation changed without a verified Resume")
        if self._generation is None or generation_changed:
            self._generation = generation
            self._cursor = 0
        self._configured = configured
        self._connected = connected
        self._authenticated = authenticated
        self._account_id = account_id or self._expected_account_id
        self._reason = "resumed_new_generation" if generation_changed else str(reason)
        self._last_event_at_ms = _optional_timestamp(payload.get("last_event_at_ms"))
        self._last_heartbeat_ack_at_ms = heartbeat_ack
        status = await self.status()
        self._persist_status(status)
        return status

    def _persist_status(self, status: TransportStatus) -> None:
        if self._transport_state is None:
            return
        now_ms = self._clock_ms()
        signature = (
            status.configured,
            status.connected,
            status.authenticated,
            status.reason,
            status.account_id is not None,
            self._generation,
        )
        if signature == self._last_persisted and now_ms - self._last_persisted_at_ms < 30_000:
            return
        healthy = status.connected and status.authenticated and status.account_id is not None
        try:
            self._transport_state.record_transition(
                "verified" if healthy else "rejected" if self._terminal_failure else "pending",
                reason=status.reason or "official_sidecar_status",
                onebot_reachable=status.connected,
                qq_online=healthy,
                account_match=True if healthy else None,
                health_receipt=("ok" if healthy else "failed", status.reason or "official_sidecar"),
                now_ms=now_ms,
            )
        except Exception as exc:
            raise TransportStatePersistenceError(
                "official transport state persistence failed"
            ) from exc
        self._last_persisted = signature
        self._last_persisted_at_ms = now_ms

    async def start(self) -> None:
        if not self.config.enabled:
            self._terminal_failure = True
            self._reason = "disabled"
            raise TransportUnavailable("official QQ is disabled")
        if self.config.transport != "sidecar" or not self.config.owner_openid:
            self._terminal_failure = True
            self._reason = "configuration_incomplete"
            raise TransportUnavailable("official QQ sidecar configuration is incomplete")
        if self._event_handler is None:
            self._terminal_failure = True
            self._reason = "event_handler_missing"
            raise TransportUnavailable("official QQ sidecar event handler is required")
        self._stop_requested.clear()
        try:
            generation, cursor = await self._hello()
            if self._generation is not None and self._generation != generation:
                raise SidecarProtocolViolation("sidecar generation changed")
            self._generation = generation
            self._cursor = cursor
            self._cursor_resync_required = False
            await self._refresh_status()
        except TransportStatePersistenceError as exc:
            self._terminal_failure = True
            self._connected = False
            self._authenticated = False
            self._reason = "transport_state_failure"
            raise TransportUnavailable("official QQ transport state is unavailable") from exc
        except (SidecarProtocolViolation, SidecarResponseError) as exc:
            self._terminal_failure = True
            self._connected = False
            self._authenticated = False
            self._reason = "protocol_error"
            raise TransportUnavailable("official QQ sidecar protocol is unavailable") from exc
        except Exception as exc:
            self._connected = False
            self._authenticated = False
            self._reason = "sidecar_unavailable"
            raise TransportUnavailable("official QQ sidecar is unavailable") from exc

    async def stop(self) -> None:
        self._stop_requested.set()
        if self._client is not None:
            await self._client.close()
            self._client = None
        self._connected = False
        self._authenticated = False
        self._account_id = None
        self._expected_account_id = None
        self._generation = None
        self._cursor = 0
        self._cursor_resync_required = False
        self._reason = "stopped"

    async def status(self) -> TransportStatus:
        return TransportStatus(
            channel=self.channel,
            configured=self._configured,
            connected=self._connected,
            authenticated=self._authenticated,
            account_id=self._account_id,
            reason=self._reason,
            last_heartbeat_ack_at_ms=self._last_heartbeat_ack_at_ms,
            last_event_at_ms=self._last_event_at_ms,
        )

    def _normalize_event(self, raw: object) -> tuple[int, InboundEvent | None]:
        if not isinstance(raw, dict):
            raise SidecarProtocolViolation("sidecar event must be an object")
        _exact_keys(
            raw,
            {
                "cursor",
                "event_type",
                "kind",
                "bot_id",
                "sender_id",
                "group_id",
                "message_id",
                "occurred_at_ms",
                "received_at_ms",
                "text",
                "attachments",
            },
        )
        cursor = raw.get("cursor")
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor != self._cursor + 1:
            raise SidecarProtocolViolation("sidecar event cursor is not contiguous")
        account_id = _safe_id(raw.get("bot_id"))
        if account_id != self._account_id:
            raise SidecarProtocolViolation("sidecar event bot identity changed")
        sender_id = _safe_id(raw.get("sender_id"))
        message_id = _safe_id(raw.get("message_id"))
        event_type = raw.get("event_type")
        kind_value = raw.get("kind")
        group_value = raw.get("group_id")
        policy_allowed = True
        if event_type == "C2C_MESSAGE_CREATE" and kind_value == "c2c":
            if group_value is not None:
                raise SidecarProtocolViolation("sidecar private event has a group identity")
            is_owner = sender_id == self.config.owner_openid
            if (
                sender_id not in self.config.active_private_openids
                or (not is_owner and not self.config.ordinary_private_enabled)
                or (not is_owner and not self._private_gate.allow(now_ms=self._clock_ms()))
            ):
                policy_allowed = False
            kind = ConversationKind.PRIVATE
            target_id = sender_id
            group_id = None
            mentioned = False
        elif event_type == "GROUP_AT_MESSAGE_CREATE" and kind_value == "group":
            group_id = _safe_id(group_value)
            if (
                not self.config.group_enabled
                or group_id not in self.config.active_group_openids
                or not self._group_gate.allow(now_ms=self._clock_ms())
            ):
                policy_allowed = False
            kind = ConversationKind.GROUP
            target_id = group_id
            mentioned = True
        else:
            raise SidecarProtocolViolation("sidecar event type is not allowed")
        occurred_at_ms = _optional_timestamp(raw.get("occurred_at_ms"))
        received_at_ms = _optional_timestamp(raw.get("received_at_ms"))
        if occurred_at_ms is None or received_at_ms is None:
            raise SidecarProtocolViolation("sidecar event timestamp is missing")
        text = raw.get("text")
        if not isinstance(text, str) or len(text) > MAX_TEXT_LENGTH:
            raise SidecarProtocolViolation("sidecar event text is invalid")
        attachment_values = raw.get("attachments")
        if not isinstance(attachment_values, list) or len(attachment_values) > 8:
            raise SidecarProtocolViolation("sidecar attachments are invalid")
        attachments: list[AttachmentRef] = []
        for attachment in attachment_values:
            if not isinstance(attachment, dict):
                raise SidecarProtocolViolation("sidecar attachment must be an object")
            _exact_keys(attachment, {"content_type", "filename", "size"})
            content_type = attachment.get("content_type")
            filename = attachment.get("filename")
            size = attachment.get("size")
            if not isinstance(content_type, str) or not 1 <= len(content_type) <= 120:
                raise SidecarProtocolViolation("sidecar attachment type is invalid")
            if filename is not None and (not isinstance(filename, str) or len(filename) > 255):
                raise SidecarProtocolViolation("sidecar attachment name is invalid")
            if size is not None and (
                isinstance(size, bool) or not isinstance(size, int) or size < 0
            ):
                raise SidecarProtocolViolation("sidecar attachment size is invalid")
            attachments.append(AttachmentRef(kind=content_type, file_name=filename or None))
        if not policy_allowed:
            return cursor, None
        return cursor, InboundEvent(
            channel=self.channel,
            account_id=account_id,
            sender_id=sender_id,
            message_id=message_id,
            occurred_at_ms=occurred_at_ms,
            conversation_kind=kind,
            conversation_id=f"{self.channel}:{kind.value}:{account_id}:{target_id}",
            group_id=group_id,
            text=text.strip(),
            mentioned=mentioned,
            attachments=tuple(attachments),
        )

    async def _poll_events(self) -> None:
        if not self._connected or not self._authenticated or self._account_id is None:
            return
        payload = await self._request("GET", f"/v1/events?after={self._cursor}&limit=32")
        generation = self._validate_envelope(payload, {"events"})
        if generation != self._generation:
            raise SidecarProtocolViolation("sidecar generation changed during event poll")
        events = payload.get("events")
        if not isinstance(events, list) or len(events) > 32:
            raise SidecarProtocolViolation("sidecar event list is invalid")
        assert self._event_handler is not None
        for raw in events:
            cursor, event = self._normalize_event(raw)
            if event is not None:
                await self._event_handler(event)
            try:
                ack_payload = await self._request(
                    "POST",
                    "/v1/events/ack",
                    json_body={
                        "protocol_version": PROTOCOL_VERSION,
                        "generation": self._generation,
                        "cursor": cursor,
                    },
                )
            except Exception:
                # The sidecar may have committed the ACK before its HTTP response
                # was lost.  Re-read the authoritative cursor before polling again.
                self._cursor_resync_required = True
                raise
            ack_generation = self._validate_envelope(ack_payload, {"event_cursor"})
            ack_cursor = ack_payload.get("event_cursor")
            if ack_generation != self._generation or ack_cursor != cursor:
                raise SidecarProtocolViolation("sidecar event acknowledgement changed")
            self._cursor = cursor

    async def _resync_cursor(self) -> None:
        if not self._cursor_resync_required:
            return
        generation, cursor = await self._hello()
        if generation != self._generation or cursor < self._cursor:
            raise SidecarProtocolViolation("sidecar acknowledgement cursor regressed")
        self._cursor = cursor
        self._cursor_resync_required = False

    async def supervise(
        self,
        *,
        poll_interval_seconds: float = 0.5,
        base_delay_seconds: float = 1.0,
        max_delay_seconds: float = 30.0,
        max_consecutive_failures: int = 5,
    ) -> None:
        if not 0.1 <= poll_interval_seconds <= 30.0:
            raise ValueError("sidecar poll interval must be between 0.1 and 30 seconds")
        if not 0.1 <= base_delay_seconds <= max_delay_seconds <= 60.0:
            raise ValueError("sidecar retry delay bounds are invalid")
        if not 1 <= max_consecutive_failures <= 10:
            raise ValueError("sidecar failure budget must be between 1 and 10")
        failures = 0
        delay = base_delay_seconds
        while not self._stop_requested.is_set() and not self._terminal_failure:
            try:
                await self._refresh_status()
                await self._resync_cursor()
                await self._poll_events()
            except asyncio.CancelledError:
                raise
            except TransportStatePersistenceError:
                self._terminal_failure = True
                self._connected = False
                self._authenticated = False
                self._reason = "transport_state_failure"
                return
            except SidecarResponseError as exc:
                self._terminal_failure = True
                self._connected = False
                self._authenticated = False
                self._reason = exc.code
                self._persist_status(await self.status())
                return
            except SidecarProtocolViolation:
                self._terminal_failure = True
                self._connected = False
                self._authenticated = False
                self._reason = "protocol_error"
                self._persist_status(await self.status())
                return
            except Exception:
                failures += 1
                self._connected = False
                self._authenticated = False
                self._reason = "sidecar_unavailable"
                self._persist_status(await self.status())
                if failures >= max_consecutive_failures:
                    self._terminal_failure = True
                    self._reason = "sidecar_failure_budget_exhausted"
                    self._persist_status(await self.status())
                    return
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop_requested.wait(), timeout=delay)
                delay = min(delay * 2, max_delay_seconds)
                continue
            failures = 0
            delay = base_delay_seconds
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_requested.wait(), timeout=poll_interval_seconds)

    async def send_text(
        self,
        target: OutboundTarget,
        text: str,
        *,
        idempotency_key: str,
        reply_message_id: str | None = None,
    ) -> DeliveryReceipt:
        if not self.config.reply_enabled:
            raise TransportUnavailable("official QQ replies are disabled")
        if target.channel.casefold() != self.channel:
            raise TransportUnavailable("official QQ target channel mismatch")
        try:
            normalized_key = _safe_id(idempotency_key.strip(), maximum=200)
        except SidecarProtocolViolation as exc:
            raise ValueError("official QQ idempotency key is invalid") from exc
        content = text.strip()
        if not content or len(content) > 2000:
            raise ValueError("official QQ text must contain 1-2000 characters")
        delivery_mode = "proactive" if reply_message_id is None else "passive"
        if delivery_mode == "proactive":
            if not self.config.proactive_enabled:
                raise TransportUnavailable("official QQ proactive sends are disabled")
            reply_id = None
        else:
            try:
                reply_id = _safe_id(reply_message_id)
            except SidecarProtocolViolation as exc:
                raise ValueError("official QQ reply message identity is invalid") from exc
        parts = target.conversation_id.split(":")
        account_id = self._account_id
        if (
            len(parts) != 4
            or parts[0] != self.channel
            or parts[1] != target.conversation_kind.value
            or account_id is None
            or parts[2] != account_id
            or not parts[3]
        ):
            raise TransportUnavailable("official QQ target conversation is not canonical")
        try:
            target_id = _safe_id(parts[3])
        except SidecarProtocolViolation as exc:
            raise TransportUnavailable("official QQ target identity is invalid") from exc
        if target.conversation_kind is ConversationKind.PRIVATE:
            kind = "c2c"
            if target_id not in self.config.active_private_openids:
                raise TransportUnavailable("official QQ private target is not allowlisted")
            if target_id != self.config.owner_openid and not self.config.ordinary_private_enabled:
                raise TransportUnavailable("official QQ ordinary private channel is disabled")
            if target_id != self.config.owner_openid and self._private_gate.is_open():
                raise TransportUnavailable("official QQ private channel circuit is open")
        elif target.conversation_kind is ConversationKind.GROUP:
            kind = "group"
            if not self.config.group_enabled:
                raise TransportUnavailable("official QQ group channel is disabled")
            if target_id not in self.config.active_group_openids:
                raise TransportUnavailable("official QQ group target is not allowlisted")
            if self._group_gate.is_open():
                raise TransportUnavailable("official QQ group channel circuit is open")
        else:  # pragma: no cover - enum exhaustiveness
            raise TransportUnavailable("official QQ target kind is invalid")
        if delivery_mode == "proactive" and kind != "c2c":
            raise TransportUnavailable("official QQ proactive sends are owner private only")
        fingerprint = hashlib.sha256(
            "\0".join((delivery_mode, kind, target_id, content, reply_id or "")).encode("utf-8")
        ).hexdigest()
        async with self._send_lock:
            prior = self._receipts.get(normalized_key)
            if prior is not None:
                if self._receipt_fingerprints.get(normalized_key) != fingerprint:
                    raise TransportUnavailable(
                        "official QQ idempotency key conflicts with another request"
                    )
                return prior
            if (
                not self._connected
                or not self._authenticated
                or self._generation is None
                or account_id != self._account_id
            ):
                raise TransportUnavailable("official QQ sidecar is not ready")
            request_id = hashlib.sha256(
                f"higgs-official-request\0{normalized_key}".encode()
            ).hexdigest()
            try:
                payload = await self._request(
                    "POST",
                    "/v1/send",
                    json_body={
                        "protocol_version": PROTOCOL_VERSION,
                        "generation": self._generation,
                        "request_id": request_id,
                        "idempotency_key": normalized_key,
                        "delivery_mode": delivery_mode,
                        "kind": kind,
                        "target_id": target_id,
                        "text": content,
                        "reply_message_id": reply_id,
                    },
                )
                generation = self._validate_envelope(payload, {"receipt"})
                if generation != self._generation:
                    raise SidecarProtocolViolation("sidecar send generation changed")
                receipt_value = payload.get("receipt")
                if not isinstance(receipt_value, dict):
                    raise SidecarProtocolViolation("sidecar receipt is invalid")
                _exact_keys(receipt_value, {"request_id", "state", "provider_message_id"})
                if receipt_value.get("request_id") != request_id:
                    raise SidecarProtocolViolation("sidecar receipt request identity changed")
                state = receipt_value.get("state")
                provider_value = receipt_value.get("provider_message_id")
                if state == "sent":
                    provider_id = _safe_id(provider_value)
                    receipt = DeliveryReceipt(
                        self.channel,
                        DeliveryState.SENT,
                        normalized_key,
                        provider_id,
                    )
                elif state == "unknown" and provider_value is None:
                    receipt = DeliveryReceipt(
                        self.channel,
                        DeliveryState.UNKNOWN,
                        normalized_key,
                    )
                else:
                    raise SidecarProtocolViolation("sidecar receipt state is invalid")
            except SidecarResponseError as exc:
                if exc.code in {
                    "capture_only",
                    "idempotency_collision",
                    "invalid_reply_binding",
                    "invalid_proactive_target",
                    "proactive_disabled",
                    "sidecar_not_configured",
                }:
                    receipt = DeliveryReceipt(
                        self.channel,
                        DeliveryState.FAILED,
                        normalized_key,
                    )
                elif exc.code in {
                    "gateway_unavailable",
                    "stale_generation",
                }:
                    raise TransportUnavailable("official QQ sidecar rejected the send") from exc
                else:
                    receipt = DeliveryReceipt(
                        self.channel,
                        DeliveryState.UNKNOWN,
                        normalized_key,
                    )
            except SidecarProtocolViolation as exc:
                self._terminal_failure = True
                self._connected = False
                self._authenticated = False
                self._reason = "protocol_error"
                self._persist_status(await self.status())
                raise TransportUnavailable("official QQ sidecar protocol failed") from exc
            except Exception:
                self._connected = False
                self._authenticated = False
                self._reason = "sidecar_unavailable"
                receipt = DeliveryReceipt(
                    self.channel,
                    DeliveryState.UNKNOWN,
                    normalized_key,
                )
            if kind != "c2c" or target_id != self.config.owner_openid:
                gate = self._private_gate if kind == "c2c" else self._group_gate
                if receipt.state is DeliveryState.SENT:
                    gate.record_success()
                elif receipt.state is DeliveryState.UNKNOWN:
                    gate.record_failure()
            self._receipts[normalized_key] = receipt
            self._receipt_fingerprints[normalized_key] = fingerprint
            return receipt


__all__ = [
    "HttpxSidecarClient",
    "OfficialQQSidecarAdapter",
    "SidecarClient",
    "SidecarProtocolViolation",
    "SidecarResponseError",
    "TransportStatePersistenceError",
]
