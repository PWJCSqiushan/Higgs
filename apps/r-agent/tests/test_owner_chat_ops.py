from pathlib import Path

from r_agent.access import IngressPolicy
from r_agent.backup import BackupManager
from r_agent.identity import IdentityStore, Principal
from r_agent.ingest import IngestService
from r_agent.journal import Journal
from r_agent.memory import MemoryKind, MemoryScope, MemoryStatus, MemoryStore
from r_agent.operator_control import LiveOperatorControl
from r_agent.owner_commands import OwnerCommandContext, OwnerCommandRouter
from r_agent.phase2_reply import ReplyPolicy
from r_agent.vector_memory import MemoryVectorStore

OWNER_QQ = "800001"


def test_owner_can_operate_runtime_and_review_memory_from_chat(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("R_AGENT_MODEL_API_KEY=secret\n", encoding="utf-8")
    service = IngestService(
        policy=IngressPolicy(True, OWNER_QQ, frozenset(), frozenset()),
        identities=IdentityStore(tmp_path / "identity.sqlite", owner_qq=OWNER_QQ),
        journal=Journal(tmp_path / "journal.sqlite"),
    )
    service.initialize()
    reply = ReplyPolicy(
        mode="live",
        private_users=frozenset({OWNER_QQ}),
        groups=frozenset(),
        require_mention=True,
        max_per_minute=6,
        owner_qq=OWNER_QQ,
    )
    control = LiveOperatorControl(
        env_path=env_path,
        owner_qq=OWNER_QQ,
        service=service,
        reply_policy=reply,
        debounce_seconds=2.5,
    )
    memory = MemoryStore(tmp_path / "memory.sqlite")
    memory.initialize()
    vectors = MemoryVectorStore(memory.path, memory=memory)
    backup = BackupManager(
        data_dir=tmp_path,
        backup_dir=tmp_path / "backups",
        interval_minutes=15,
        retention=3,
        config_snapshot=lambda: {"enabled": control.snapshot().enabled},
    )
    control.attach_backup(backup.create)
    router = OwnerCommandRouter(
        context=OwnerCommandContext("live", 0, 0, 0, True, True, True),
        vectors=vectors,
        control=control,
        memory=memory,
        backup=backup,
    )
    owner = Principal("owner-principal", "owner")
    user = Principal("user-principal", "user")

    assert "仅允许" in (router.handle("/higgs disable", actor=user) or "")
    assert "暂停" in (router.handle("/higgs disable", actor=owner) or "")
    assert control.snapshot().enabled is False
    assert "恢复" in (router.handle("/higgs enable", actor=owner) or "")
    assert "1个" in (router.handle("/higgs whitelist group add 700001", actor=owner) or "")
    assert "希格斯" in (router.handle("/higgs keyword add 希格斯", actor=owner) or "")
    assert "单会话4" in (router.handle("/higgs rate 4 12", actor=owner) or "")

    item = memory.propose(
        scope=MemoryScope.PRINCIPAL,
        scope_id="someone",
        kind=MemoryKind.PREFERENCE,
        text="喜欢清晨跑步",
        source_channel="qq",
        source_account_id="900001",
        source_message_id="1",
        source_principal_id="someone",
        created_by="test",
    )
    response = router.handle(
        f"/higgs memory activate {item.item_id} 主人核实",
        actor=owner,
    )
    assert "active" in (response or "")
    assert memory.get(item.item_id).status is MemoryStatus.ACTIVE
    assert backup.status()["count"] >= 1
    assert "备份完成" in (router.handle("/higgs backup now", actor=owner) or "")
