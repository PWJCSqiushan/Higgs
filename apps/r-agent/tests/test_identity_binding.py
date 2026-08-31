from __future__ import annotations

from pathlib import Path

import pytest

from r_agent.events import ConversationKind, InboundEvent
from r_agent.identity import IdentityBindingError, IdentityStore


def _official_event(*, account_id: str, sender_id: str) -> InboundEvent:
    return InboundEvent(
        channel="qq_official",
        account_id=account_id,
        sender_id=sender_id,
        message_id=f"message-{account_id}-{sender_id}",
        occurred_at_ms=1_767_225_600_000,
        conversation_kind=ConversationKind.PRIVATE,
        conversation_id=f"qq_official:private:{account_id}:{sender_id}",
        group_id=None,
        text="test",
        mentioned=False,
    )


def test_explicit_official_owner_binding_reuses_owner_principal(tmp_path: Path) -> None:
    store = IdentityStore(
        tmp_path / "identity.sqlite",
        owner_qq="10001",
        owner_identities=(("qq_official", "owner-openid"),),
    )
    store.initialize()

    napcat_owner = store.resolve("qq", "10001")
    official_owner = store.resolve("qq_official", "owner-openid")
    regular_user = store.resolve("qq_official", "someone-else")

    assert napcat_owner.principal_id == official_owner.principal_id
    assert official_owner.role == "owner"
    assert regular_user.principal_id != official_owner.principal_id
    assert regular_user.role == "user"


def test_explicit_binding_refuses_to_overwrite_existing_user(tmp_path: Path) -> None:
    path = tmp_path / "identity.sqlite"
    store = IdentityStore(path, owner_qq="10001")
    store.initialize()
    existing = store.resolve("qq_official", "owner-openid")

    rebound = IdentityStore(
        path,
        owner_qq="10001",
        owner_identities=(("qq_official", "owner-openid"),),
    )
    with pytest.raises(IdentityBindingError, match="another principal"):
        rebound.initialize()

    assert store.resolve("qq_official", "owner-openid").principal_id == existing.principal_id


def test_official_group_members_remain_principal_isolated_across_channels(
    tmp_path: Path,
) -> None:
    store = IdentityStore(
        tmp_path / "identity.sqlite",
        owner_qq="10001",
        owner_identities=(("qq_official", "owner-openid"),),
    )
    store.initialize()

    owner = store.resolve("qq_official", "owner-openid")
    member_a = store.resolve("qq_official", "member-openid-a")
    member_b = store.resolve("qq_official", "member-openid-b")
    same_text_on_onebot = store.resolve("qq", "member-openid-a")

    assert owner.role == "owner"
    assert member_a.role == "user"
    assert member_b.role == "user"
    assert (
        len(
            {
                owner.principal_id,
                member_a.principal_id,
                member_b.principal_id,
                same_text_on_onebot.principal_id,
            }
        )
        == 4
    )
    assert store.resolve("qq_official", "member-openid-a").principal_id == member_a.principal_id


def test_official_identity_is_isolated_by_bot_account(tmp_path: Path) -> None:
    store = IdentityStore(tmp_path / "identity.sqlite", owner_qq="10001")
    store.initialize()

    first = store.resolve_event(_official_event(account_id="bot-a", sender_id="same-openid"))
    repeated = store.resolve_event(_official_event(account_id="bot-a", sender_id="same-openid"))
    second_bot = store.resolve_event(_official_event(account_id="bot-b", sender_id="same-openid"))

    assert first.principal_id == repeated.principal_id
    assert second_bot.principal_id != first.principal_id
    assert first.role == second_bot.role == "user"
    assert (
        store.principal_id_for("qq_official", "same-openid", account_id="bot-a")
        == first.principal_id
    )
    assert store.delete_external_identity("qq_official", "same-openid", account_id="bot-b")
    assert store.principal_id_for("qq_official", "same-openid", account_id="bot-b") is None


def test_configured_owner_migrates_to_one_authenticated_bot_without_changing_principal(
    tmp_path: Path,
) -> None:
    path = tmp_path / "identity.sqlite"
    store = IdentityStore(
        path,
        owner_qq="10001",
        owner_identities=(("qq_official", "owner-openid"),),
    )
    store.initialize()
    legacy_owner = store.resolve("qq_official", "owner-openid")

    scoped_owner = store.resolve_event(
        _official_event(account_id="bot-a", sender_id="owner-openid")
    )
    assert scoped_owner == legacy_owner

    reopened = IdentityStore(
        path,
        owner_qq="10001",
        owner_identities=(("qq_official", "owner-openid"),),
    )
    reopened.initialize()
    assert (
        reopened.resolve_event(_official_event(account_id="bot-a", sender_id="owner-openid"))
        == legacy_owner
    )
    with pytest.raises(IdentityBindingError, match="another Bot account"):
        reopened.resolve_event(_official_event(account_id="bot-b", sender_id="owner-openid"))


def test_legacy_ordinary_official_identity_is_not_guessed_into_bot_scope(
    tmp_path: Path,
) -> None:
    store = IdentityStore(tmp_path / "identity.sqlite", owner_qq="10001")
    store.initialize()
    legacy = store.resolve("qq_official", "ordinary-openid")

    scoped = store.resolve_event(_official_event(account_id="bot-a", sender_id="ordinary-openid"))

    assert scoped.principal_id != legacy.principal_id
    assert scoped.role == legacy.role == "user"
