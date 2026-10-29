import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from r_agent.agent_tools import AgentLoop, AgentTool, ToolAudit, ToolContext, ToolRegistry
from r_agent.builtin_tools import SHANGHAI, BuiltinToolDeps, register_builtin_tools
from r_agent.events import ConversationKind, InboundEvent
from r_agent.group_timeline import GroupTimeline
from r_agent.memory import MemoryScope, MemoryStore
from r_agent.model_client import ChatResult, ModelError, ToolCall, parse_chat_body
from r_agent.reminders import ReminderStore
from r_agent.web_providers import SearxngSearch, ZhipuWebSearch

NOW = datetime(2026, 10, 29, 20, 0, tzinfo=SHANGHAI)


def event(
    kind: ConversationKind = ConversationKind.PRIVATE, sender: str = "800009"
) -> InboundEvent:
    group = kind is ConversationKind.GROUP
    return InboundEvent(
        channel="qq",
        account_id="900001",
        sender_id=sender,
        message_id="42",
        occurred_at_ms=int(NOW.timestamp() * 1000),
        conversation_kind=kind,
        conversation_id="qq:group:900001:700001" if group else f"qq:private:900001:{sender}",
        group_id="700001" if group else None,
        text="hi",
        mentioned=True,
        sender_name="丘山",
    )


class ScriptedClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def chat(self, *, messages, tools=None, max_tokens=600):
        self.calls.append(([dict(m) for m in messages], tools))
        return self.script.pop(0)

    async def complete_messages(self, *, messages, max_tokens=400):
        return "plain"


def loop(tmp_path: Path, client, registry: ToolRegistry, **kw) -> AgentLoop:
    audit = ToolAudit(tmp_path / "agent_tools.sqlite")
    audit.initialize()
    return AgentLoop(client=client, registry=registry, audit=audit, **kw)


def deps(tmp_path: Path, **extra) -> BuiltinToolDeps:
    memory = MemoryStore(tmp_path / "memory.sqlite")
    memory.initialize()
    reminders = ReminderStore(tmp_path / "reminders.sqlite")
    reminders.initialize()
    return BuiltinToolDeps(memory=memory, reminders=reminders, now=lambda: NOW, **extra)


def test_parse_chat_body_tool_calls_and_content() -> None:
    body = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {"id": "c1", "function": {"name": "get_current_time", "arguments": {}}}
                    ],
                }
            }
        ]
    }
    result = parse_chat_body(body)
    assert result.content is None
    assert result.tool_calls == (ToolCall("c1", "get_current_time", "{}"),)
    assert result.assistant_message()["tool_calls"][0]["function"]["name"] == "get_current_time"
    with pytest.raises(ModelError):
        parse_chat_body({"choices": [{"message": {"content": "  "}}]})


async def test_loop_executes_tool_then_answers(tmp_path: Path) -> None:
    registry = ToolRegistry()
    register_builtin_tools(registry, BuiltinToolDeps(now=lambda: NOW))
    client = ScriptedClient(
        [
            ChatResult(None, (ToolCall("c1", "get_current_time", "{}"),)),
            ChatResult("现在是晚上八点。"),
        ]
    )
    agent = loop(tmp_path, client, registry)
    ctx = ToolContext(event(), "p-owner", "owner")
    reply = await agent.run(
        [{"role": "system", "content": "S"}, {"role": "user", "content": "几点"}], ctx
    )
    assert reply == "现在是晚上八点。"
    second_messages = client.calls[1][0]
    assert second_messages[-1]["role"] == "tool"
    assert "2026-10-29 20:00" in second_messages[-1]["content"]
    assert "# 你可以使用的工具" in second_messages[0]["content"]
    assert agent.audit.recent(1)[0][1:] == ("get_current_time", "ok")


async def test_owner_only_tools_hidden_from_users_and_unknown_rejected(tmp_path: Path) -> None:
    registry = ToolRegistry()
    register_builtin_tools(registry, deps(tmp_path))
    user_ctx = ToolContext(event(sender="800001"), "p-user", "user")
    owner_ctx = ToolContext(event(), "p-owner", "owner")
    assert "create_reminder" not in {t.name for t in registry.available(user_ctx)}
    assert "create_reminder" in {t.name for t in registry.available(owner_ctx)}
    client = ScriptedClient(
        [
            ChatResult(None, (ToolCall("c1", "create_reminder", '{"content":"x"}'),)),
            ChatResult("做不到"),
        ]
    )
    agent = loop(tmp_path, client, registry)
    await agent.run(
        [{"role": "system", "content": "S"}, {"role": "user", "content": "u"}], user_ctx
    )
    assert "无权" in client.calls[1][0][-1]["content"]


async def test_budget_and_bad_arguments(tmp_path: Path) -> None:
    registry = ToolRegistry()
    register_builtin_tools(registry, deps(tmp_path))
    ctx = ToolContext(event(sender="800001"), "p-user", "user")
    client = ScriptedClient(
        [
            ChatResult(None, (ToolCall("c1", "search_memory", "not json"),)),
            ChatResult(None, (ToolCall("c2", "search_memory", '{"query":"相机"}'),)),
            ChatResult("ok"),
        ]
    )
    agent = loop(tmp_path, client, registry, user_daily_budget=1)
    await agent.run([{"role": "system", "content": "S"}, {"role": "user", "content": "u"}], ctx)
    assert "参数无效" in client.calls[1][0][-1]["content"]
    assert "次数已用完" in client.calls[2][0][-1]["content"]


async def test_loop_stops_after_max_steps(tmp_path: Path) -> None:
    registry = ToolRegistry()
    register_builtin_tools(registry, BuiltinToolDeps(now=lambda: NOW))
    call = ChatResult(None, (ToolCall("c", "get_current_time", "{}"),))
    client = ScriptedClient([call, call, ChatResult("最终")])
    agent = loop(tmp_path, client, registry, max_steps=2)
    ctx = ToolContext(event(), "p", "owner")
    assert (
        await agent.run([{"role": "system", "content": "S"}, {"role": "user", "content": "u"}], ctx)
        == "最终"
    )
    assert client.calls[-1][1] is None


async def test_remember_owner_active_user_candidate_sensitive_blocked(tmp_path: Path) -> None:
    d = deps(tmp_path)
    registry = ToolRegistry()
    register_builtin_tools(registry, d)
    tool = registry.tools["remember"]
    owner = ToolContext(event(), "p-owner", "owner")
    user = ToolContext(event(sender="800001"), "p-user", "user")
    assert "已记住" in await tool.handler({"fact": "主人喜欢拍银河"}, owner)
    assert "候选" in await tool.handler({"fact": "该用户喜欢猫"}, user)
    assert "候选" in await tool.handler({"fact": "主人的银行卡号是123"}, owner)
    active = d.memory.list_active_for_scope(
        scope=MemoryScope.PRINCIPAL, scope_id="p-owner", limit=10
    )
    assert [item.text for item in active] == ["主人喜欢拍银河"]
    found = await registry.tools["search_memory"].handler({"query": "银河"}, owner)
    assert "主人喜欢拍银河" in found
    assert "银河" not in await registry.tools["search_memory"].handler({"query": "银河"}, user)


async def test_create_reminder_pending(tmp_path: Path) -> None:
    d = deps(tmp_path)
    registry = ToolRegistry()
    register_builtin_tools(registry, d)
    ctx = ToolContext(event(), "p-owner", "owner")
    out = json.loads(
        await registry.tools["create_reminder"].handler(
            {"content": "开会", "minutes_from_now": 30}, ctx
        )
    )
    assert "确认" in out["status"] and "2026-10-29 20:30" in out["detail"]
    bad = registry.tools["create_reminder"].handler(
        {"content": "x", "due_time": "2020-01-01 00:00"}, ctx
    )
    with pytest.raises(Exception, match="未来"):
        await bad


async def test_search_group_history(tmp_path: Path) -> None:
    timeline = GroupTimeline(tmp_path / "tl.sqlite")
    timeline.initialize()
    old = event(ConversationKind.GROUP, sender="800001")
    from dataclasses import replace

    timeline.record_inbound(
        replace(
            old,
            message_id="1",
            text="下周六去爬山",
            sender_name="小明",
            occurred_at_ms=old.occurred_at_ms - 3_600_000,
        )
    )
    registry = ToolRegistry()
    register_builtin_tools(registry, BuiltinToolDeps(group_timeline=timeline, now=lambda: NOW))
    ctx = ToolContext(event(ConversationKind.GROUP), "p", "user")
    out = await registry.tools["search_group_history"].handler({"keyword": "爬山"}, ctx)
    assert "小明#" in out and "下周六去爬山" in out and "800001" not in out
    assert "search_group_history" not in {
        t.name for t in registry.available(ToolContext(event(), "p", "user"))
    }


async def test_web_providers_parse_responses() -> None:
    def zhipu(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer k"
        assert json.loads(request.content)["search_query"] == "天气"
        return httpx.Response(
            200,
            json={
                "search_result": [
                    {
                        "title": "北京天气",
                        "link": "https://w.example/1",
                        "content": "晴 " * 200,
                        "media": "天气网",
                    }
                ]
            },
        )

    results = await ZhipuWebSearch(api_key="k", transport=httpx.MockTransport(zhipu)).search("天气")
    assert results[0]["title"] == "北京天气" and len(results[0]["snippet"]) <= 300

    def searx(request: httpx.Request) -> httpx.Response:
        assert request.url.params["format"] == "json"
        return httpx.Response(
            200, json={"results": [{"title": "t", "url": "https://a", "content": "c"}]}
        )

    out = await SearxngSearch(
        endpoint="https://s.example/search", transport=httpx.MockTransport(searx)
    ).search("q")
    assert out == [{"title": "t", "url": "https://a", "snippet": "c"}]


async def test_falls_back_to_plain_completion_without_chat(tmp_path: Path) -> None:
    class Plain:
        async def complete_messages(self, *, messages, max_tokens=400):
            return "plain"

    registry = ToolRegistry()
    registry.register(AgentTool("t", "d", {"type": "object", "properties": {}}, lambda a, c: None))
    agent = loop(tmp_path, Plain(), registry)
    out = await agent.run(
        [{"role": "system", "content": "S"}, {"role": "user", "content": "u"}],
        ToolContext(event(), "p", "owner"),
    )
    assert out == "plain"
