from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from r_agent.access import IngressPolicy
from r_agent.identity import IdentityStore, Principal
from r_agent.ingest import IngestService
from r_agent.journal import Journal
from r_agent.memory import MemoryKind, MemoryScope, MemoryStatus, MemoryStore
from r_agent.operator_control import LiveOperatorControl
from r_agent.owner_commands import OwnerCommandContext, OwnerCommandRouter
from r_agent.phase2_reply import ReplyPolicy
from r_agent.tool_governance import ToolGovernance, ToolRequest, ToolRequestSource
from r_agent.vector_memory import MemoryVectorStore

OWNER = Principal("owner-principal", "owner")


class CountingOwnerRouter(OwnerCommandRouter):
    def __init__(self, governance: ToolGovernance) -> None:
        self.mutation_calls: list[str] = []
        super().__init__(
            context=OwnerCommandContext(
                mode="live",
                private_user_count=0,
                group_count=0,
                natural_group_count=0,
                safety_enabled=True,
                passive_learning_enabled=False,
                embedding_enabled=True,
            ),
            vectors=SimpleNamespace(memory=object()),  # type: ignore[arg-type]
            tool_governance=governance,
        )

    def handle(self, text: str, *, actor: Principal, surface: str = "private") -> str | None:
        assert actor == OWNER
        assert surface == "private"
        self.mutation_calls.append(text)
        return f"completed:{text}"


class FailingOwnerRouter(CountingOwnerRouter):
    def handle(self, text: str, *, actor: Principal, surface: str = "private") -> str | None:
        self.mutation_calls.append(text)
        return "操作未执行：synthetic failure"


@pytest.mark.parametrize(
    ("command", "allowed"),
    (
        ("/higgs enable", True),
        ("/higgs keyword add higgs", True),
        ("/higgs rate 4 12", True),
        ("/higgs debounce 2.5", True),
        ("/higgs memory auto on", True),
        ("/higgs memory observations retry abcdef12", True),
        ("/higgs memory backfill apply", True),
        ("/higgs memory activate abcdef12 reviewed", True),
        ("/higgs memory self adopt abcdef12 reviewed", True),
        ("/higgs memory self why abcdef12", False),
        ("/higgs backup now", True),
        ("/higgs remind snooze abcdef12 10m", True),
        ("/higgs whitelist group add 700001", False),
        ("/higgs natural add 700001", False),
        ("/higgs backup", False),
    ),
)
def test_official_mutation_allowlist_is_explicit(command: str, allowed: bool) -> None:
    assert OwnerCommandRouter.is_governed_mutation(command) is allowed


@pytest.mark.asyncio
async def test_successful_owner_mutation_replay_reuses_persisted_receipt(tmp_path: Path) -> None:
    audit_path = tmp_path / "tool_audit.sqlite"
    router = CountingOwnerRouter(ToolGovernance(audit_path=audit_path))
    key = "a" * 64

    first = await router.handle_governed(
        "/higgs enable",
        actor=OWNER,
        surface="private",
        idempotency_key=key,
    )
    replay = await router.handle_governed(
        "/higgs enable",
        actor=OWNER,
        surface="private",
        idempotency_key=key,
    )

    assert replay == first == "普通回复状态已更新。"
    assert router.mutation_calls == ["/higgs enable"]
    with sqlite3.connect(audit_path) as connection:
        row = connection.execute(
            "SELECT actor_sha256,state,result_json FROM tool_idempotency WHERE idempotency_key=?",
            (key,),
        ).fetchone()
    assert row is not None and row[1] == "succeeded"
    assert OWNER.principal_id not in str(row)
    assert "/higgs enable" not in str(row)


@pytest.mark.asyncio
async def test_handler_failure_is_not_persisted_as_success(tmp_path: Path) -> None:
    audit_path = tmp_path / "tool_audit.sqlite"
    router = FailingOwnerRouter(ToolGovernance(audit_path=audit_path))
    reply = await router.handle_governed(
        "/higgs enable",
        actor=OWNER,
        surface="private",
        idempotency_key="f" * 64,
    )
    assert "未完成" in reply
    with sqlite3.connect(audit_path) as connection:
        state, result_json = connection.execute(
            "SELECT state,result_json FROM tool_idempotency WHERE idempotency_key=?",
            ("f" * 64,),
        ).fetchone()
    assert state == "failed"
    assert result_json is None


@pytest.mark.asyncio
async def test_persisted_result_does_not_repeat_mutation_parameters(tmp_path: Path) -> None:
    audit_path = tmp_path / "tool_audit.sqlite"
    router = CountingOwnerRouter(ToolGovernance(audit_path=audit_path))
    reply = await router.handle_governed(
        "/higgs keyword add private-trigger-phrase",
        actor=OWNER,
        surface="private",
        idempotency_key="0" * 64,
    )
    assert reply == "触发关键词已更新。"
    with sqlite3.connect(audit_path) as connection:
        stored = connection.execute(
            "SELECT result_json FROM tool_idempotency WHERE idempotency_key=?",
            ("0" * 64,),
        ).fetchone()[0]
    assert "private-trigger-phrase" not in stored


@pytest.mark.asyncio
async def test_owner_mutation_idempotency_conflict_is_denied(tmp_path: Path) -> None:
    router = CountingOwnerRouter(ToolGovernance(audit_path=tmp_path / "tool_audit.sqlite"))
    key = "b" * 64
    await router.handle_governed(
        "/higgs enable",
        actor=OWNER,
        surface="private",
        idempotency_key=key,
    )
    conflict = await router.handle_governed(
        "/higgs disable",
        actor=OWNER,
        surface="private",
        idempotency_key=key,
    )
    assert "冲突" in conflict
    assert router.mutation_calls == ["/higgs enable"]


@pytest.mark.asyncio
async def test_pre_execution_crash_claim_is_unknown_after_restart(tmp_path: Path) -> None:
    audit_path = tmp_path / "tool_audit.sqlite"
    governance = ToolGovernance(audit_path=audit_path)
    CountingOwnerRouter(governance)
    key = "c" * 64
    request = ToolRequest(
        tool_name=OwnerCommandRouter.GOVERNED_TOOL_NAME,
        parameters={
            "command": "/higgs enable",
            "actor_principal_id": OWNER.principal_id,
        },
        actor_role=OWNER.role,
        actor_id=OWNER.principal_id,
        source=ToolRequestSource.OWNER_COMMAND.value,
        surface="owner_command_private",
        idempotency_key=key,
        request_id=f"owner-{key}",
    )
    reservation = governance.audit.reserve(
        request,
        governance.registry.get(OwnerCommandRouter.GOVERNED_TOOL_NAME),
        now_ms=1_000,
    )
    assert reservation.kind == "new"

    restarted = CountingOwnerRouter(ToolGovernance(audit_path=audit_path))
    result = await restarted.handle_governed(
        "/higgs enable",
        actor=OWNER,
        surface="private",
        idempotency_key=key,
    )
    assert "结果未知" in result
    assert restarted.mutation_calls == []


@pytest.mark.asyncio
async def test_real_config_and_memory_mutations_execute_once_on_replay(tmp_path: Path) -> None:
    owner_qq = "800001"
    env_path = tmp_path / ".env"
    env_path.write_text("R_AGENT_RUNTIME_ENABLED=true\n", encoding="utf-8")
    service = IngestService(
        policy=IngressPolicy(True, owner_qq, frozenset(), frozenset()),
        identities=IdentityStore(tmp_path / "identity.sqlite", owner_qq=owner_qq),
        journal=Journal(tmp_path / "journal.sqlite"),
    )
    service.initialize()
    reply = ReplyPolicy(
        mode="live",
        private_users=frozenset({owner_qq}),
        groups=frozenset(),
        require_mention=True,
        max_per_minute=6,
        owner_qq=owner_qq,
    )
    control = LiveOperatorControl(
        env_path=env_path,
        owner_qq=owner_qq,
        service=service,
        reply_policy=reply,
        debounce_seconds=2.5,
    )
    memory = MemoryStore(tmp_path / "memory.sqlite")
    memory.initialize()
    router = OwnerCommandRouter(
        context=OwnerCommandContext("live", 0, 0, 0, True, False, True),
        vectors=MemoryVectorStore(memory.path, memory=memory),
        control=control,
        memory=memory,
        tool_governance=ToolGovernance(audit_path=tmp_path / "tool_audit.sqlite"),
    )

    first_disable = await router.handle_governed(
        "/higgs disable",
        actor=OWNER,
        surface="private",
        idempotency_key="d" * 64,
    )
    replay_disable = await router.handle_governed(
        "/higgs disable",
        actor=OWNER,
        surface="private",
        idempotency_key="d" * 64,
    )
    assert replay_disable == first_disable
    assert control.snapshot().enabled is False

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
    command = f"/higgs memory activate {item.item_id} reviewed"
    first_activation = await router.handle_governed(
        command,
        actor=OWNER,
        surface="private",
        idempotency_key="e" * 64,
    )
    replay_activation = await router.handle_governed(
        command,
        actor=OWNER,
        surface="private",
        idempotency_key="e" * 64,
    )
    assert replay_activation == first_activation
    assert memory.get(item.item_id).status is MemoryStatus.ACTIVE
    audits = memory.audit_log(item.item_id, actor=OWNER, limit=20)
    assert sum(entry.action == "active" for entry in audits) == 1
