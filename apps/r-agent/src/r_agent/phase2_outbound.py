"""Explicitly gated OneBot action for Phase 2 live mode."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from r_agent.events import ConversationKind, InboundEvent


class OutboundError(RuntimeError):
    """A OneBot action failed, with explicit delivery uncertainty."""

    def __init__(self, message: str, *, delivery_unknown: bool = True) -> None:
        super().__init__(message)
        self.delivery_unknown = delivery_unknown


@dataclass(frozen=True, slots=True)
class OneBotAccountStatus:
    """Authoritative QQ runtime state paired with the active account identity."""

    online: bool
    good: bool
    account_id: str | None
    nickname: str


def _message_id_from_response(response: Mapping[str, object]) -> str:
    """Require a provider message id before considering a send acknowledged."""

    data = response.get("data")
    if not isinstance(data, Mapping):
        raise OutboundError("OneBot send acknowledgement omitted data")
    message_id = data.get("message_id")
    if isinstance(message_id, bool) or message_id is None:
        raise OutboundError("OneBot send acknowledgement omitted message_id")
    normalized = str(message_id).strip()
    if not normalized or len(normalized) > 64:
        raise OutboundError("OneBot send acknowledgement contained an invalid message_id")
    return normalized


async def _wait_for_action_response(socket: Any, *, echo: str) -> Mapping[str, object]:
    """Ignore unrelated events until the response carrying our echo arrives."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 10.0
    for _ in range(64):
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        raw = await asyncio.wait_for(socket.recv(), timeout=remaining)
        if not isinstance(raw, (str, bytes)) or len(raw) > 64 * 1024:
            continue
        try:
            response = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(response, Mapping) and response.get("echo") == echo:
            return response
    raise OutboundError("OneBot action acknowledgement timed out")


async def send_onebot_reply(
    ws_url: str,
    token: str | None,
    event: InboundEvent,
    text: str,
) -> str:
    import websockets

    if not 1 <= len(text) <= 2000:
        raise OutboundError("reply length outside safe bound")
    if event.conversation_kind is ConversationKind.PRIVATE:
        if (
            not event.sender_id.isascii()
            or not event.sender_id.isdigit()
            or len(event.sender_id) > 20
        ):
            raise OutboundError("private target is invalid", delivery_unknown=False)
        action, params = "send_private_msg", {"user_id": int(event.sender_id), "message": text}
    else:
        group_id = event.group_id or ""
        if not group_id.isascii() or not group_id.isdigit() or len(group_id) > 20:
            raise OutboundError("group target is invalid", delivery_unknown=False)
        action, params = (
            "send_group_msg",
            {
                "group_id": int(group_id),
                "message": text,
            },
        )
    headers = {"Authorization": f"Bearer {token}"} if token else None
    echo = f"r-agent-phase2:{event.account_id}:{event.message_id}"
    payload = {"action": action, "params": params, "echo": echo}
    try:
        async with websockets.connect(
            ws_url,
            additional_headers=headers,
            max_size=64 * 1024,
            max_queue=64,
            close_timeout=5,
        ) as socket:
            await socket.send(json.dumps(payload, ensure_ascii=False))
            response = await _wait_for_action_response(socket, echo=echo)
    except OutboundError:
        raise
    except Exception as exc:
        raise OutboundError("OneBot action failed") from exc
    if response.get("status") != "ok" or response.get("retcode") != 0:
        raise OutboundError("OneBot action rejected", delivery_unknown=False)
    return _message_id_from_response(response)


async def get_onebot_message_sender(
    ws_url: str,
    token: str | None,
    message_id: str,
) -> str:
    """Resolve a quoted message sender through a separate fail-closed OneBot action."""
    if not message_id.isascii() or not message_id.isdigit() or len(message_id) > 20:
        raise OutboundError("invalid quoted message id")
    import websockets

    headers = {"Authorization": f"Bearer {token}"} if token else None
    echo = f"r-agent-phase2:get-msg:{message_id}"
    payload = {
        "action": "get_msg",
        "params": {"message_id": int(message_id)},
        "echo": echo,
    }
    try:
        async with websockets.connect(
            ws_url,
            additional_headers=headers,
            max_size=64 * 1024,
            max_queue=64,
            close_timeout=5,
        ) as socket:
            await socket.send(json.dumps(payload, ensure_ascii=False))
            response = await _wait_for_action_response(socket, echo=echo)
    except OutboundError:
        raise
    except Exception as exc:
        raise OutboundError("OneBot get_msg action failed") from exc
    if response.get("status") != "ok" or response.get("retcode") != 0:
        raise OutboundError("OneBot get_msg action rejected", delivery_unknown=False)
    data = response.get("data")
    if not isinstance(data, Mapping):
        raise OutboundError("OneBot get_msg data was malformed")
    sender = data.get("sender")
    user_id = sender.get("user_id") if isinstance(sender, Mapping) else data.get("user_id")
    if isinstance(user_id, bool):
        raise OutboundError("OneBot get_msg sender was malformed")
    normalized = str(user_id)
    if not normalized.isascii() or not normalized.isdigit() or len(normalized) > 20:
        raise OutboundError("OneBot get_msg sender was malformed")
    return normalized


async def call_onebot_action(
    ws_url: str,
    token: str | None,
    *,
    action: str,
    params: Mapping[str, object],
    echo: str,
) -> Mapping[str, object]:
    """Run one bounded action on a separate socket and validate acknowledgement."""
    import websockets

    headers = {"Authorization": f"Bearer {token}"} if token else None
    payload = {"action": action, "params": dict(params), "echo": echo}
    try:
        async with websockets.connect(
            ws_url,
            additional_headers=headers,
            max_size=64 * 1024,
            max_queue=64,
            close_timeout=5,
        ) as socket:
            await socket.send(json.dumps(payload, ensure_ascii=False))
            response = await _wait_for_action_response(socket, echo=echo)
    except OutboundError:
        raise
    except Exception as exc:
        raise OutboundError(f"OneBot {action} action failed") from exc
    if response.get("status") != "ok" or response.get("retcode") != 0:
        raise OutboundError(f"OneBot {action} action rejected", delivery_unknown=False)
    return response


async def get_onebot_login_info(ws_url: str, token: str | None) -> tuple[str, str]:
    """Actively confirm the QQ account that NapCat reports as online."""
    response = await call_onebot_action(
        ws_url,
        token,
        action="get_login_info",
        params={},
        echo="r-agent:online-probe",
    )
    data = response.get("data")
    if not isinstance(data, Mapping):
        raise OutboundError("OneBot get_login_info data was malformed")
    user_id = data.get("user_id")
    nickname = data.get("nickname", "")
    normalized = str(user_id)
    if not normalized.isascii() or not normalized.isdigit() or len(normalized) > 20:
        raise OutboundError("OneBot get_login_info user was malformed")
    return normalized, str(nickname)[:100]


async def get_onebot_account_status(
    ws_url: str,
    token: str | None,
) -> OneBotAccountStatus:
    """Require OneBot's runtime status before treating login identity as online."""
    response = await call_onebot_action(
        ws_url,
        token,
        action="get_status",
        params={},
        echo="r-agent:status-probe",
    )
    data = response.get("data")
    if not isinstance(data, Mapping):
        raise OutboundError("OneBot get_status data was malformed")
    online = data.get("online")
    good = data.get("good")
    if not isinstance(online, bool) or not isinstance(good, bool):
        raise OutboundError("OneBot get_status flags were malformed")
    if not online or not good:
        return OneBotAccountStatus(
            online=online,
            good=good,
            account_id=None,
            nickname="",
        )
    account_id, nickname = await get_onebot_login_info(ws_url, token)
    return OneBotAccountStatus(
        online=True,
        good=True,
        account_id=account_id,
        nickname=nickname,
    )


async def send_onebot_private_message(
    ws_url: str,
    token: str | None,
    *,
    user_id: str,
    text: str,
    idempotency_key: str,
) -> str | None:
    """Send an owner reminder and return the provider message id when available."""
    if not user_id.isascii() or not user_id.isdigit() or len(user_id) > 20:
        raise OutboundError("private target is invalid")
    if not 1 <= len(text) <= 2000:
        raise OutboundError("reply length outside safe bound")
    safe_key = "".join(ch for ch in idempotency_key if ch.isalnum() or ch in {"-", ":"})[:80]
    if not safe_key:
        raise OutboundError("idempotency key is invalid")
    response = await call_onebot_action(
        ws_url,
        token,
        action="send_private_msg",
        params={"user_id": int(user_id), "message": text},
        echo=f"r-agent:private:{safe_key}",
    )
    try:
        return _message_id_from_response(response)
    except OutboundError:
        # The action was accepted but delivery cannot be correlated without the
        # provider id.  Callers must surface this as UNKNOWN rather than SENT.
        return None


async def send_onebot_group_message(
    ws_url: str,
    token: str | None,
    *,
    group_id: str,
    text: str,
    idempotency_key: str,
) -> str | None:
    """Send a group reminder and require a matching OneBot acknowledgement."""
    if not group_id.isascii() or not group_id.isdigit() or len(group_id) > 20:
        raise OutboundError("group target is invalid", delivery_unknown=False)
    if not 1 <= len(text) <= 2000:
        raise OutboundError("reply length outside safe bound", delivery_unknown=False)
    safe_key = "".join(ch for ch in idempotency_key if ch.isalnum() or ch in {"-", ":"})[:80]
    if not safe_key:
        raise OutboundError("idempotency key is invalid", delivery_unknown=False)
    response = await call_onebot_action(
        ws_url,
        token,
        action="send_group_msg",
        params={"group_id": int(group_id), "message": text},
        echo=f"r-agent:group:{safe_key}",
    )
    try:
        return _message_id_from_response(response)
    except OutboundError:
        # See the private helper: an accepted action without an id is unknown.
        return None
