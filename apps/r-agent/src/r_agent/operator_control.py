"""Owner-only hot configuration with atomic local persistence."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from r_agent.config import ConfigError
from r_agent.trash import move_to_trash

if TYPE_CHECKING:
    from r_agent.group_debounce import GroupMessageDebouncer
    from r_agent.ingest import IngestService
    from r_agent.phase2_reply import ReplyPolicy
    from r_agent.risk_ledger import RiskLedger

_log = logging.getLogger(__name__)


class OperatorControlError(ValueError):
    """A requested runtime change violated an operator invariant."""


@dataclass(frozen=True, slots=True)
class ControlSnapshot:
    enabled: bool
    private_users: tuple[str, ...]
    groups: tuple[str, ...]
    natural_groups: tuple[str, ...]
    trigger_terms: tuple[str, ...]
    conversation_max_per_minute: int
    global_max_per_minute: int
    debounce_seconds: float
    memory_auto_review_enabled: bool
    memory_auto_review_confidence: float
    memory_auto_review_evidence: int


class LiveOperatorControl:
    """Apply a validated change in memory and persist the same state to `.env`."""

    def __init__(
        self,
        *,
        env_path: Path,
        owner_qq: str,
        service: IngestService,
        reply_policy: ReplyPolicy,
        debounce_seconds: float,
        memory_auto_review_enabled: bool = False,
        memory_auto_review_confidence: float = 0.9,
        memory_auto_review_evidence: int = 2,
    ) -> None:
        resolved = env_path.expanduser().resolve()
        if not resolved.is_file():
            raise ConfigError("operator control requires an existing .env file")
        self.env_path = resolved
        self.owner_qq = owner_qq
        self.service = service
        self.reply_policy = reply_policy
        self._debounce_seconds = debounce_seconds
        self._memory_auto_review_enabled = memory_auto_review_enabled
        self._memory_auto_review_confidence = memory_auto_review_confidence
        self._memory_auto_review_evidence = memory_auto_review_evidence
        self._debouncer: GroupMessageDebouncer | None = None
        self._risk_ledger: RiskLedger | None = None
        self._on_change: Callable[[str], object] | None = None
        self._lock = threading.RLock()

    def attach_debouncer(self, debouncer: GroupMessageDebouncer) -> None:
        with self._lock:
            self._debouncer = debouncer
            debouncer.quiet_seconds = self._debounce_seconds

    def debounce_seconds_for(self, *, private: bool) -> float:
        """Return the live quiet-window used by both transport pipelines."""

        with self._lock:
            if self._debouncer is None:
                return self._debounce_seconds
            if private:
                return self._debouncer.private_quiet_seconds
            return self._debouncer.quiet_seconds

    def attach_risk_ledger(self, ledger: RiskLedger) -> None:
        with self._lock:
            self._risk_ledger = ledger

    def attach_backup(self, callback: Callable[[str], object]) -> None:
        with self._lock:
            self._on_change = callback

    @staticmethod
    def _qq(value: str) -> str:
        clean = value.strip()
        if not clean.isascii() or not clean.isdigit() or not 5 <= len(clean) <= 12:
            raise OperatorControlError("QQ号或群号必须是5至12位数字。")
        return clean

    @staticmethod
    def _term(value: str) -> str:
        clean = value.strip().casefold()
        if not clean or len(clean) > 32 or "\n" in clean or "\r" in clean:
            raise OperatorControlError("关键词必须是1至32个字符且不能换行。")
        return clean

    def _persist(self, updates: dict[str, str]) -> None:
        lines = self.env_path.read_text(encoding="utf-8").splitlines()
        remaining = dict(updates)
        rewritten: list[str] = []
        for line in lines:
            if "=" not in line or line.lstrip().startswith("#"):
                rewritten.append(line)
                continue
            key = line.split("=", 1)[0].strip()
            if key in remaining:
                rewritten.append(f"{key}={remaining.pop(key)}")
            else:
                rewritten.append(line)
        rewritten.extend(f"{key}={value}" for key, value in remaining.items())
        temporary = self.env_path.with_name(f"{self.env_path.name}.operator.tmp")
        previous: Path | None = None
        try:
            temporary.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
            previous = move_to_trash(self.env_path, trash_root=self.env_path.parent / ".trash")
            temporary.rename(self.env_path)
        except Exception:
            if not self.env_path.exists() and previous is not None and previous.exists():
                previous.rename(self.env_path)
            raise
        finally:
            move_to_trash(temporary, trash_root=self.env_path.parent / ".trash")
        if self._on_change is not None:
            try:
                self._on_change("operator-config-change")
            except Exception as exc:
                _log.warning("operator_change_backup_failed type=%s", type(exc).__name__)

    def snapshot(self) -> ControlSnapshot:
        with self._lock:
            return ControlSnapshot(
                enabled=self.reply_policy.runtime_enabled,
                private_users=tuple(
                    sorted(self.reply_policy.private_users.difference({self.owner_qq}))
                ),
                groups=tuple(sorted(self.reply_policy.groups)),
                natural_groups=tuple(sorted(self.reply_policy.natural_trigger_groups)),
                trigger_terms=tuple(sorted(self.reply_policy.natural_trigger_terms)),
                conversation_max_per_minute=self.reply_policy.max_per_minute,
                global_max_per_minute=self.reply_policy.global_max_per_minute,
                debounce_seconds=self._debounce_seconds,
                memory_auto_review_enabled=self._memory_auto_review_enabled,
                memory_auto_review_confidence=self._memory_auto_review_confidence,
                memory_auto_review_evidence=self._memory_auto_review_evidence,
            )

    def memory_auto_review_policy(self) -> tuple[bool, float, int]:
        with self._lock:
            return (
                self._memory_auto_review_enabled,
                self._memory_auto_review_confidence,
                self._memory_auto_review_evidence,
            )

    def set_memory_auto_review_enabled(self, enabled: bool) -> ControlSnapshot:
        with self._lock:
            self._memory_auto_review_enabled = enabled
            self._persist({"R_AGENT_MEMORY_AUTO_REVIEW_ENABLED": str(enabled).lower()})
            return self.snapshot()

    def set_memory_auto_review_confidence(self, value: str) -> ControlSnapshot:
        try:
            confidence = float(value)
        except ValueError as exc:
            raise OperatorControlError("自动审核置信度必须是数字。") from exc
        if not 0.8 <= confidence <= 0.99:
            raise OperatorControlError("自动审核置信度范围为0.80至0.99。")
        with self._lock:
            self._memory_auto_review_confidence = confidence
            self._persist({"R_AGENT_MEMORY_AUTO_REVIEW_CONFIDENCE": f"{confidence:.2f}"})
            return self.snapshot()

    def set_memory_auto_review_evidence(self, value: str) -> ControlSnapshot:
        try:
            evidence = int(value)
        except ValueError as exc:
            raise OperatorControlError("重复佐证次数必须是整数。") from exc
        if not 2 <= evidence <= 5:
            raise OperatorControlError("重复佐证次数范围为2至5。")
        with self._lock:
            self._memory_auto_review_evidence = evidence
            self._persist({"R_AGENT_MEMORY_AUTO_REVIEW_EVIDENCE": str(evidence)})
            return self.snapshot()

    def set_enabled(self, enabled: bool) -> ControlSnapshot:
        with self._lock:
            self.reply_policy.runtime_enabled = enabled
            self._persist({"R_AGENT_RUNTIME_ENABLED": str(enabled).lower()})
            return self.snapshot()

    def change_private(self, action: str, value: str) -> ControlSnapshot:
        qq = self._qq(value)
        if qq == self.owner_qq:
            raise OperatorControlError("主人无需加入普通私聊白名单，也不能在此移除。")
        with self._lock:
            values = set(self.reply_policy.private_users)
            values.discard(self.owner_qq)
            self._change_set(values, action, qq)
            ingress_values = frozenset(values)
            self.service.policy = replace(
                self.service.policy,
                allowed_private_qqs=ingress_values,
            )
            self.reply_policy.private_users = ingress_values.union({self.owner_qq})
            serialized = ",".join(sorted(values))
            self._persist(
                {
                    "R_AGENT_ALLOWED_PRIVATE_QQS": serialized,
                    "R_AGENT_REPLY_ALLOWED_PRIVATE_QQS": serialized,
                }
            )
            return self.snapshot()

    def change_group(self, action: str, value: str) -> ControlSnapshot:
        group = self._qq(value)
        with self._lock:
            groups = set(self.reply_policy.groups)
            self._change_set(groups, action, group)
            natural = set(self.reply_policy.natural_trigger_groups)
            if action == "remove":
                natural.discard(group)
            self.service.policy = replace(
                self.service.policy,
                allowed_groups=frozenset(groups),
            )
            self.reply_policy.groups = frozenset(groups)
            self.reply_policy.natural_trigger_groups = frozenset(natural)
            self._persist(
                {
                    "R_AGENT_ALLOWED_GROUPS": ",".join(sorted(groups)),
                    "R_AGENT_REPLY_ALLOWED_GROUPS": ",".join(sorted(groups)),
                    "R_AGENT_REPLY_NATURAL_TRIGGER_GROUPS": ",".join(sorted(natural)),
                }
            )
            return self.snapshot()

    def change_natural_group(self, action: str, value: str) -> ControlSnapshot:
        group = self._qq(value)
        with self._lock:
            if action == "add" and group not in self.reply_policy.groups:
                raise OperatorControlError("请先把该群加入群白名单。")
            natural = set(self.reply_policy.natural_trigger_groups)
            self._change_set(natural, action, group)
            self.reply_policy.natural_trigger_groups = frozenset(natural)
            self._persist(
                {
                    "R_AGENT_REPLY_NATURAL_TRIGGER_GROUPS": ",".join(sorted(natural)),
                }
            )
            return self.snapshot()

    def change_keyword(self, action: str, value: str) -> ControlSnapshot:
        term = self._term(value)
        with self._lock:
            terms = set(self.reply_policy.natural_trigger_terms)
            self._change_set(terms, action, term)
            if not terms:
                raise OperatorControlError("至少保留一个明确关键词。")
            if len(terms) > 16:
                raise OperatorControlError("关键词最多16个。")
            self.reply_policy.natural_trigger_terms = frozenset(terms)
            self._persist(
                {
                    "R_AGENT_REPLY_NATURAL_TRIGGER_TERMS": ",".join(sorted(terms)),
                }
            )
            return self.snapshot()

    def set_rates(self, conversation: str, global_value: str) -> ControlSnapshot:
        try:
            conversation_rate = int(conversation)
            global_rate = int(global_value)
        except ValueError as exc:
            raise OperatorControlError("频率必须是整数。") from exc
        if (
            not 1 <= conversation_rate <= 10
            or not 4 <= global_rate <= 60
            or conversation_rate > global_rate
        ):
            raise OperatorControlError("单会话频率范围1至10且不得超过全局频率; 全局频率范围4至60。")
        with self._lock:
            self.reply_policy.max_per_minute = conversation_rate
            self.reply_policy.global_max_per_minute = global_rate
            if self._risk_ledger is not None:
                self._risk_ledger.limits = replace(
                    self._risk_ledger.limits,
                    conversation_per_minute=conversation_rate,
                    global_per_minute=global_rate,
                )
            self._persist(
                {
                    "R_AGENT_REPLY_MAX_PER_MINUTE": str(conversation_rate),
                    "R_AGENT_REPLY_GLOBAL_MAX_PER_MINUTE": str(global_rate),
                }
            )
            return self.snapshot()

    def set_debounce(self, value: str) -> ControlSnapshot:
        try:
            seconds = float(value)
        except ValueError as exc:
            raise OperatorControlError("合并等待时间必须是数字。") from exc
        if not 0.5 <= seconds <= 10:
            raise OperatorControlError("合并等待时间范围为0.5至10秒。")
        with self._lock:
            self._debounce_seconds = seconds
            if self._debouncer is not None:
                self._debouncer.quiet_seconds = seconds
                self._debouncer.private_quiet_seconds = seconds
            self._persist(
                {
                    "R_AGENT_GROUP_DEBOUNCE_SECONDS": str(seconds),
                    "R_AGENT_PRIVATE_DEBOUNCE_SECONDS": str(seconds),
                }
            )
            return self.snapshot()

    @staticmethod
    def _change_set(values: set[str], action: str, item: str) -> None:
        if action == "add":
            values.add(item)
            return
        if action == "remove":
            values.discard(item)
            return
        raise OperatorControlError("操作必须是 add 或 remove。")
