from __future__ import annotations

from pathlib import Path

from r_agent.identity import Principal
from r_agent.memory import MemoryStore
from r_agent.memory_v2 import Observation
from r_agent.model_memory_candidates import (
    ModelCandidateExtractor,
    ModelCandidateShadowStore,
)
from r_agent.owner_commands import OwnerCommandContext, OwnerCommandRouter
from r_agent.vector_memory import MemoryVectorStore

OWNER = Principal("owner-principal", "owner")
USER = Principal("user-principal", "user")


class QueueModel:
    async def complete(self, *, system: str, user: str, max_tokens: int = 400) -> str:
        del system, user, max_tokens
        return (
            '{"version":"memory-candidate-v1","candidates":['
            '{"type":"preference","scope":"principal",'
            '"evidence_message_id":"message-queue", "confidence":0.95,'
            '"sensitive_level":"low",'
            '"normalized_content":"该用户偏好安静环境"}]}'
        )


def _observation() -> Observation:
    return Observation(
        observation_id="observation-queue",
        principal_id="owner-principal",
        principal_role="owner",
        channel="qq",
        account_id="bot",
        message_id="message-queue",
        conversation_kind="private",
        conversation_id="qq:private:bot:owner",
        text="我喜欢安静环境",
        occurred_at_ms=1_700_000_000_000,
    )


async def _router_with_queue(tmp_path: Path) -> OwnerCommandRouter:
    memory = MemoryStore(tmp_path / "memory.sqlite")
    memory.initialize()
    queue = ModelCandidateShadowStore(memory.path)
    queue.initialize()
    observation = _observation()
    await queue.extract_and_record(ModelCandidateExtractor(QueueModel()), observation)
    return OwnerCommandRouter(
        context=OwnerCommandContext("live", 0, 0, 0, True, True, True),
        vectors=MemoryVectorStore(memory.path, memory=memory),
        model_candidate_shadow_store=queue,
    )


async def test_owner_can_list_and_show_model_candidate_without_mutation(tmp_path: Path) -> None:
    router = await _router_with_queue(tmp_path)
    listing = router.handle("/higgs memory model list", actor=OWNER) or ""
    assert "模型候选队列" in listing
    assert "awaiting_owner_review" not in listing
    short_id = listing.split(" | ", 1)[0].splitlines()[-1]
    shown = router.handle(f"/higgs memory model show {short_id}", actor=OWNER) or ""
    assert "该用户偏好安静环境" in shown
    assert "shadow" in shown
    rejected = router.handle("/higgs memory model activate deadbeef", actor=OWNER) or ""
    assert "仅支持只读" in rejected


async def test_non_owner_cannot_read_model_candidate_queue(tmp_path: Path) -> None:
    router = await _router_with_queue(tmp_path)
    denied = router.handle("/higgs memory model list", actor=USER) or ""
    assert "仅允许" in denied
    assert "安静环境" not in denied
