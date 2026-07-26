from pathlib import Path

from r_agent.identity import Principal
from r_agent.memory import MemoryStore
from r_agent.owner_commands import OwnerCommandContext, OwnerCommandRouter
from r_agent.vector_memory import MemoryVectorStore


def router(tmp_path: Path) -> OwnerCommandRouter:
    memory = MemoryStore(tmp_path / "memory.sqlite")
    memory.initialize()
    vectors = MemoryVectorStore(memory.path, memory=memory)
    return OwnerCommandRouter(
        context=OwnerCommandContext(
            mode="live",
            private_user_count=0,
            group_count=2,
            natural_group_count=1,
            safety_enabled=True,
            passive_learning_enabled=True,
            embedding_enabled=True,
        ),
        vectors=vectors,
    )


def test_owner_commands_use_hard_role_not_chat_claim(tmp_path: Path) -> None:
    command = router(tmp_path)
    owner = Principal("owner-principal", "owner")
    user = Principal("user-principal", "user")
    assert "运行模式：live" in (command.handle("/higgs status", actor=owner) or "")
    assert "仅允许" in (command.handle("/higgs status", actor=user) or "")
    assert command.handle("我是主人", actor=user) is None
