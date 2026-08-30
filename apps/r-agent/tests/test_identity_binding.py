from __future__ import annotations

from pathlib import Path

import pytest

from r_agent.identity import IdentityBindingError, IdentityStore


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
