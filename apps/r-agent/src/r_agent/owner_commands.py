"""Deterministic owner-only QQ commands that never rely on model judgment."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from r_agent.backup import BackupError, BackupManager
from r_agent.conversation_guard import ConversationCircuitBreaker
from r_agent.identity import Principal
from r_agent.memory import MemoryError, MemoryStatus, MemoryStore
from r_agent.memory_v2 import (
    MemoryObservationStore,
    backfill_candidates,
    backfill_preview,
)
from r_agent.model_memory_candidates import (
    CandidateDecision,
    ModelCandidateShadowStore,
    ModelCandidateStoreError,
)
from r_agent.operator_control import (
    ControlSnapshot,
    LiveOperatorControl,
    OperatorControlError,
)
from r_agent.persona_evolution import EvidenceKind, SelfMemoryService
from r_agent.recall import RecallLedger
from r_agent.reminders import ReminderError, ReminderStore, format_job
from r_agent.risk_ledger import RiskLedger
from r_agent.server_status import ServerStatusCommand
from r_agent.tool_governance import (
    ToolGovernance,
    ToolReceiptState,
    ToolRequest,
    ToolRequestSource,
    ToolSpec,
)
from r_agent.transport_state import TransportSnapshot, TransportStateStore
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
    GOVERNED_TOOL_NAME = "owner_command_mutation"

    def __init__(
        self,
        *,
        context: OwnerCommandContext,
        vectors: MemoryVectorStore,
        control: LiveOperatorControl | None = None,
        memory: MemoryStore | None = None,
        backup: BackupManager | None = None,
        observations: MemoryObservationStore | None = None,
        reminders: ReminderStore | None = None,
        journal_path: Path | None = None,
        conversation_guard: ConversationCircuitBreaker | None = None,
        risk_ledger: RiskLedger | None = None,
        recall_ledger: RecallLedger | None = None,
        transport_state: TransportStateStore | None = None,
        official_transport_state: TransportStateStore | None = None,
        server_status: ServerStatusCommand | None = None,
        model_candidate_shadow_store: ModelCandidateShadowStore | None = None,
        tool_governance: ToolGovernance | None = None,
        self_memory: SelfMemoryService | None = None,
    ) -> None:
        self.context = context
        self.vectors = vectors
        self.control = control
        self.memory = memory or vectors.memory
        self.backup = backup
        self.observations = observations
        self.reminders = reminders
        self.journal_path = journal_path
        self.conversation_guard = conversation_guard
        self.risk_ledger = risk_ledger
        self.recall_ledger = recall_ledger
        self.transport_state = transport_state
        self.official_transport_state = official_transport_state
        self.server_status = server_status
        self.model_candidate_shadow_store = model_candidate_shadow_store
        self.tool_governance = tool_governance
        self.self_memory = self_memory
        if self.tool_governance is not None:
            if self.tool_governance.registry.has(self.GOVERNED_TOOL_NAME):
                raise ValueError("owner command mutation tool is already registered")
            self.tool_governance.register(
                ToolSpec(
                    name=self.GOVERNED_TOOL_NAME,
                    description="Execute one explicit owner-private local mutation.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"},
                            "actor_principal_id": {"type": "string"},
                        },
                        "required": ["command", "actor_principal_id"],
                        "additionalProperties": False,
                    },
                    enabled=True,
                    requires_explicit_approval=True,
                    allow_model_execution=False,
                    timeout_seconds=120,
                    rate_limit_per_minute=6,
                    persist_result=True,
                ),
                self._execute_governed_mutation,
            )

    @staticmethod
    def is_governed_mutation(text: str) -> bool:
        """Allow only bounded, explicit owner-private mutations on official QQ."""

        parts = " ".join(text.strip().casefold().split()).split()
        if not parts or parts[0] != "/higgs":
            return False
        if parts in (["/higgs", "enable"], ["/higgs", "disable"]):
            return True
        if len(parts) == 4 and parts[1] == "keyword" and parts[2] in {"add", "remove"}:
            return True
        if len(parts) == 4 and parts[1] == "rate":
            return True
        if len(parts) == 3 and parts[1] == "debounce":
            return True
        if parts == ["/higgs", "backup", "now"]:
            return True
        if len(parts) >= 3 and parts[1] == "remind":
            action = parts[2]
            return (action in {"confirm", "ack", "cancel"} and len(parts) == 4) or (
                action == "snooze" and len(parts) == 5
            )
        if len(parts) < 3 or parts[1] != "memory":
            return False
        action = parts[2]
        if action == "auto":
            return (len(parts) == 4 and parts[3] in {"on", "off"}) or (
                len(parts) == 5 and parts[3] in {"threshold", "evidence"}
            )
        if action == "observations":
            return len(parts) == 5 and parts[3] == "retry"
        if action == "backfill":
            return parts == ["/higgs", "memory", "backfill", "apply"]
        if action == "self":
            return len(parts) >= 5 and parts[3] in {
                "adopt",
                "reject",
                "withdraw",
                "restore",
            }
        return action in {"activate", "quarantine", "invalidate", "restore"} and len(parts) >= 4

    @staticmethod
    def _governed_receipt_reply(command: str) -> str:
        """Return a durable result that never repeats command parameters or content."""

        parts = command.casefold().split()
        action = parts[1]
        if action in {"enable", "disable"}:
            return "普通回复状态已更新。"
        if action == "keyword":
            return "触发关键词已更新。"
        if action == "rate":
            return "频率限制已更新。"
        if action == "debounce":
            return "连续消息等待已更新。"
        if action == "backup":
            return "备份已完成。"
        if action == "remind":
            return {
                "confirm": "提醒已确认。",
                "ack": "提醒已完成。",
                "cancel": "提醒已取消。",
                "snooze": "提醒时间已更新。",
            }[parts[2]]
        memory_action = parts[2]
        if memory_action == "auto":
            return "记忆自动审核配置已更新。"
        if memory_action == "observations":
            return "记忆观察已重新排队。"
        if memory_action == "backfill":
            return "记忆候选回填已完成。"
        return "记忆状态已更新。"

    def _execute_governed_mutation(self, parameters: Mapping[str, object]) -> dict[str, str]:
        command = parameters.get("command")
        actor_id = parameters.get("actor_principal_id")
        if not isinstance(command, str) or not isinstance(actor_id, str) or not actor_id:
            raise OperatorControlError("主人变更命令参数无效")
        if not self.is_governed_mutation(command):
            raise OperatorControlError("该命令不属于已迁移的主人变更边界")
        reply = self.handle(command, actor=Principal(actor_id, "owner"), surface="private")
        if reply is None:
            raise OperatorControlError("主人变更命令未被处理")
        if reply.startswith("操作未执行：") or reply.startswith("未知主人命令"):
            raise OperatorControlError("主人变更命令未完成")
        return {"reply": self._governed_receipt_reply(command)}

    async def handle_governed(
        self,
        text: str,
        *,
        actor: Principal,
        surface: str,
        idempotency_key: str,
    ) -> str:
        if actor.role != "owner" or surface.strip().casefold() != "private":
            return "该变更命令仅允许系统配置确认的主人私聊使用。"
        if self.tool_governance is None:
            return "主人变更命令治理模块未启用。"
        command = " ".join(text.strip().split())
        if not self.is_governed_mutation(command):
            return "该主人变更命令尚未迁移到官方 QQ 安全边界。"
        request = ToolRequest(
            tool_name=self.GOVERNED_TOOL_NAME,
            parameters={
                "command": command,
                "actor_principal_id": actor.principal_id,
            },
            actor_role=actor.role,
            actor_id=actor.principal_id,
            source=ToolRequestSource.OWNER_COMMAND.value,
            surface="owner_command_private",
            idempotency_key=idempotency_key,
            request_id=f"owner-{idempotency_key}",
        )
        decision = self.tool_governance.decide(
            request,
            approved=True,
            approved_by=actor.principal_id,
        )
        receipt = await self.tool_governance.execute(request, decision=decision)
        if receipt.state in {ToolReceiptState.SUCCEEDED, ToolReceiptState.DUPLICATE}:
            if isinstance(receipt.result, dict) and isinstance(receipt.result.get("reply"), str):
                return str(receipt.result["reply"])
            return "该操作已有终态回执。为避免重复执行，请先查询当前状态。"
        if receipt.state in {ToolReceiptState.UNKNOWN, ToolReceiptState.TIMED_OUT}:
            return "操作结果未知，系统不会自动重试。请先查询当前状态。"
        if receipt.state is ToolReceiptState.RATE_LIMITED:
            return "主人变更操作过于频繁，本次未执行。"
        if receipt.state is ToolReceiptState.DENIED:
            return "主人变更操作未获执行许可，或幂等键与参数冲突。"
        return "主人变更操作未完成。请查询状态后再决定是否发起新请求。"

    def handle(self, text: str, *, actor: Principal, surface: str = "private") -> str | None:
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
            if command in {"server", "服务器"}:
                return self._server(arguments, actor=actor, surface=surface)
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
            if command == "remind":
                return self._remind(arguments)
            if command in {"risk", "风控"}:
                return self._risk(arguments)
            if command in {"backup", "备份"}:
                return self._backup(arguments)
        except (
            OperatorControlError,
            MemoryError,
            ModelCandidateStoreError,
            ReminderError,
        ) as exc:
            return f"操作未执行：{exc}"
        return "未知主人命令。发送 /higgs help 查看可用命令。"

    @staticmethod
    def _help() -> str:
        return (
            "Higgs主人命令：\n"
            "/higgs status\n"
            "/higgs server status\n"
            "/higgs enable | disable\n"
            "/higgs whitelist\n"
            "/higgs whitelist private add|remove QQ号\n"
            "/higgs whitelist group add|remove 群号\n"
            "/higgs natural add|remove 群号\n"
            "/higgs keyword add|remove 关键词\n"
            "/higgs rate 单会话每分钟 全局每分钟\n"
            "/higgs debounce 秒数\n"
            "/higgs memory list [candidate|quarantined|active|invalidated] [页码]\n"
            "/higgs memory show 记忆ID或短ID\n"
            "/higgs memory model list [shadow|quarantined|rejected] [页码]\n"
            "/higgs memory model show 候选ID或短ID\n"
            "/higgs memory audit 记忆ID或短ID\n"
            "/higgs memory auto [on|off|threshold 数值|evidence 次数]\n"
            "/higgs memory stats | observations [failed [limit]|retry ID]\n"
            "/higgs memory recall [limit] | source status\n"
            "/higgs memory backfill preview|apply\n"
            "/higgs memory self show|why 记忆ID\n"
            "/higgs memory self adopt|reject|withdraw|restore 记忆ID [原因]\n"
            "/higgs remind list|show|confirm|ack|cancel|snooze\n"
            "/higgs plan today|add|show|confirm|done|skip|replan|cancel|history\n"
            "/higgs memory activate|quarantine|invalidate|restore 记忆ID或短ID [原因]\n"
            "/higgs risk\n"
            "/higgs backup [now]\n"
            "永久删除记忆仍需在本机CLI双重确认。"
        )

    def _server(self, arguments: list[str], *, actor: Principal, surface: str) -> str:
        if len(arguments) != 1 or arguments[0].casefold() != "status":
            raise OperatorControlError("用法：/higgs server status")
        if surface.strip().casefold() != "private":
            raise OperatorControlError("服务器状态命令仅允许主人私聊。")
        if self.server_status is None:
            raise OperatorControlError("服务器状态工具未启用。")
        return self.server_status.handle(actor=actor)

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
            auto_review_line = "\n记忆自动审核：不可热配置"
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
            auto_review_line = (
                f"\n记忆自动审核：{'启用' if snapshot.memory_auto_review_enabled else '关闭'}"
                f"(置信度≥{snapshot.memory_auto_review_confidence:.2f}，"
                f"重复佐证≥{snapshot.memory_auto_review_evidence}次)"
            )
        status = (
            f"普通回复：{'启用' if enabled else '暂停'}\n"
            f"运行模式：{self.context.mode}\n"
            f"获准好友：{private_count}\n"
            f"获准群：{group_count}\n"
            f"自然触发群：{natural_count}\n"
            f"发送安全：{self.context.safety_enabled}\n"
            f"被动学习：{self.context.passive_learning_enabled}\n"
            f"向量模块：{self.context.embedding_enabled}"
            f"{rate_line}{auto_review_line}"
        )
        transport_status = self._transport_status()
        return f"{status}{transport_status}"

    def _transport_status(self) -> str:
        """Format anonymous persisted transport dimensions for the owner."""
        reports: list[str] = []
        if self.transport_state is not None:
            reports.append(self._format_transport_status(self.transport_state.snapshot()))
        if self.official_transport_state is not None:
            reports.append(
                self._format_transport_status(
                    self.official_transport_state.snapshot(),
                    official=True,
                )
            )
        return "".join(reports)

    @staticmethod
    def _format_transport_status(
        snapshot: TransportSnapshot,
        *,
        official: bool = False,
    ) -> str:
        """Format one channel without exposing account or platform identifiers."""

        def flag(value: bool | None) -> str:
            if value is None:
                return "未验证"
            return "是" if value else "否"

        def age(timestamp_ms: int | None) -> str:
            if timestamp_ms is None:
                return "无"
            seconds = max(0, int((time.time() * 1000 - timestamp_ms) / 1000))
            return f"{seconds}秒前"

        def timestamp(timestamp_ms: int) -> str:
            return datetime.fromtimestamp(timestamp_ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        state_name = {
            "verified": "在线",
            "rejected": "异常",
            "pending": "待确认",
        }.get(snapshot.state, "未知")
        action = snapshot.last_action_state
        action_name = {"ok": "正常", "failed": "失败", "unknown": "未知"}.get(action, "未知")
        duration_seconds = max(0, snapshot.duration_ms // 1000)
        if official:
            return (
                f"\n官方QQ通道：{state_name}\n"
                f"Gateway可达：{flag(snapshot.onebot_reachable)}\n"
                f"官方账号在线：{flag(snapshot.qq_online)}\n"
                f"Bot身份匹配：{flag(snapshot.account_match)}\n"
                f"最近状态回执：{action_name}({snapshot.last_action_reason or '无'}，"
                f"{age(snapshot.last_action_at_ms)})\n"
                f"最近健康回执：{snapshot.last_health_state}("
                f"{snapshot.last_health_reason or '无'}，{age(snapshot.last_health_at_ms)})\n"
                f"状态开始：{timestamp(snapshot.state_started_at_ms)}\n"
                f"故障持续：{snapshot.fault_duration_ms // 1000}秒\n"
                f"状态持续：{duration_seconds}秒\n"
                f"恢复结果：{snapshot.recovery_result or '无'}"
            )
        return (
            f"\nQQ通道：{state_name}\n"
            f"NapCat容器存活：{flag(snapshot.napcat_container_alive)}\n"
            f"OneBot可达：{flag(snapshot.onebot_reachable)}\n"
            f"QQ在线：{flag(snapshot.qq_online)}\n"
            f"账号匹配：{flag(snapshot.account_match)}\n"
            f"最近动作回执：{action_name}({snapshot.last_action_reason or '无'}，"
            f"{age(snapshot.last_action_at_ms)})\n"
            f"最近健康回执：{snapshot.last_health_state}("
            f"{snapshot.last_health_reason or '无'}，{age(snapshot.last_health_at_ms)})\n"
            f"最近踢线原因：{snapshot.kick_reason or '无'}\n"
            f"状态开始：{timestamp(snapshot.state_started_at_ms)}\n"
            f"故障持续：{snapshot.fault_duration_ms // 1000}秒\n"
            f"状态持续：{duration_seconds}秒\n"
            f"恢复结果：{snapshot.recovery_result or '无'}"
        )

    def _risk(self, arguments: list[str]) -> str:
        if arguments:
            raise OperatorControlError("用法：/higgs risk")
        if self.risk_ledger is None:
            raise OperatorControlError("风控台账未启用。")
        report = self.risk_ledger.stats()
        return (
            f"24小时发送={report['sent_24h']} 失败={report['failed_24h']} "
            f"限流={report['limited_24h']} "
            f"半小时峰值={report['peak_half_hour_24h']}\n"
            f"疑似机器人来源={report['suspected_robot_sources']} "
            f"24小时被踢={report['kicked_offline_24h']}"
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
            snapshot = self._snapshot()
            auto = (
                "不可热配置"
                if snapshot is None
                else (
                    f"{'启用' if snapshot.memory_auto_review_enabled else '关闭'}，"
                    f"置信度≥{snapshot.memory_auto_review_confidence:.2f}，"
                    f"重复佐证≥{snapshot.memory_auto_review_evidence}次"
                )
            )
            return (
                f"记忆总数：{status['total']}\n"
                f"已有向量：{status['embedded']}\n"
                f"已激活向量：{status['active_embedded']}\n"
                f"自动审核：{auto}\n"
                "发送 /higgs memory list candidate 1 查看待审核记忆。"
            )
        action = arguments[0].casefold()
        if action == "self":
            return self._self_memory(arguments[1:], actor=actor)
        if action == "stats":
            status = self.vectors.status()
            observation = self.observations.stats() if self.observations else {}
            counts = self.memory.status_counts(actor=actor)
            return (
                f"total={status['total']} candidate={counts['candidate']} "
                f"active={counts['active']} quarantined={counts['quarantined']} "
                f"invalidated={counts['invalidated']} vectors={status['embedded']}\n"
                f"observations_pending={observation.get('pending', 0)} "
                f"last_reconcile_ms={observation.get('last_reconcile_ms') or 'never'}"
            )
        if action == "observations":
            if self.observations is None:
                raise OperatorControlError("memory observation queue is disabled")
            if len(arguments) >= 2 and arguments[1].casefold() == "failed":
                if len(arguments) > 3:
                    raise OperatorControlError("usage: /higgs memory observations failed [limit]")
                try:
                    limit = int(arguments[2]) if len(arguments) == 3 else 10
                except ValueError as exc:
                    raise OperatorControlError("limit must be an integer") from exc
                if not 1 <= limit <= 50:
                    raise OperatorControlError("limit must be between 1 and 50")
                failed = self.observations.list_failed(limit=limit)
                if not failed:
                    return "failed_observations=0"
                lines = [
                    f"{str(item['observation_id'])[:8]} | {item['error_type']} | "
                    f"retries={item['retry_count']} | error={str(item['error_sha256'])[:8]}"
                    for item in failed
                ]
                return f"failed_observations={len(failed)}\n" + "\n".join(lines)
            if len(arguments) == 3 and arguments[1].casefold() == "retry":
                retried = self.observations.retry_failed(arguments[2])
                if not retried:
                    raise OperatorControlError("failed observation ID is missing or ambiguous")
                return f"observation {arguments[2][:8]} queued for retry"
            if len(arguments) != 1:
                raise OperatorControlError(
                    "usage: /higgs memory observations [failed [limit]|retry ID]"
                )
            stats = self.observations.stats()
            return (
                f"pending={stats['pending']} processed={stats['processed']} "
                f"excluded={stats['excluded']} failed={stats['failed']}"
            )
        if action == "recall":
            if self.recall_ledger is None:
                raise OperatorControlError("recall ledger is disabled")
            if len(arguments) > 2:
                raise OperatorControlError("usage: /higgs memory recall [limit]")
            try:
                limit = int(arguments[1]) if len(arguments) == 2 else 10
            except ValueError as exc:
                raise OperatorControlError("limit must be an integer") from exc
            if not 1 <= limit <= 50:
                raise OperatorControlError("limit must be between 1 and 50")
            entries = self.recall_ledger.list_recent(actor=actor, limit=limit)
            if not entries:
                return "recent_recalls=0"
            lines = [
                f"{entry.recall_id[:8]} | {entry.created_at_ms} | "
                f"items={','.join(item[:8] for item in entry.memory_item_ids) or '-'} | "
                f"query={entry.query_sha256[:8]}"
                for entry in entries
            ]
            return f"recent_recalls={len(entries)}\n" + "\n".join(lines)
        if action == "backfill" and arguments[1:] == ["preview"]:
            if self.journal_path is None:
                raise OperatorControlError("journal path is unavailable")
            report = backfill_preview(self.journal_path)
            return (
                "backfill preview only; no memory was written\n"
                f"total={report['total_messages']} eligible={report['eligible_messages']} "
                f"excluded_high_frequency={report['excluded_high_frequency']}"
            )
        if action == "backfill" and arguments[1:] == ["apply"]:
            if self.journal_path is None or self.observations is None:
                raise OperatorControlError("journal or observation queue is unavailable")
            report = backfill_candidates(self.journal_path, self.observations)
            return (
                "candidate-only backfill completed; nothing was auto-activated\n"
                f"total={report['total_messages']} eligible={report['eligible_messages']} "
                f"excluded_high_frequency={report['excluded_high_frequency']}\n"
                f"enqueued={report['enqueued']} "
                f"already_present={report['already_present']}"
            )
        if action == "source" and arguments[1:] == ["status"]:
            if self.conversation_guard is None:
                raise OperatorControlError("conversation circuit breaker is disabled")
            report = self.conversation_guard.source_status()
            base = (
                f"active_cooldowns={report['active_cooldowns']} "
                f"recent_non_owner_replies={report['recent_non_owner_replies']}"
            )
            if self.observations is None:
                return base
            quality = self.observations.source_quality()
            if not quality:
                return base + "\nobservation_sources=0"
            lines = [f"{item['source']}:{item['status']}={item['count']}" for item in quality[:20]]
            return base + "\nobservation_sources=" + " ".join(lines)
        if action in {"model", "model-candidate", "model_candidates", "candidates"}:
            return self._model_candidates(arguments[1:])
        if action == "list":
            status_filter = None
            page = 1
            remaining = arguments[1:]
            if remaining:
                try:
                    page = int(remaining[0])
                    remaining = remaining[1:]
                except ValueError:
                    try:
                        status_filter = MemoryStatus(remaining[0].casefold())
                    except ValueError as exc:
                        raise OperatorControlError("未知记忆状态。") from exc
                    remaining = remaining[1:]
                    if remaining:
                        try:
                            page = int(remaining[0])
                        except ValueError as exc:
                            raise OperatorControlError("页码必须是正整数。") from exc
                        remaining = remaining[1:]
            if remaining or not 1 <= page <= 999:
                raise OperatorControlError(
                    "用法：/higgs memory list [candidate|quarantined|active|invalidated] [页码]"
                )
            page_size = 8
            records = self.memory.list_items(
                actor=actor,
                status=status_filter,
                limit=page_size,
                offset=(page - 1) * page_size,
            )
            if not records:
                return f"第{page}页没有符合条件的记忆。"
            lines = [
                f"{item.item_id[:8]} | {item.status.value} | {self._short(item.text)}"
                for item in records
            ]
            return f"记忆列表 第{page}页(每页{page_size}条，短ID可直接用于命令)：\n" + "\n".join(
                lines
            )
        if action == "show":
            if len(arguments) != 2:
                raise OperatorControlError("用法：/higgs memory show 记忆ID或短ID")
            item = self.memory.get_for_review(arguments[1], actor=actor)
            return (
                f"ID：{item.item_id}\n"
                f"状态：{item.status.value}\n"
                f"类型：{item.kind.value}\n"
                f"作用域：{item.scope.value}\n"
                f"风险：{item.risk.value}\n"
                f"置信度：{item.confidence:.2f}\n"
                f"审核者：{item.reviewed_by or '未审核'}\n"
                f"内容：{item.text}"
            )
        if action == "audit":
            if len(arguments) != 2:
                raise OperatorControlError("用法：/higgs memory audit 记忆ID或短ID")
            item = self.memory.get_for_review(arguments[1], actor=actor)
            audits = self.memory.audit_log(item.item_id, actor=actor, limit=20)
            if not audits:
                return f"记忆 {item.item_id[:8]} 没有审计记录。"
            lines = [
                f"{entry.audit_id} | {entry.action} | {entry.actor_role} | {entry.created_at_ms}"
                for entry in audits
            ]
            return f"记忆 {item.item_id[:8]} 的审计历史：\n" + "\n".join(lines)
        if action == "auto":
            control = self._require_control()
            if len(arguments) == 1:
                snapshot = control.snapshot()
            elif len(arguments) == 2 and arguments[1].casefold() in {"on", "off"}:
                snapshot = control.set_memory_auto_review_enabled(arguments[1].casefold() == "on")
            elif len(arguments) == 3 and arguments[1].casefold() == "threshold":
                snapshot = control.set_memory_auto_review_confidence(arguments[2])
            elif len(arguments) == 3 and arguments[1].casefold() == "evidence":
                snapshot = control.set_memory_auto_review_evidence(arguments[2])
            else:
                raise OperatorControlError(
                    "用法：/higgs memory auto [on|off|threshold 0.80-0.99|evidence 2-5]"
                )
            return (
                f"记忆自动审核：{'启用' if snapshot.memory_auto_review_enabled else '关闭'}\n"
                f"最低置信度：{snapshot.memory_auto_review_confidence:.2f}\n"
                f"重复佐证：{snapshot.memory_auto_review_evidence}次\n"
                "仅低风险、本人自述、同一人重复表达的偏好可自动激活，其余仍需人工审核。"
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

    def _self_memory(self, arguments: list[str], *, actor: Principal) -> str:
        if self.self_memory is None:
            raise OperatorControlError("Higgs 自我记忆治理尚未启用。")
        if len(arguments) < 2:
            raise OperatorControlError(
                "用法：/higgs memory self show|why|adopt|reject|withdraw|restore 记忆ID [原因]"
            )
        action = arguments[0].casefold()
        item_id = arguments[1]
        if action in {"show", "why"}:
            if len(arguments) != 2:
                raise OperatorControlError("查看自我记忆时不能附加变更参数。")
            item = self.memory.get_for_review(item_id, actor=actor)
            report = self.self_memory.explain(item.item_id, actor=actor)
            evidence = self.self_memory.list_evidence(item.item_id)
            counts = {
                kind.value: sum(entry.evidence_kind is kind for entry in evidence)
                for kind in EvidenceKind
            }
            quote_proven = self.self_memory.context_original_quote(item.item_id) is not None
            return (
                f"ID：{item.item_id}\n"
                f"状态：{item.status.value}\n"
                f"类型：{item.kind.value}\n"
                f"观点：{item.text}\n"
                f"演进状态：{report['state']}\n"
                f"记住/改变原因：{report['reason'] or '无'}\n"
                f"证据：自我回复={counts['self_reply']} 支持={counts['support']} "
                f"反对={counts['opposition']} 原句已验证={'是' if quote_proven else '否'}"
            )
        transitions = {
            "adopt": self.self_memory.adopt,
            "reject": self.self_memory.reject,
            "withdraw": self.self_memory.withdraw,
            "restore": self.self_memory.restore,
        }
        if action not in transitions:
            raise OperatorControlError("未知自我记忆治理动作。")
        reason = " ".join(arguments[2:]).strip() or "主人通过 QQ 命令治理自我观点"
        item = transitions[action](item_id, actor=actor, reason=reason)
        if self.backup is not None:
            self.backup.create(f"self-memory-{action}")
        return f"自我记忆 {item.item_id[:8]} 已完成 {action}，状态为 {item.status.value}。"

    def _model_candidates(self, arguments: list[str]) -> str:
        """List/show the append-only model queue; there are no mutation branches."""
        if self.model_candidate_shadow_store is None:
            raise OperatorControlError("模型记忆候选队列未启用。")
        if not arguments:
            raise OperatorControlError(
                "用法：/higgs memory model list [shadow|quarantined|rejected] [页码]"
            )
        action = arguments[0].casefold()
        if action == "list":
            status: CandidateDecision | None = None
            page = 1
            remaining = arguments[1:]
            if remaining:
                try:
                    page = int(remaining[0])
                    remaining = remaining[1:]
                except ValueError:
                    try:
                        status = CandidateDecision(remaining[0].casefold())
                    except ValueError as exc:
                        raise OperatorControlError("未知模型候选状态。") from exc
                    remaining = remaining[1:]
                    if remaining:
                        try:
                            page = int(remaining[0])
                        except ValueError as exc:
                            raise OperatorControlError("页码必须是正整数。") from exc
                        remaining = remaining[1:]
            if remaining or not 1 <= page <= 999:
                raise OperatorControlError(
                    "用法：/higgs memory model list [shadow|quarantined|rejected] [页码]"
                )
            page_size = 8
            records = self.model_candidate_shadow_store.list_candidates(
                decision=status,
                limit=page_size,
                offset=(page - 1) * page_size,
            )
            if not records:
                return f"模型候选队列第{page}页没有记录。"
            lines = []
            for item in records:
                confidence = f"{item.confidence:.2f}" if item.confidence is not None else "-"
                detail = item.normalized_content or item.reason
                lines.append(
                    f"{item.proposal_id[:8]} | {item.decision.value} | "
                    f"{item.kind or '-'} | 置信度={confidence} | {self._short(detail)}"
                )
            return f"模型候选队列第{page}页(每页{page_size}条，短ID可直接用于show)：\n" + "\n".join(
                lines
            )
        if action == "show":
            if len(arguments) != 2:
                raise OperatorControlError("用法：/higgs memory model show 候选ID或短ID")
            item = self.model_candidate_shadow_store.get_for_review(arguments[1])
            confidence = f"{item.confidence:.2f}" if item.confidence is not None else "无"
            return (
                f"候选ID：{item.proposal_id}\n"
                f"决定：{item.decision.value}\n"
                f"原因：{item.reason}\n"
                f"类型：{item.kind or '无'}\n"
                f"作用域：{item.scope or '无'}\n"
                f"置信度：{confidence}\n"
                f"敏感等级：{item.sensitive_level.value if item.sensitive_level else '无'}\n"
                f"证据消息ID：{item.evidence_message_id}\n"
                f"内容：{item.normalized_content or '无'}"
            )
        raise OperatorControlError(
            "模型候选仅支持只读 list/show，不提供 activate、overwrite 或 delete。"
        )

    def _remind(self, arguments: list[str]) -> str:
        if self.reminders is None:
            raise OperatorControlError("reminder module is disabled")
        if not arguments or arguments == ["list"]:
            jobs = self.reminders.list(limit=10)
            if not jobs:
                return "No reminders."
            return "Recent reminders:\n" + "\n".join(
                f"{job.job_id[:8]} | {job.status} | {self._short(job.content, 35)}" for job in jobs
            )
        action = arguments[0].casefold()
        if action == "show" and len(arguments) == 2:
            return format_job(self.reminders.get(arguments[1]))
        if action == "confirm" and len(arguments) == 2:
            return format_job(self.reminders.confirm(arguments[1]))
        if action == "ack" and len(arguments) == 2:
            job = self.reminders.acknowledge(arguments[1])
            return f"Reminder {job.job_id[:8]} completed."
        if action == "cancel" and len(arguments) == 2:
            job = self.reminders.cancel(arguments[1])
            return f"Reminder {job.job_id[:8]} cancelled."
        if action == "snooze" and len(arguments) == 3:
            suffix = arguments[2].casefold()
            if not suffix.endswith("m") or not suffix[:-1].isdigit():
                raise OperatorControlError("snooze duration example: 10m")
            return format_job(self.reminders.snooze(arguments[1], int(suffix[:-1])))
        raise OperatorControlError("usage: /higgs remind list|show|confirm|ack|cancel|snooze")

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
