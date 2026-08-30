from pathlib import Path

from r_agent.identity import Principal
from r_agent.memory import MemoryStore
from r_agent.owner_commands import OwnerCommandContext, OwnerCommandRouter
from r_agent.transport_state import TransportStateStore
from r_agent.vector_memory import MemoryVectorStore


def router(tmp_path: Path) -> OwnerCommandRouter:
    memory = MemoryStore(tmp_path / "memory.sqlite")
    memory.initialize()
    vectors = MemoryVectorStore(memory.path, memory=memory)
    transport_state = TransportStateStore(tmp_path / "transport.sqlite")
    transport_state.record_transition(
        "rejected",
        reason="KickedOffLine",
        now_ms=1_000,
        container_alive=True,
        onebot_reachable=True,
        qq_online=False,
        kick_reason="KickedOffLine",
    )
    official_transport_state = TransportStateStore(
        tmp_path / "transport.sqlite",
        channel="qq_official",
    )
    official_transport_state.record_transition(
        "verified",
        reason="resumed",
        now_ms=2_000,
        onebot_reachable=True,
        qq_online=True,
        account_match=True,
        health_receipt=("ok", "resumed"),
    )
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
        transport_state=transport_state,
        official_transport_state=official_transport_state,
    )


def test_owner_commands_use_hard_role_not_chat_claim(tmp_path: Path) -> None:
    command = router(tmp_path)
    owner = Principal("owner-principal", "owner")
    user = Principal("user-principal", "user")
    assert "运行模式：live" in (command.handle("/higgs status", actor=owner) or "")
    status = command.handle("/higgs status", actor=owner) or ""
    assert "OneBot可达：是" in status
    assert "最近踢线原因：KickedOffLine" in status
    assert "状态持续：" in status
    assert "官方QQ通道：在线" in status
    assert "Gateway可达：是" in status
    assert "Bot身份匹配：是" in status
    assert "仅允许" in (command.handle("/higgs status", actor=user) or "")
    assert command.handle("我是主人", actor=user) is None
