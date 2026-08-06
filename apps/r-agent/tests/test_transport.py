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
    ):
        monkeypatch.delenv(name, raising=False)

    config = OfficialQQConfig.from_env()

    assert config.enabled is False
    assert config.app_id is None
    assert "CLIENT_SECRET" not in repr(config)


def test_enabled_official_qq_requires_both_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_ENABLED", "true")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_APP_ID", "123456")
    monkeypatch.delenv("R_AGENT_OFFICIAL_QQ_CLIENT_SECRET", raising=False)

    with pytest.raises(ConfigError, match="AppID and ClientSecret"):
        OfficialQQConfig.from_env()


def test_official_qq_repr_never_contains_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "this-secret-must-not-leak"
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_ENABLED", "true")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_APP_ID", "123456")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_CLIENT_SECRET", secret)

    config = OfficialQQConfig.from_env()

    assert secret not in repr(config)


@pytest.mark.asyncio
async def test_scaffold_is_fail_closed_even_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_ENABLED", "true")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_APP_ID", "123456")
    monkeypatch.setenv("R_AGENT_OFFICIAL_QQ_CLIENT_SECRET", "a-secure-client-secret")
    adapter = OfficialQQAdapter(OfficialQQConfig.from_env())

    status = await adapter.status()

    assert status.configured is True
    assert status.connected is False
    assert status.reason == "adapter_not_activated"


def test_registry_rejects_unknown_and_duplicate_channels() -> None:
    registry = TransportRegistry()
    adapter = OfficialQQAdapter(OfficialQQConfig(False, None, None))
    registry.register(adapter)

    assert registry.channels() == ("qq_official",)
    with pytest.raises(ValueError, match="unique"):
        registry.register(adapter)
    with pytest.raises(TransportUnavailable, match="not registered"):
        registry.get("onebot")
