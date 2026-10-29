"""End-to-end M2: the real runtime runs a tool call and replies in the group."""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
from pathlib import Path

import pytest
from napcat_sim import BOT_QQ, OWNER_QQ, FakeNapCat, RecordingModel, live_env

from r_agent import phase2_cli
from r_agent.model_client import ChatResult, ToolCall


async def _wait_until(predicate, timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError("condition not reached")
        await asyncio.sleep(0.05)


def _brain(messages, tools):
    names = {tool["function"]["name"] for tool in tools or []}
    if messages[-1]["role"] == "tool":
        return ChatResult("好，记下了：你喜欢拍银河。")
    if "记住" in messages[-1]["content"] and "remember" in names:
        return ChatResult(
            None, (ToolCall("c1", "remember", '{"fact": "主人喜欢拍银河", "kind": "preference"}'),)
        )
    return ChatResult("嗯。")


@pytest.mark.asyncio
async def test_owner_asks_higgs_to_remember_in_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "sim.env").write_text("", encoding="utf-8")
    model = RecordingModel(chat_responder=_brain)
    monkeypatch.setattr(phase2_cli, "_model_client", lambda *, required: model)
    async with FakeNapCat() as napcat:
        live_env(monkeypatch, data_dir=str(tmp_path), ws_url=napcat.url)
        runtime = asyncio.create_task(phase2_cli.listen())
        try:
            await napcat.wait_for_clients()
            await asyncio.sleep(0.3)
            await napcat.push_group_message(
                message_id=201,
                user_id=OWNER_QQ,
                card="丘山",
                segments=[
                    {"type": "at", "data": {"qq": str(BOT_QQ)}},
                    {"type": "text", "data": {"text": "记住我喜欢拍银河"}},
                ],
            )
            await _wait_until(lambda: len(napcat.sent()) >= 1)
        finally:
            runtime.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await runtime

    message = napcat.sent()[0]["params"]["message"]
    text = (
        message
        if isinstance(message, str)
        else "".join(s["data"].get("text", "") for s in message if s["type"] == "text")
    )
    assert "记下了" in text
    tools_offered = {t["function"]["name"] for t in model.chat_calls[0][1]}
    assert {
        "remember",
        "create_reminder",
        "search_group_history",
        "get_current_time",
    } <= tools_offered
    with sqlite3.connect(tmp_path / "memory.sqlite") as conn:
        rows = conn.execute("SELECT text, status FROM memory_items").fetchall()
    assert ("主人喜欢拍银河", "active") in rows
    with sqlite3.connect(tmp_path / "agent_tools.sqlite") as conn:
        assert conn.execute("SELECT tool, outcome FROM agent_tool_calls").fetchall() == [
            ("remember", "ok")
        ]
