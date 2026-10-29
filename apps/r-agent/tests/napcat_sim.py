"""In-process fake NapCat (OneBot v11 forward WebSocket) for end-to-end tests.

It answers the actions Higgs uses, records every action it receives, and can
push message events to all connected clients.  Reused by later milestones
(tool loop, QZone, proactive behaviour) so the full ``phase2_cli.listen``
runtime can be exercised without a real QQ account.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import Mapping
from typing import Any

import websockets

BOT_QQ = 900001
OWNER_QQ = 800009
GROUP = 700001


class FakeNapCat:
    def __init__(self) -> None:
        self.actions: list[dict[str, Any]] = []
        self.messages: dict[int, dict[str, Any]] = {}
        self._clients: set[Any] = set()
        self._next_message_id = 5000
        self._server: Any = None
        self.port = 0

    async def __aenter__(self) -> FakeNapCat:
        self._server = await websockets.serve(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *args: object) -> None:
        self._server.close()
        with contextlib.suppress(Exception):
            await self._server.wait_closed()

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}"

    async def _handle(self, socket: Any) -> None:
        self._clients.add(socket)
        try:
            async for raw in socket:
                request = json.loads(raw)
                request["_received_at"] = time.time()
                self.actions.append(request)
                await socket.send(json.dumps(self._respond(request), ensure_ascii=False))
        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(socket)

    def _respond(self, request: Mapping[str, Any]) -> dict[str, Any]:
        action = request.get("action")
        params = request.get("params") or {}
        data: Any = {}
        if action == "get_status":
            data = {"online": True, "good": True}
        elif action == "get_login_info":
            data = {"user_id": BOT_QQ, "nickname": "Higgs"}
        elif action in {"send_group_msg", "send_private_msg"}:
            self._next_message_id += 1
            data = {"message_id": self._next_message_id}
            message = params.get("message")
            segments = (
                message
                if isinstance(message, list)
                else [{"type": "text", "data": {"text": message}}]
            )
            self.messages[self._next_message_id] = {
                "self_id": BOT_QQ,
                "user_id": BOT_QQ,
                "time": int(time.time()),
                "group_id": params.get("group_id"),
                "sender": {"user_id": BOT_QQ, "nickname": "Higgs", "card": ""},
                "message": segments,
            }
        elif action == "get_msg":
            stored = self.messages.get(int(params.get("message_id", 0)))
            if stored is None:
                return {"status": "failed", "retcode": 1404, "echo": request.get("echo")}
            data = stored
        return {"status": "ok", "retcode": 0, "data": data, "echo": request.get("echo")}

    async def wait_for_clients(self, timeout: float = 5.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while not self._clients:
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError("Higgs never connected to the fake NapCat")
            await asyncio.sleep(0.02)

    async def push_group_message(
        self,
        *,
        message_id: int,
        user_id: int,
        card: str,
        segments: list[dict[str, Any]],
        at_seconds: int | None = None,
    ) -> None:
        payload = {
            "post_type": "message",
            "message_type": "group",
            "time": at_seconds if at_seconds is not None else int(time.time()),
            "self_id": BOT_QQ,
            "group_id": GROUP,
            "message_id": message_id,
            "user_id": user_id,
            "sender": {"user_id": user_id, "nickname": card, "card": card},
            "message": segments,
        }
        self.messages[message_id] = payload
        frame = json.dumps(payload, ensure_ascii=False)
        for client in list(self._clients):
            with contextlib.suppress(Exception):
                await client.send(frame)

    def sent(self, action: str = "send_group_msg") -> list[dict[str, Any]]:
        return [item for item in self.actions if item.get("action") == action]


class RecordingModel:
    """Fake OpenAI-compatible client returning scripted replies."""

    def __init__(
        self,
        replies: list[str] | None = None,
        *,
        responder: Any = None,
        chat_responder: Any = None,
    ) -> None:
        self.replies = list(replies or [])
        self.responder = responder
        self.chat_responder = chat_responder
        self.chat_calls: list[tuple[list[dict[str, Any]], Any]] = []
        if chat_responder is not None:
            self.chat = self._chat  # type: ignore[attr-defined]
        self.calls: list[tuple[dict[str, str], ...]] = []

    async def complete(self, *, system: str, user: str, max_tokens: int = 400) -> str:
        return await self.complete_messages(
            messages=({"role": "system", "content": system}, {"role": "user", "content": user}),
            max_tokens=max_tokens,
        )

    async def complete_messages(self, *, messages: Any, max_tokens: int = 400) -> str:
        call = tuple(dict(item) for item in messages)
        self.calls.append(call)
        if self.responder is not None:
            return self.responder(call)
        return self.replies.pop(0) if self.replies else "好的。"

    async def _chat(self, *, messages: Any, tools: Any = None, max_tokens: int = 600) -> Any:
        snapshot = [dict(item) for item in messages]
        self.chat_calls.append((snapshot, tools))
        return self.chat_responder(snapshot, tools)


def live_env(monkeypatch: Any, *, data_dir: str, ws_url: str) -> None:
    """Minimal live-mode environment for one whitelisted group."""
    values = {
        "R_AGENT_ENV_FILE": f"{data_dir}/sim.env",
        "R_AGENT_DATA_DIR": data_dir,
        "R_AGENT_ONEBOT_WS_URL": ws_url,
        "R_AGENT_SHADOW_MODE": "false",
        "R_AGENT_REPLY_MODE": "live",
        "R_AGENT_PHASE2_ENABLE_LIVE": "true",
        "R_AGENT_OWNER_QQ": str(OWNER_QQ),
        "R_AGENT_EXPECTED_BOT_QQ": str(BOT_QQ),
        "R_AGENT_ALLOWED_PRIVATE_QQS": str(OWNER_QQ),
        "R_AGENT_REPLY_ALLOWED_PRIVATE_QQS": str(OWNER_QQ),
        "R_AGENT_ALLOWED_GROUPS": str(GROUP),
        "R_AGENT_REPLY_ALLOWED_GROUPS": str(GROUP),
        "R_AGENT_REPLY_GROUP_REQUIRE_MENTION": "true",
        "R_AGENT_GROUP_DEBOUNCE_SECONDS": "0.5",
        "R_AGENT_MODEL_API_KEY": "sim-not-a-real-key",
        "R_AGENT_EMBEDDING_ENABLED": "false",
        "R_AGENT_SAFETY_ENABLED": "false",
        "R_AGENT_REPLY_MAX_PER_MINUTE": "5",
        "R_AGENT_REPLY_GLOBAL_MAX_PER_MINUTE": "20",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
