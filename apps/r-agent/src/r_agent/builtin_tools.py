"""Built-in Higgs agent tools (M2): time, memory, reminders, web, group history."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from r_agent.agent_tools import (
    AgentTool,
    ToolContext,
    ToolInputError,
    ToolRegistry,
    as_json,
    parse_due_time,
    text_arg,
)
from r_agent.group_timeline import GroupTimeline, speaker_label
from r_agent.identity import Principal
from r_agent.memory import MemoryKind, MemoryRisk, MemoryScope, MemoryStore
from r_agent.reminders import ReminderError, ReminderStore, format_job

SHANGHAI = ZoneInfo("Asia/Shanghai")
_WEEKDAYS = "一二三四五六日"
_SENSITIVE_HINTS = (
    "密码",
    "验证码",
    "身份证",
    "银行卡",
    "卡号",
    "住址",
    "地址",
    "手机号",
    "电话",
    "token",
    "密钥",
    "api key",
    "主人",
    "管理员",
    "权限",
    "系统提示",
)


class WebSearch(Protocol):
    async def search(self, query: str) -> list[dict[str, str]]: ...


class WebReader(Protocol):
    async def read(self, url: str) -> dict[str, str]: ...


@dataclass(slots=True)
class BuiltinToolDeps:
    memory: MemoryStore | None = None
    reminders: ReminderStore | None = None
    group_timeline: GroupTimeline | None = None
    owner_ids: frozenset[str] = frozenset()
    web_search: WebSearch | None = None
    web_reader: WebReader | None = None
    now: Any = None  # optional callable returning aware datetime (tests)

    def current_time(self) -> datetime:
        return self.now() if callable(self.now) else datetime.now(SHANGHAI)


_NO_ARGS: Mapping[str, Any] = {"type": "object", "properties": {}}


def register_builtin_tools(registry: ToolRegistry, deps: BuiltinToolDeps) -> None:
    async def get_current_time(_args: Mapping[str, Any], _ctx: ToolContext) -> str:
        now = deps.current_time()
        return as_json(
            {"北京时间": now.strftime("%Y-%m-%d %H:%M"), "星期": f"星期{_WEEKDAYS[now.weekday()]}"}
        )

    registry.register(
        AgentTool(
            name="get_current_time",
            description="获取当前北京时间和星期。涉及日期、时间、倒计时时调用。",
            parameters=_NO_ARGS,
            handler=get_current_time,
        )
    )

    if deps.memory is not None:
        memory = deps.memory

        async def search_memory(args: Mapping[str, Any], ctx: ToolContext) -> str:
            query = text_arg(args, "query", limit=100)
            items = await asyncio.to_thread(
                memory.search_active,
                scope=MemoryScope.PRINCIPAL,
                scope_id=ctx.principal_id,
                query=query,
                limit=8,
            )
            if not items:
                keywords = [part for part in query.replace("，", " ").split() if part][:3]
                for keyword in keywords:
                    items = await asyncio.to_thread(
                        memory.search_active,
                        scope=MemoryScope.PRINCIPAL,
                        scope_id=ctx.principal_id,
                        query=keyword,
                        limit=8,
                    )
                    if items:
                        break
            return as_json(
                {"memories": [f"[{item.kind.value}] {item.text}" for item in items]}
                if items
                else {"memories": [], "note": "没有找到关于对方的相关记忆"}
            )

        registry.register(
            AgentTool(
                name="search_memory",
                description="在你对当前说话人的长期记忆里搜索（只能查到这个人自己的记忆）。",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "关键词"}},
                    "required": ["query"],
                },
                handler=search_memory,
            )
        )

        async def remember(args: Mapping[str, Any], ctx: ToolContext) -> str:
            fact = text_arg(args, "fact", limit=200)
            kind_raw = args.get("kind", "user_fact")
            kinds = {"user_fact", "preference", "commitment", "relationship"}
            if kind_raw not in kinds:
                raise ToolInputError("kind 只能是 user_fact/preference/commitment/relationship")
            hints = [h for h in _SENSITIVE_HINTS if not (ctx.is_owner and h == "主人")]
            sensitive = any(hint in fact.casefold() for hint in hints)
            record = await asyncio.to_thread(
                memory.propose,
                scope=MemoryScope.PRINCIPAL,
                scope_id=ctx.principal_id,
                kind=MemoryKind(kind_raw),
                text=fact,
                source_channel=ctx.event.channel,
                source_account_id=ctx.event.account_id,
                source_message_id=ctx.event.message_id,
                source_principal_id=ctx.principal_id,
                source_principal_role=ctx.principal_role,
                created_by="agent_tool_remember",
                risk=MemoryRisk.HIGH if sensitive else MemoryRisk.LOW,
                confidence=0.9 if ctx.is_owner else 0.6,
                importance=0.6,
                source_trust=0.9 if ctx.is_owner else 0.5,
            )
            if ctx.is_owner and not sensitive:
                actor = Principal(ctx.principal_id, "owner")
                await asyncio.to_thread(
                    memory.activate, record.item_id, actor=actor, reason="主人明确要求记住"
                )
                return as_json({"status": "已记住", "id": record.item_id[:8]})
            return as_json(
                {
                    "status": "已作为候选记下，等主人审核后才会长期生效",
                    "id": record.item_id[:8],
                }
            )

        registry.register(
            AgentTool(
                name="remember",
                description=(
                    "当对方明确要你记住关于他自己的某件事时调用，例如喜好、计划、约定。"
                    "不要用来记密码、证件、住址等隐私。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "fact": {"type": "string", "description": "以第三人称写的一句话事实"},
                        "kind": {
                            "type": "string",
                            "enum": ["user_fact", "preference", "commitment", "relationship"],
                        },
                    },
                    "required": ["fact"],
                },
                handler=remember,
            )
        )

    if deps.reminders is not None:
        reminders = deps.reminders

        async def create_reminder(args: Mapping[str, Any], ctx: ToolContext) -> str:
            content = text_arg(args, "content", limit=200)
            due = parse_due_time(args, now=deps.current_time())
            event = ctx.event
            target = event.group_id if ctx.in_group else event.sender_id
            if not target:
                raise ToolInputError("无法确定提醒发送对象")
            try:
                job = await asyncio.to_thread(
                    reminders.create_pending,
                    owner_principal_id=ctx.principal_id,
                    owner_qq=event.sender_id,
                    content=content,
                    due_at_ms=int(due.timestamp() * 1000),
                    origin_channel=event.channel,
                    origin_surface=event.conversation_kind.value,
                    origin_conversation_id=event.conversation_id,
                    delivery_channel=event.channel,
                    delivery_surface=event.conversation_kind.value,
                    delivery_account_id=event.account_id,
                    delivery_target_id=target,
                    source_message_id=event.message_id,
                    now_ms=int(deps.current_time().timestamp() * 1000),
                )
            except ReminderError as exc:
                return as_json({"error": f"提醒没有创建：{exc}"})
            return as_json(
                {
                    "status": "已创建待确认提醒，必须让主人回复“确认”才会生效",
                    "detail": format_job(job),
                }
            )

        registry.register(
            AgentTool(
                name="create_reminder",
                description="为主人创建一个提醒（创建后需要主人回复“确认”才生效）。",
                parameters={
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "提醒内容"},
                        "due_time": {
                            "type": "string",
                            "description": "北京时间，格式 YYYY-MM-DD HH:MM",
                        },
                        "minutes_from_now": {
                            "type": "number",
                            "description": "多少分钟后提醒，与 due_time 二选一",
                        },
                    },
                    "required": ["content"],
                },
                handler=create_reminder,
                audience="owner",
                surfaces=frozenset({"private", "group"}),
            )
        )

    if deps.group_timeline is not None:
        timeline = deps.group_timeline

        async def search_group_history(args: Mapping[str, Any], ctx: ToolContext) -> str:
            keyword = text_arg(args, "keyword", limit=40)
            event = ctx.event
            if not event.group_id:
                raise ToolInputError("只能在群聊中使用")
            entries = await asyncio.to_thread(
                timeline.recent,
                channel=event.channel,
                account_id=event.account_id,
                group_id=event.group_id,
                until_ms=event.occurred_at_ms + 999,
                limit=200,
                max_age_ms=7 * 86_400_000,
            )
            hits = [entry for entry in entries if keyword.casefold() in entry.text.casefold()]
            lines = []
            for entry in hits[-12:]:
                when = datetime.fromtimestamp(entry.occurred_at_ms / 1000, SHANGHAI)
                label = speaker_label(
                    account_id=entry.account_id,
                    group_id=entry.group_id,
                    sender_id=entry.sender_id,
                    sender_name=entry.sender_name,
                    is_self=entry.is_self,
                    owner_ids=deps.owner_ids,
                )
                lines.append(f"[{when:%m-%d %H:%M}] {label}: {entry.text[:150]}")
            return as_json({"matches": lines} if lines else {"matches": [], "note": "没找到"})

        registry.register(
            AgentTool(
                name="search_group_history",
                description="在本群最近 7 天的聊天记录里按关键词查找（例如有人问“之前谁说过…”）。",
                parameters={
                    "type": "object",
                    "properties": {"keyword": {"type": "string"}},
                    "required": ["keyword"],
                },
                handler=search_group_history,
                surfaces=frozenset({"group"}),
            )
        )

    if deps.web_search is not None:
        searcher = deps.web_search

        async def web_search(args: Mapping[str, Any], _ctx: ToolContext) -> str:
            query = text_arg(args, "query", limit=120)
            results = await searcher.search(query)
            return json.dumps({"results": results[:6]}, ensure_ascii=False)

        registry.register(
            AgentTool(
                name="web_search",
                description="联网搜索最新信息（新闻、天气、价格、事实核查等）。",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "搜索词"}},
                    "required": ["query"],
                },
                handler=web_search,
            )
        )

    if deps.web_reader is not None:
        reader = deps.web_reader

        async def read_url(args: Mapping[str, Any], _ctx: ToolContext) -> str:
            url = text_arg(args, "url", limit=2000)
            if not url.startswith(("http://", "https://")):
                raise ToolInputError("只支持 http/https 链接")
            page = await reader.read(url)
            return json.dumps(page, ensure_ascii=False)

        registry.register(
            AgentTool(
                name="read_url",
                description="读取一个公开网页的标题和正文（例如别人发来的链接）。",
                parameters={
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
                handler=read_url,
            )
        )
