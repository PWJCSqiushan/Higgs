"""Explicitly gated OneBot action for Phase 2 live mode."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

from r_agent.events import ConversationKind, InboundEvent


class OutboundError(RuntimeError):
    """A OneBot action was not acknowledged safely."""


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
) -> None:
    import websockets

    if not 1 <= len(text) <= 2000:
        raise OutboundError("reply length outside safe bound")
    if event.conversation_kind is ConversationKind.PRIVATE:
        action, params = "send_private_msg", {"user_id": int(event.sender_id), "message": text}
    else:
        action, params = (
            "send_group_msg",
            {
                "group_id": int(event.group_id or ""),
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
    if response.get("status") != "ok" or response.get("retcode") not in {0, None}:
        raise OutboundError("OneBot action rejected")


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
    if response.get("status") != "ok" or response.get("retcode") not in {0, None}:
        raise OutboundError("OneBot get_msg action rejected")
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
