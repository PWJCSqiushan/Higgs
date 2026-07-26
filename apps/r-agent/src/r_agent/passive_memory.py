"""Extract bounded, untrusted memory candidates from non-replied group chat."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from r_agent.embedding import EmbeddingClient, EmbeddingError
from r_agent.events import ConversationKind, InboundEvent
from r_agent.memory import (
    MemoryKind,
    MemoryRecord,
    MemoryRisk,
    MemoryScope,
    MemoryStore,
)
from r_agent.vector_memory import MemoryVectorStore

_log = logging.getLogger(__name__)

# Passive learning is intentionally narrow. A sentence must explicitly describe
# the speaker ("我…") before it can enter the owner-review queue.
_SELF_FACT = re.compile(
    r"(?:^|[\uFF0C\u3002\uFF01\uFF1F\s])我"
    r"(?:叫|是|喜欢|不喜欢|讨厌|偏好|想|准备|计划|需要|擅长|来自|住在|正在)"
    r".{1,180}"
)
_PREFERENCE = re.compile(
    r"(?:^|[\uFF0C\u3002\uFF01\uFF1F\s])我"
    r"(?:很|更|最|比较|一直|通常|平时)?(?:喜欢|不喜欢|讨厌|偏好).{1,120}"
)
_INJECTION_MARKERS = (
    "忽略之前",
    "系统提示词",
    "修改主人",
    "最高权限",
    "你必须记住",
    "记住我是",
    "叫我主人",
    "api key",
    "密钥",
    "token",
)
_SENSITIVE_MARKERS = (
    "密码",
    "验证码",
    "身份证",
    "银行卡",
    "家庭住址",
    "手机号",
    "邮箱密码",
    "主人",
    "管理员",
    "权限",
    "提示词",
)


@dataclass(frozen=True, slots=True)
class PassiveLearningResult:
    candidate: MemoryRecord | None
    embedded: bool = False
    auto_review_decision: str | None = None
    evidence_count: int = 0


class PassiveMemoryLearner:
    """Create candidates and optionally apply a narrow deterministic review gate."""

    def __init__(
        self,
        *,
        memory: MemoryStore,
        vectors: MemoryVectorStore,
        embedding_client: EmbeddingClient | None,
        auto_review_policy: Callable[[], tuple[bool, float, int]] | None = None,
        on_auto_review: Callable[[str], object] | None = None,
    ) -> None:
        self.memory = memory
        self.vectors = vectors
        self.embedding_client = embedding_client
        self.auto_review_policy = auto_review_policy
        self.on_auto_review = on_auto_review

    @staticmethod
    def _classification(text: str) -> tuple[MemoryKind, MemoryRisk, float]:
        lowered = text.casefold()
        if any(marker in lowered for marker in _INJECTION_MARKERS):
            return MemoryKind.EPISODE_SUMMARY, MemoryRisk.HIGH, 0.1
        if any(marker in lowered for marker in _SENSITIVE_MARKERS):
            return MemoryKind.EPISODE_SUMMARY, MemoryRisk.MEDIUM, 0.3
        if _PREFERENCE.search(text) is not None:
            # This score reflects extractor certainty, not truth. Automatic review
            # still requires a second matching self-report from the same principal.
            return MemoryKind.PREFERENCE, MemoryRisk.LOW, 0.9
        return MemoryKind.EPISODE_SUMMARY, MemoryRisk.MEDIUM, 0.35

    async def observe(
        self,
        event: InboundEvent,
        *,
        principal_id: str,
    ) -> PassiveLearningResult:
        if event.conversation_kind is not ConversationKind.GROUP:
            return PassiveLearningResult(None)
        clean = event.text.strip()
        if not 4 <= len(clean) <= 300 or _SELF_FACT.search(clean) is None:
            return PassiveLearningResult(None)

        kind, risk, confidence = self._classification(clean)
        candidate = await asyncio.to_thread(
            self.memory.propose,
            scope=MemoryScope.PRINCIPAL,
            scope_id=principal_id,
            kind=kind,
            text=clean,
            source_channel=event.channel,
            source_account_id=event.account_id,
            source_message_id=event.message_id,
            source_principal_id=principal_id,
            created_by="passive-observer-v2",
            risk=risk,
            confidence=confidence,
            now_ms=event.occurred_at_ms,
        )
        embedded = False
        if self.embedding_client is not None:
            try:
                vector = await self.embedding_client.embed_one(clean)
                await asyncio.to_thread(self.vectors.set, candidate.item_id, vector)
                embedded = True
            except EmbeddingError:
                pass

        if self.auto_review_policy is None:
            return PassiveLearningResult(candidate, embedded=embedded)
        enabled, threshold, evidence = self.auto_review_policy()
        if not enabled:
            return PassiveLearningResult(candidate, embedded=embedded)
        outcome = await asyncio.to_thread(
            self.memory.auto_review_candidate,
            candidate.item_id,
            min_confidence=threshold,
            min_evidence=evidence,
            now_ms=event.occurred_at_ms,
        )
        if outcome.decision in {"activated", "duplicate_invalidated"} and self.on_auto_review:
            try:
                await asyncio.to_thread(self.on_auto_review, f"memory-auto-{outcome.decision}")
            except Exception as exc:
                # A backup failure must not break QQ ingest.
                _log.warning("auto_review_backup_failed type=%s", type(exc).__name__)
        return PassiveLearningResult(
            outcome.record,
            embedded=embedded,
            auto_review_decision=outcome.decision,
            evidence_count=outcome.evidence_count,
        )