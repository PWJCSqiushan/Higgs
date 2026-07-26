"""Deterministic owner-only QQ commands that never rely on model judgment."""

from __future__ import annotations

from dataclasses import dataclass

from r_agent.backup import BackupError, BackupManager
from r_agent.identity import Principal
from r_agent.memory import MemoryError, MemoryStatus, MemoryStore
from r_agent.operator_control import (
    ControlSnapshot,
    LiveOperatorControl,
    OperatorControlError,
)
from r_agent.vector_memory import MemoryVectorStore


@dataclass(frozen=True, slots=True)
class OwnerCommandContext:
    mode: str
    private_user_count: int
    group_count: int
    natural_group_count: int
    safety_enabled: bool
    passive_learning_enabled: bool
    embedding_enabled: bool


class OwnerCommandRouter:
    """Parse a deliberately small command language after hard owner resolution."""

    PREFIX = "/higgs"

    def __init__(
        self,
        *,
        context: OwnerCommandContext,
        vectors: MemoryVectorStore,
        control: LiveOperatorControl | None = None,
        memory: MemoryStore | None = None,
        backup: BackupManager | None = None,
    ) -> None:
        self.context = context
        self.vectors = vectors
        self.control = control
        self.memory = memory or vectors.memory
        self.backup = backup

    def handle(self, text: str, *, actor: Principal) -> str | None:
        clean = text.strip()
        if not clean.casefold().startswith(self.PREFIX):
            return None
        if actor.role != "owner":
            return "该命令仅允许系统配置确认的主人使用。"

        command_text = clean[len(self.PREFIX) :].strip()
        parts = command_text.split()
        command = parts[0].casefold() if parts else "help"
        arguments = parts[1:]
        try:
            if command in {"help", "帮助"}:
                return self._help()
            if command in {"status", "状态"}:
                return self._status()
            if command in {"enable", "启用"}:
                return self._set_enabled(True)
            if command in {"disable", "停用"}:
                return self._set_enabled(False)
            if command in {"whitelist", "白名单"}:
                return self._whitelist(arguments)
            if command in {"natural", "自然群"}:
                return self._natural_group(arguments)
            if command in {"keyword", "关键词"}:
                return self._keyword(arguments)
            if command in {"rate", "频率"}:
                return self._rate(arguments)
            if command in {"debounce", "合并"}:
                return self._debounce(arguments)
            if command in {"memory", "记忆"}:
                return self._memory(arguments, actor=actor)
            if command in {"backup", "备份"}:
                return self._backup(arguments)
        except (OperatorControlError, MemoryError) as exc:
            return f"操作未执行：{exc}"
        return "未知主人命令。发送 /higgs help 查看可用命令。"

    @staticmethod
    def _help() -> str:
        return (
            "Higgs主人命令：\n"
            "/higgs status\n"
            "/higgs enable | disable\n"
            "/higgs whitelist\n"
            "/higgs whitelist private add|remove QQ号\n"
            "/higgs whitelist group add|remove 群号\n"
            "/higgs natural add|remove 群号\n"
            "/higgs keyword add|remove 关键词\n"
            "/higgs rate 单会话每分钟 全局每分钟\n"
            "/higgs debounce 秒数\n"
            "/higgs memory list [candidate|quarantined|active|invalidated]\n"
            "/higgs memory show 记忆ID\n"
            "/higgs memory activate|quarantine|invalidate|restore 记忆ID [原因]\n"
            "/higgs backup [now]\n"
            "永久删除记忆仍需在本机CLI双重确认。"
        )

    def _snapshot(self) -> ControlSnapshot | None:
        return self.control.snapshot() if self.control is not None else None

    def _status(self) -> str:
        snapshot = self._snapshot()
        if snapshot is None:
            enabled = True
            private_count = self.context.private_user_count
            group_count = self.context.group_count
            natural_count = self.context.natural_group_count
            rate_line = ""
        else:
            enabled = snapshot.enabled
            private_count = len(snapshot.private_users)
            group_count = len(snapshot.groups)
            natural_count = len(snapshot.natural_groups)
            rate_line = (
                f"\n频率：{snapshot.conversation_max_per_minute}/会话/分钟，"
                f"{snapshot.global_max_per_minute}/全局/分钟"
                f"\n连续消息等待：{snapshot.debounce_seconds:g}秒"
            )
        return (
            f"普通回复：{'启用' if enabled else '暂停'}\n"
            f"运行模式：{self.context.mode}\n"
            f"获准好友：{private_count}\n"
            f"获准群：{group_count}\n"
            f"自然触发群：{natural_count}\n"
            f"发送安全：{self.context.safety_enabled}\n"
            f"被动学习：{self.context.passive_learning_enabled}\n"
            f"向量模块：{self.context.embedding_enabled}"
            f"{rate_line}"
        )

    def _require_control(self) -> LiveOperatorControl:
        if self.control is None:
            raise OperatorControlError("当前实例未启用聊天运维控制。")
        return self.control

    def _set_enabled(self, enabled: bool) -> str:
        snapshot = self._require_control().set_enabled(enabled)
        state = "恢复" if snapshot.enabled else "暂停"
        return f"已{state}普通回复。监听和主人命令保持在线。"

    def _whitelist(self, arguments: list[str]) -> str:
        control = self._require_control()
        if not arguments:
            snapshot = control.snapshot()
            return (
                f"私聊白名单：{self._join(snapshot.private_users)}\n"
                f"群白名单：{self._join(snapshot.groups)}\n"
                f"自然触发群：{self._join(snapshot.natural_groups)}"
            )
        if len(arguments) != 3:
            raise OperatorControlError("用法：/higgs whitelist private|group add|remove 数字ID")
        kind, action, value = (item.casefold() for item in arguments)
        if kind == "private":
            snapshot = control.change_private(action, value)
            return f"私聊白名单已更新，共{len(snapshot.private_users)}个。"
        if kind == "group":
            snapshot = control.change_group(action, value)
            return f"群白名单已更新，共{len(snapshot.groups)}个。"
        raise OperatorControlError("白名单类型必须是 private 或 group。")

    def _natural_group(self, arguments: list[str]) -> str:
        if not arguments:
            snapshot = self._require_control().snapshot()
            return f"自然触发群：{self._join(snapshot.natural_groups)}"
        if len(arguments) != 2:
            raise OperatorControlError("用法：/higgs natural add|remove 群号")
        snapshot = self._require_control().change_natural_group(
            arguments[0].casefold(),
            arguments[1],
        )
        return f"自然触发群已更新，共{len(snapshot.natural_groups)}个。"

    def _keyword(self, arguments: list[str]) -> str:
        control = self._require_control()
        if not arguments:
            return f"触发关键词：{self._join(control.snapshot().trigger_terms)}"
        if len(arguments) != 2:
            raise OperatorControlError("用法：/higgs keyword add|remove 关键词")
        snapshot = control.change_keyword(arguments[0].casefold(), arguments[1])
        return f"触发关键词：{self._join(snapshot.trigger_terms)}"

    def _rate(self, arguments: list[str]) -> str:
        control = self._require_control()
        if not arguments:
            snapshot = control.snapshot()
            return (
                f"单会话每分钟：{snapshot.conversation_max_per_minute}\n"
                f"全局每分钟：{snapshot.global_max_per_minute}"
            )
        if len(arguments) != 2:
            raise OperatorControlError("用法：/higgs rate 单会话每分钟 全局每分钟")
        snapshot = control.set_rates(arguments[0], arguments[1])
        return (
            f"频率已更新：单会话{snapshot.conversation_max_per_minute}/分钟，"
            f"全局{snapshot.global_max_per_minute}/分钟。"
        )

    def _debounce(self, arguments: list[str]) -> str:
        control = self._require_control()
        if not arguments:
            return f"连续消息等待：{control.snapshot().debounce_seconds:g}秒"
        if len(arguments) != 1:
            raise OperatorControlError("用法：/higgs debounce 秒数")
        snapshot = control.set_debounce(arguments[0])
        return f"连续消息等待已更新为{snapshot.debounce_seconds:g}秒。"

    def _memory(self, arguments: list[str], *, actor: Principal) -> str:
        if not arguments:
            status = self.vectors.status()
            return (
                f"记忆总数：{status['total']}\n"
                f"已有向量：{status['embedded']}\n"
                f"已激活向量：{status['active_embedded']}\n"
                "候选记忆需主人审核后才参与召回。"
            )
        action = arguments[0].casefold()
        if action == "list":
            try:
                status = MemoryStatus(arguments[1].casefold()) if len(arguments) > 1 else None
            except ValueError as exc:
                raise OperatorControlError("未知记忆状态。") from exc
            records = self.memory.list_items(actor=actor, status=status, limit=5)
            if not records:
                return "没有符合条件的记忆。"
            lines = [
                f"{item.item_id} | {item.status.value} | {self._short(item.text)}"
                for item in records
            ]
            return "最近记忆(最多5条)：\n" + "\n".join(lines)
        if action == "show":
            if len(arguments) != 2:
                raise OperatorControlError("用法：/higgs memory show 记忆ID")
            item = self.memory.get_for_review(arguments[1], actor=actor)
            return (
                f"ID：{item.item_id}\n"
                f"状态：{item.status.value}\n"
                f"风险：{item.risk.value}\n"
                f"置信度：{item.confidence:.2f}\n"
                f"内容：{item.text}"
            )
        transitions = {
            "activate": self.memory.activate,
            "quarantine": self.memory.quarantine,
            "invalidate": self.memory.invalidate,
            "restore": self.memory.restore,
        }
        if action in transitions:
            if len(arguments) < 2:
                raise OperatorControlError("/higgs memory 状态操作 需要记忆ID，可在后面附加原因。")
            reason = " ".join(arguments[2:]).strip() or "主人通过QQ命令审核"
            item = transitions[action](arguments[1], actor=actor, reason=reason)
            if self.backup is not None:
                try:
                    self.backup.create(f"memory-{action}")
                except BackupError:
                    return (
                        f"记忆 {item.item_id} 已变更为 {item.status.value}，"
                        "但变更后备份失败，请检查本机日志。"
                    )
            return f"记忆 {item.item_id} 已变更为 {item.status.value}。"
        raise OperatorControlError("未知记忆操作。发送 /higgs help 查看用法。")

    def _backup(self, arguments: list[str]) -> str:
        if self.backup is None:
            raise OperatorControlError("当前实例未启用自动备份。")
        if not arguments:
            status = self.backup.status()
            return (
                f"备份数量：{status['count']}\n"
                f"最近备份：{status['latest'] or '无'}\n"
                f"定时间隔：{status['interval_minutes']}分钟"
            )
        if arguments != ["now"]:
            raise OperatorControlError("用法：/higgs backup now")
        path = self.backup.create("owner-command")
        return f"备份完成：{path.name}"

    @staticmethod
    def _join(values: tuple[str, ...]) -> str:
        return "、".join(values) if values else "无"

    @staticmethod
    def _short(text: str, limit: int = 70) -> str:
        clean = " ".join(text.split())
        return clean if len(clean) <= limit else f"{clean[:limit]}…"
