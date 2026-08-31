from __future__ import annotations

import pytest

from r_agent.config import ConfigError
from r_agent.official_qq import OfficialQQAdapter, OfficialQQConfig
from r_agent.transport import TransportRegistry, TransportUnavailable


def test_official_qq_defaults_to_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "R_AGENT_OFFICIAL_QQ_ENABLED",
        "R_AGENT_OFFICIAL_QQ_APP_ID",
        "R_AGENT_OFFICIAL_QQ_CLIENT_SECRET",
        "R_AGENT_OFFICIAL_QQ_SANDBOX",
        "R_AGENT_OFFICIAL_QQ_OWNER_OPENID",
        "R_AGENT_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS",
        "R_AGENT_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS",
        "R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_VERSION",
        "R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FINGERPRINT",
        "R_AGENT_OFFICIAL_QQ_GROUP_ALLOWLIST_VERSION",
        "R_AGENT_OFFICIAL_QQ_GROUP_ALLOWLIST_FINGERPRINT",
        "R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED",
        "R_AGENT_OFFICIAL_QQ_GROUP_ENABLED",
        "R_AGENT_OFFICIAL_QQ_PRIVATE_RATE_PER_MINUTE",
        "R_AGENT_OFFICIAL_QQ_GROUP_RATE_PER_MINUTE",
        "R_AGENT_OFFICIAL_QQ_PRIVATE_CIRCUIT_FAILURE_LIMIT",
        "R_AGENT_OFFICIAL_QQ_GROUP_CIRCUIT_FAILURE_LIMIT",
        "R_AGENT_OFFICIAL_QQ_PRIVATE_CIRCUIT_COOLDOWN_SECONDS",
        "R_AGENT_OFFICIAL_QQ_GROUP_CIRCUIT_COOLDOWN_SECONDS",
        "R_AGENT_OFFICIAL_QQ_TRANSPORT",
        "R_AGENT_OFFICIAL_QQ_SIDECAR_SOCKET",
        "R_AGENT_OFFICIAL_QQ_REPLY_ENABLED",
        "R_AGENT_OFFICIAL_QQ_PROACTIVE_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)

    config = OfficialQQConfig.from_env()

    assert config.enabled is False
    assert config.app_id is None
    assert config.reply_enabled is False
    assert config.proactive_enabled is False
    assert config.ordinary_private_enabled is False
    assert config.group_enabled is False
    assert config.allowed_private_openids == frozenset()
    assert "CLIENT_SECRET" not in repr(config)


def test_owner_c2c_remains_available_without_new_ordinary_switches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_ENABLED", "true")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_TRANSPORT", "sidecar")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_REPLY_ENABLED", "true")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_OWNER_OPENID", "owner-openid")
    monkeypatch.delenv("R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED", raising=False)
    monkeypatch.delenv("R_AGENT_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS", raising=False)

    config = OfficialQQConfig.from_env()

    assert config.ordinary_private_enabled is False
    assert config.active_private_openids == frozenset({"owner-openid"})
    assert config.active_group_openids == frozenset()


def test_private_allowlist_is_normalized_and_owner_is_always_union_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_ENABLED", "true")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_TRANSPORT", "sidecar")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_OWNER_OPENID", "owner-openid")
    monkeypatch.setenv(
        "R_AGENT_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS",
        "member-openid, owner-openid, member-openid",
    )
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED", "true")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_VERSION", "1")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FINGERPRINT", "a" * 64)

    config = OfficialQQConfig.from_env()

    assert config.allowed_private_openids == frozenset({"owner-openid", "member-openid"})
    assert config.active_private_openids == config.allowed_private_openids


def test_ordinary_private_requires_versioned_allowlist_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_ENABLED", "true")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_TRANSPORT", "sidecar")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_OWNER_OPENID", "owner-openid")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED", "true")
    monkeypatch.delenv("R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_VERSION", raising=False)
    monkeypatch.delenv("R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FINGERPRINT", raising=False)

    with pytest.raises(ConfigError, match="versioned allowlist metadata"):
        OfficialQQConfig.from_env()

    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_VERSION", "1")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FINGERPRINT", "not-a-hash")
    with pytest.raises(ConfigError, match="lowercase SHA-256"):
        OfficialQQConfig.from_env()


def test_group_channel_requires_versioned_allowlist_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_ENABLED", "true")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_TRANSPORT", "sidecar")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_OWNER_OPENID", "owner-openid")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_GROUP_ENABLED", "true")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS", "group-openid")
    monkeypatch.delenv("R_AGENT_OFFICIAL_QQ_GROUP_ALLOWLIST_VERSION", raising=False)
    monkeypatch.delenv("R_AGENT_OFFICIAL_QQ_GROUP_ALLOWLIST_FINGERPRINT", raising=False)

    with pytest.raises(ConfigError, match="group channel requires versioned"):
        OfficialQQConfig.from_env()

    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_GROUP_ALLOWLIST_VERSION", "2")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_GROUP_ALLOWLIST_FINGERPRINT", "b" * 64)
    config = OfficialQQConfig.from_env()
    assert config.active_group_allowlist_version == 2
    assert config.active_group_allowlist_fingerprint == "b" * 64


@pytest.mark.parametrize(
    "name,value,match",
    [
        ("R_AGENT_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS", "*", "printable ASCII"),
        ("R_AGENT_OFFICIAL_QQ_PRIVATE_RATE_PER_MINUTE", "0", "between 1 and 120"),
        ("R_AGENT_OFFICIAL_QQ_GROUP_RATE_PER_MINUTE", "241", "between 1 and 240"),
    ],
)
def test_official_channel_policy_rejects_wildcards_and_out_of_range_limits(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    match: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ConfigError, match=match):
        OfficialQQConfig.from_env()


def test_official_switches_cannot_be_enabled_while_transport_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED", "true")

    with pytest.raises(ConfigError, match="enabled transport"):
        OfficialQQConfig.from_env()


def test_enabled_official_qq_requires_both_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_ENABLED", "true")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_APP_ID", "123456")
    monkeypatch.delenv("R_AGENT_OFFICIAL_QQ_CLIENT_SECRET", raising=False)

    with pytest.raises(ConfigError, match="AppID, ClientSecret"):
        OfficialQQConfig.from_env()


def test_sidecar_transport_requires_owner_but_forbids_agent_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_ENABLED", "true")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_TRANSPORT", "sidecar")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_OWNER_OPENID", "owner-openid")
    monkeypatch.delenv("R_AGENT_OFFICIAL_QQ_APP_ID", raising=False)
    monkeypatch.delenv("R_AGENT_OFFICIAL_QQ_CLIENT_SECRET", raising=False)

    config = OfficialQQConfig.from_env()
    assert config.transport == "sidecar"
    assert config.app_id is None
    assert config.client_secret is None

    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_APP_ID", "123456")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_CLIENT_SECRET", "a-secure-client-secret")
    with pytest.raises(ConfigError, match="forbids App credentials"):
        OfficialQQConfig.from_env()

    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_ENABLED", "false")
    with pytest.raises(ConfigError, match="forbids App credentials"):
        OfficialQQConfig.from_env()


def test_sidecar_socket_path_is_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_TRANSPORT", "sidecar")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_SIDECAR_SOCKET", "../sidecar.sock")

    with pytest.raises(ConfigError, match="absolute socket path"):
        OfficialQQConfig.from_env()


def test_official_reply_gate_cannot_enable_a_disabled_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_ENABLED", "false")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_REPLY_ENABLED", "true")

    with pytest.raises(ConfigError, match="replies require"):
        OfficialQQConfig.from_env()


def test_official_reply_gate_requires_durable_sidecar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_ENABLED", "true")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_REPLY_ENABLED", "true")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_TRANSPORT", "sdk")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_APP_ID", "123456")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_CLIENT_SECRET", "a-secure-client-secret")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_OWNER_OPENID", "owner-openid")

    with pytest.raises(ConfigError, match="durable sidecar"):
        OfficialQQConfig.from_env()

    with pytest.raises(ConfigError, match="durable sidecar"):
        OfficialQQConfig(
            enabled=True,
            app_id="123456",
            client_secret="a-secure-client-secret",
            owner_openid="owner-openid",
            reply_enabled=True,
        )


def test_official_proactive_gate_requires_enabled_passive_sidecar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_PROACTIVE_ENABLED", "true")
    with pytest.raises(ConfigError, match="passive replies"):
        OfficialQQConfig.from_env()

    config = OfficialQQConfig(
        enabled=True,
        app_id=None,
        client_secret=None,
        owner_openid="owner-openid",
        transport="sidecar",
        reply_enabled=True,
        proactive_enabled=True,
    )
    assert config.proactive_enabled is True


def test_direct_sidecar_config_keeps_credentials_and_missing_owner_out_of_agent() -> None:
    with pytest.raises(ConfigError, match="explicit owner"):
        OfficialQQConfig(
            enabled=True,
            app_id=None,
            client_secret=None,
            transport="sidecar",
        )

    with pytest.raises(ConfigError, match="forbids App credentials"):
        OfficialQQConfig(
            enabled=True,
            app_id="123456",
            client_secret=None,
            owner_openid="owner-openid",
            transport="sidecar",
        )


def test_official_qq_repr_never_contains_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "this-secret-must-not-leak"  # pragma: allowlist secret
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_ENABLED", "true")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_APP_ID", "123456")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_CLIENT_SECRET", secret)
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_OWNER_OPENID", "owner-openid")

    config = OfficialQQConfig.from_env()

    assert secret not in repr(config)


def test_disabled_official_config_has_no_active_policy_identities() -> None:
    config = OfficialQQConfig(
        enabled=False,
        app_id="123456",
        client_secret="a-secure-client-secret",  # pragma: allowlist secret
        owner_openid="owner-openid",
        allowed_group_openids=frozenset({"group-openid"}),
    )

    assert config.active_owner_openid is None
    assert config.active_group_openids == frozenset()


@pytest.mark.asyncio
async def test_adapter_is_not_connected_before_explicit_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_ENABLED", "true")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_APP_ID", "123456")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_CLIENT_SECRET", "a-secure-client-secret")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_OWNER_OPENID", "owner-openid")
    adapter = OfficialQQAdapter(OfficialQQConfig.from_env())

    status = await adapter.status()

    assert status.configured is True
    assert status.connected is False
    assert status.reason == "not_started"


def test_registry_rejects_unknown_and_duplicate_channels() -> None:
    registry = TransportRegistry()
    adapter = OfficialQQAdapter(OfficialQQConfig(False, None, None))
    registry.register(adapter)

    assert registry.channels() == ("qq_official",)
    with pytest.raises(ValueError, match="unique"):
        registry.register(adapter)
    with pytest.raises(TransportUnavailable, match="not registered"):
        registry.get("onebot")
