from __future__ import annotations

import time
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from qqbot_agent_sdk import QQApiClient, QQWebSocket, WSCallbacks
from qqbot_agent_sdk.dto import CloseAction, OPCode, classify_close_code


def callbacks(*, session: tuple[str | None, int | None] = (None, None)) -> WSCallbacks:
    return WSCallbacks(
        on_message_event=AsyncMock(),
        on_connected=Mock(),
        on_disconnected=Mock(),
        on_fatal_error=Mock(),
        get_token=Mock(return_value="token"),
        get_session=Mock(return_value=session),
        set_session=Mock(),
        set_heartbeat_interval=Mock(),
        clear_token=Mock(),
        fail_pending=Mock(),
        get_gateway_url=Mock(return_value="wss://gateway.invalid"),
        on_heartbeat_ack=Mock(),
    )


@pytest.mark.asyncio
async def test_pinned_sdk_identify_and_resume_payloads() -> None:
    identify_cb = callbacks()
    identify = QQWebSocket(identify_cb, log_tag="contract")
    identify._ws = AsyncMock()  # type: ignore[attr-defined]
    identify._ws.closed = False  # type: ignore[attr-defined]
    await identify._send_identify()  # type: ignore[attr-defined]
    identify_payload = identify._ws.send_json.call_args.args[0]  # type: ignore[attr-defined]
    assert identify_payload["op"] == OPCode.IDENTIFY
    assert identify_payload["d"]["token"] == "QQBot token"
    assert identify_payload["d"]["intents"] > 0

    resume_cb = callbacks(session=("session-id", 42))
    resume = QQWebSocket(resume_cb, log_tag="contract")
    resume._ws = AsyncMock()  # type: ignore[attr-defined]
    resume._ws.closed = False  # type: ignore[attr-defined]
    await resume._send_resume()  # type: ignore[attr-defined]
    resume_payload = resume._ws.send_json.call_args.args[0]  # type: ignore[attr-defined]
    assert resume_payload == {
        "op": OPCode.RESUME,
        "d": {"token": "QQBot token", "session_id": "session-id", "seq": 42},
    }


def test_pinned_sdk_hello_invalid_session_dedup_and_ack_contract() -> None:
    cb = callbacks()
    websocket = QQWebSocket(cb, log_tag="contract")
    scheduled: list[str] = []

    def capture(coroutine: object) -> None:
        scheduled.append(coroutine.cr_code.co_name)  # type: ignore[attr-defined]
        coroutine.close()  # type: ignore[attr-defined]

    websocket._create_task = capture  # type: ignore[method-assign]
    websocket._handle_hello({"heartbeat_interval": 30_000})  # type: ignore[attr-defined]
    assert scheduled == ["_send_identify"]
    cb.set_heartbeat_interval.assert_called_once_with(24.0)

    websocket._close_ws_async = Mock()  # type: ignore[method-assign]
    websocket._dispatch_payload({"op": OPCode.INVALID_SESSION, "d": False})  # type: ignore[attr-defined]
    cb.set_session.assert_called_with(None, None)
    assert websocket._is_duplicate("message-id") is False  # type: ignore[attr-defined]
    assert websocket._is_duplicate("message-id") is True  # type: ignore[attr-defined]
    websocket._handle_heartbeat_ack()  # type: ignore[attr-defined]
    cb.on_heartbeat_ack.assert_called_once()


def test_pinned_sdk_close_code_policy_is_fail_closed() -> None:
    assert classify_close_code(4008) is CloseAction.RATE_LIMIT
    assert classify_close_code(4009) is CloseAction.RESUME_OK
    assert classify_close_code(4006) is CloseAction.IDENTIFY_ONLY
    assert classify_close_code(4013) is CloseAction.STOP
    assert classify_close_code(4014) is CloseAction.STOP


def test_pinned_sdk_refreshes_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"access_token": "fresh-token", "expires_in": 7200}
    monkeypatch.setattr(httpx, "post", Mock(return_value=response))
    client = QQApiClient("123456", "a-secure-client-secret", log_tag="contract")
    client._access_token = "expired-token"  # type: ignore[attr-defined]
    client._token_expires_at = time.time() - 1  # type: ignore[attr-defined]

    assert client.ensure_token_sync() == "fresh-token"
