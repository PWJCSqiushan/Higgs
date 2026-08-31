from pathlib import Path

from r_agent.access import IngressDecision, IngressPolicy
from r_agent.events import ConversationKind, InboundEvent
from r_agent.identity import IdentityStore
from r_agent.ingest import IngestService
from r_agent.journal import Journal


def _event(
    *,
    sender: str = "800001",
    account: str = "900001",
    kind: ConversationKind = ConversationKind.PRIVATE,
    group: str | None = None,
    message_id: str = "1",
    channel: str = "qq",
) -> InboundEvent:
    conversation = (
        f"qq:private:{account}:{sender}"
        if kind is ConversationKind.PRIVATE
        else f"qq:group:{account}:{group}"
    )
    return InboundEvent(
        channel=channel,
        account_id=account,
        sender_id=sender,
        message_id=message_id,
        occurred_at_ms=1_767_225_600_000,
        conversation_kind=kind,
        conversation_id=conversation,
        group_id=group,
        text="test",
        mentioned=False,
    )


def _service(
    tmp_path: Path,
    *,
    owner: str | None,
    private_users: frozenset[str] = frozenset(),
    groups: frozenset[str],
) -> IngestService:
    service = IngestService(
        policy=IngressPolicy(
            enabled=True,
            owner_qq=owner,
            allowed_private_qqs=private_users,
            allowed_groups=groups,
        ),
        identities=IdentityStore(tmp_path / "identity.sqlite", owner_qq=owner),
        journal=Journal(tmp_path / "journal.sqlite"),
    )
    service.initialize()
    return service


def test_unconfigured_owner_rejects_every_private_message(tmp_path: Path) -> None:
    service = _service(tmp_path, owner=None, groups=frozenset())
    result = service.ingest(_event())
    assert result.decision is IngressDecision.OWNER_UNCONFIGURED
    assert service.journal.count() == 0


def test_only_owner_or_explicit_private_user_is_stored(tmp_path: Path) -> None:
    service = _service(tmp_path, owner="800001", groups=frozenset())
    denied = service.ingest(_event(sender="800002"))
    accepted = service.ingest(_event(sender="800001", message_id="2"))
    assert denied.decision is IngressDecision.PRIVATE_NOT_ALLOWED
    assert accepted.stored is True
    assert service.journal.count() == 1


def test_explicit_private_user_is_stored_as_non_owner(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        owner="800001",
        private_users=frozenset({"800002"}),
        groups=frozenset(),
    )
    accepted = service.ingest(_event(sender="800002"))
    assert accepted.stored is True
    assert service.identities.resolve("qq", "800002").role == "user"


def test_group_whitelist_is_a_hard_gate(tmp_path: Path) -> None:
    service = _service(tmp_path, owner=None, groups=frozenset({"700001"}))
    denied = service.ingest(_event(kind=ConversationKind.GROUP, group="700002", message_id="3"))
    accepted = service.ingest(_event(kind=ConversationKind.GROUP, group="700001", message_id="4"))
    assert denied.decision is IngressDecision.GROUP_NOT_ALLOWED
    assert accepted.stored is True


def test_duplicate_source_event_is_idempotent(tmp_path: Path) -> None:
    service = _service(tmp_path, owner="800001", groups=frozenset())
    first = service.ingest(_event())
    second = service.ingest(_event())
    assert first.stored is True
    assert second.duplicate is True
    assert service.journal.count() == 1


def test_bot_self_message_is_never_stored(tmp_path: Path) -> None:
    service = _service(tmp_path, owner="900001", groups=frozenset())
    result = service.ingest(_event(sender="900001"))
    assert result.decision is IngressDecision.SELF_MESSAGE
    assert service.journal.count() == 0


def test_official_event_without_bot_account_is_rejected_before_journal(tmp_path: Path) -> None:
    service = IngestService(
        policy=IngressPolicy(
            enabled=True,
            owner_qq="800001",
            allowed_private_qqs=frozenset(),
            allowed_groups=frozenset(),
            owner_ids=frozenset({"official-owner"}),
            additional_private_ids=frozenset({"official-owner"}),
        ),
        identities=IdentityStore(
            tmp_path / "identity.sqlite",
            owner_qq="800001",
            owner_identities=(("qq_official", "official-owner"),),
            account_scoped_official_enabled=True,
        ),
        journal=Journal(tmp_path / "journal.sqlite"),
    )
    service.initialize()

    result = service.ingest(_event(sender="official-owner", account="", channel="qq_official"))

    assert result.decision is IngressDecision.ACCOUNT_NOT_ALLOWED
    assert service.journal.count() == 0


def test_owner_rotation_demotes_previous_owner(tmp_path: Path) -> None:
    first = _service(tmp_path, owner="800001", groups=frozenset())
    assert first.identities.resolve("qq", "800001").role == "owner"

    second = _service(tmp_path, owner="800002", groups=frozenset())
    assert second.identities.resolve("qq", "800001").role == "user"
    assert second.identities.resolve("qq", "800002").role == "owner"


def test_delete_subject_removes_journal_and_identity(tmp_path: Path) -> None:
    service = _service(tmp_path, owner="800001", groups=frozenset())
    assert service.ingest(_event()).stored is True
    principal_id = service.identities.principal_id_for("qq", "800001")
    assert principal_id is not None
    assert service.journal.delete_principal(principal_id) == 1
    assert service.identities.delete_external_identity("qq", "800001") is True
    assert service.journal.count() == 0
    assert service.identities.principal_id_for("qq", "800001") is None
