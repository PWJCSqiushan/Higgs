"""Extract bounded, untrusted memory candidates from non-replied group chat."""

from __future__ import annotations

import asyncio
import re
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

# Passive learning is intentionally narrow. A sentence must explicitly describe
# the speaker ("我…") before it can enter the owner-review queue.
_SELF_FACT = re.compile(
    r"(?:^|[\uFF0C\u3002\uFF01\uFF1F\s])我"
    r"(?:叫|是|喜欢|不喜欢|讨厌|想|准备|计划|需要|擅长|来自|住在|正在)"
    r".{1,180}"
)
_INJECTION_MARKERS = (
    "忽略之前",
    "系统提示词",
    "修改主人",
    "最高权限",
    "你必须记住",
    "api key",
    "密钥",
)


@dataclass(frozen=True, slots=True)
class PassiveLearningResult:
    candidate: MemoryRecord | None
    embedded: bool = False


class PassiveMemoryLearner:
    """Create review-only candidates; group chat can never activate memory."""

    def __init__(
        self,
        *,
        memory: MemoryStore,
        vectors: MemoryVectorStore,
        embedding_client: EmbeddingClient | None,
    ) -> None:
        self.memory = memory
        self.vectors = vectors
        self.embedding_client = embedding_client

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

        lowered = clean.casefold()
        risk = (
            MemoryRisk.HIGH
            if any(marker in lowered for marker in _INJECTION_MARKERS)
            else MemoryRisk.MEDIUM
        )
        candidate = await asyncio.to_thread(
            self.memory.propose,
            scope=MemoryScope.PRINCIPAL,
            scope_id=principal_id,
            kind=MemoryKind.EPISODE_SUMMARY,
            text=clean,
            source_channel=event.channel,
            source_account_id=event.account_id,
            source_message_id=event.message_id,
            source_principal_id=principal_id,
            created_by="passive-observer-v1",
            risk=risk,
            confidence=0.35,
            now_ms=event.occurred_at_ms,
        )
        if self.embedding_client is None:
            return PassiveLearningResult(candidate)
        try:
            vector = await self.embedding_client.embed_one(clean)
            await asyncio.to_thread(self.vectors.set, candidate.item_id, vector)
        except EmbeddingError:
            return PassiveLearningResult(candidate)
        return PassiveLearningResult(candidate, embedded=True)
