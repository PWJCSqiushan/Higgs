from pathlib import Path

from r_agent.access import IngressPolicy
from r_agent.group_debounce import GroupMessageDebouncer
from r_agent.identity import IdentityStore
from r_agent.ingest import IngestService
from r_agent.journal import Journal
from r_agent.operator_control import LiveOperatorControl
from r_agent.phase2_reply import ReplyPolicy

OWNER_QQ = "800001"


def build_control(tmp_path: Path) -> tuple[LiveOperatorControl, ReplyPolicy, IngestService, Path]:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "R_AGENT_MODEL_API_KEY=must-stay-secret\n"
        "R_AGENT_ALLOWED_GROUPS=\n"
        "R_AGENT_REPLY_ALLOWED_GROUPS=\n",
        encoding="utf-8",
    )
    service = IngestService(
        policy=IngressPolicy(
            enabled=True,
            owner_qq=OWNER_QQ,
            allowed_private_qqs=frozenset(),
            allowed_groups=frozenset(),
        ),
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
    return control, reply, service, env_path


async def test_hot_controls_persist_without_overwriting_secrets(tmp_path: Path) -> None:
    control, reply, service, env_path = build_control(tmp_path)

    async def unused_handler(*args: object) -> None:
        return None

    debouncer = GroupMessageDebouncer(
        quiet_seconds=2.5,
        private_quiet_seconds=1.25,
        handler=unused_handler,
    )
    control.attach_debouncer(debouncer)
    assert control.debounce_seconds_for(private=False) == 2.5
    assert control.debounce_seconds_for(private=True) == 1.25
    control.change_private("add", "800002")
    control.change_group("add", "700001")
    control.change_natural_group("add", "700001")
    control.change_keyword("add", "希格斯")
    control.set_rates("4", "12")
    control.set_debounce("3.5")
    control.set_enabled(False)

    snapshot = control.snapshot()
    assert snapshot.enabled is False
    assert snapshot.private_users == ("800002",)
    assert snapshot.groups == ("700001",)
    assert snapshot.natural_groups == ("700001",)
    assert snapshot.trigger_terms == ("higgs", "希格斯")
    assert snapshot.conversation_max_per_minute == 4
    assert snapshot.global_max_per_minute == 12
    assert snapshot.debounce_seconds == 3.5
    assert debouncer.quiet_seconds == 3.5
    assert debouncer.private_quiet_seconds == 3.5
    assert control.debounce_seconds_for(private=False) == 3.5
    assert control.debounce_seconds_for(private=True) == 3.5
    assert service.policy.allowed_groups == frozenset({"700001"})
    assert reply.groups == frozenset({"700001"})

    saved = env_path.read_text(encoding="utf-8")
    assert "R_AGENT_MODEL_API_KEY=must-stay-secret" in saved
    assert "R_AGENT_REPLY_NATURAL_TRIGGER_TERMS=higgs,希格斯" in saved
    assert "R_AGENT_RUNTIME_ENABLED=false" in saved
    trashed_versions = list((tmp_path / ".trash").iterdir())
    assert trashed_versions
    assert any(
        "R_AGENT_MODEL_API_KEY=must-stay-secret" in item.read_text(encoding="utf-8")
        for item in trashed_versions
    )
