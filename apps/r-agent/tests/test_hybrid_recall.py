from pathlib import Path

import pytest

from r_agent.embedding import LocalHashEmbeddingClient
from r_agent.hybrid_recall import HybridMemorySearch
from r_agent.identity import Principal
from r_agent.memory import MemoryKind, MemoryRisk, MemoryScope, MemoryStore
from r_agent.vector_memory import MemoryVectorStore

OWNER = Principal("owner", "owner")


@pytest.mark.asyncio
async def test_local_hash_embedding_is_deterministic_and_bounded() -> None:
    client = LocalHashEmbeddingClient(dimensions=256)
    first = await client.embed_one("我喜欢路跑和摄影")
    second = await client.embed_one("我喜欢路跑和摄影")
    assert first == second
    assert len(first) == 256
    assert any(first)


def test_hybrid_lexical_search_respects_active_scope(tmp_path: Path) -> None:
    path = tmp_path / "memory.sqlite"
    memory = MemoryStore(path)
    memory.initialize()
    candidate = memory.propose(
        scope=MemoryScope.PRINCIPAL,
        scope_id="owner",
        kind=MemoryKind.PREFERENCE,
        text="主人偏好上午进行深度学习",
        source_channel="qq",
        source_account_id="bot",
        source_message_id="m1",
        source_principal_id="owner",
        created_by="test",
        risk=MemoryRisk.LOW,
        confidence=0.95,
    )
    memory.activate(candidate.item_id, actor=OWNER, reason="test")
    search = HybridMemorySearch(path, memory=memory, vectors=MemoryVectorStore(path, memory=memory))
    found = search.search(
        scope=MemoryScope.PRINCIPAL,
        scope_id="owner",
        query="深度学习",
        query_embedding=None,
        limit=4,
    )
    assert [item.item_id for item in found] == [candidate.item_id]
