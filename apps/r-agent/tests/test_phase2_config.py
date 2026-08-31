from pathlib import Path

import pytest

from r_agent.config import ConfigError, Settings
from r_agent.phase2_cli import _phase2_settings


def settings(
    *,
    shadow: bool,
    owner: str | None = "800001",
    private_users: frozenset[str] = frozenset(),
    groups: frozenset[str] = frozenset(),
) -> Settings:
    return Settings(
        shadow_mode=shadow,
        ingest_enabled=True,
        data_dir=Path("data"),
        onebot_ws_url="ws://127.0.0.1:3001",
        onebot_access_token=None,
        owner_qq=owner,
        allowed_private_qqs=private_users,
        allowed_groups=groups,
        journal_retention_days=7,
    )


def test_live_requires_explicit_enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_AGENT_REPLY_MODE", "live")
    with pytest.raises(ConfigError, match="PHASE2_ENABLE_LIVE"):
        _phase2_settings(settings(shadow=False))


def test_live_requires_non_shadow_and_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_AGENT_REPLY_MODE", "live")
    monkeypatch.setenv("R_AGENT_PHASE2_ENABLE_LIVE", "true")
    with pytest.raises(ConfigError, match="SHADOW_MODE=false"):
        _phase2_settings(settings(shadow=True))
    with pytest.raises(ConfigError, match="OWNER_QQ"):
        _phase2_settings(settings(shadow=False, owner=None))

    phase = _phase2_settings(settings(shadow=False))
    assert phase.mode == "live"


def test_draft_requires_shadow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_AGENT_REPLY_MODE", "draft")
    with pytest.raises(ConfigError, match="require R_AGENT_SHADOW_MODE=true"):
        _phase2_settings(settings(shadow=False))


def test_invalid_boolean_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_AGENT_REPLY_MODE", "draft")
    monkeypatch.setenv("R_AGENT_REPLY_GROUP_REQUIRE_MENTION", "maybe")
    with pytest.raises(ConfigError, match="must be a boolean"):
        _phase2_settings(settings(shadow=True))


def test_reply_groups_must_be_valid_and_ingress_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_REPLY_MODE", "draft")
    monkeypatch.setenv("R_AGENT_REPLY_ALLOWED_GROUPS", "700002")
    with pytest.raises(ConfigError, match="subset"):
        _phase2_settings(settings(shadow=True, groups=frozenset({"700001"})))

    monkeypatch.setenv("R_AGENT_REPLY_ALLOWED_GROUPS", "not-a-qq")
    with pytest.raises(ConfigError, match="ASCII digits"):
        _phase2_settings(settings(shadow=True, groups=frozenset({"700001"})))


def test_rate_limit_config_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_AGENT_REPLY_MODE", "draft")
    monkeypatch.setenv("R_AGENT_REPLY_MAX_PER_MINUTE", "0")
    with pytest.raises(ConfigError, match="between 1 and 10"):
        _phase2_settings(settings(shadow=True))


def test_reply_private_users_must_be_ingress_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_REPLY_MODE", "draft")
    monkeypatch.setenv("R_AGENT_REPLY_ALLOWED_PRIVATE_QQS", "800002")
    with pytest.raises(ConfigError, match="subset"):
        _phase2_settings(settings(shadow=True, private_users=frozenset({"800003"})))

    phase = _phase2_settings(settings(shadow=True, private_users=frozenset({"800002"})))
    assert phase.private_users == frozenset({"800002"})


def test_natural_trigger_groups_must_be_reply_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_REPLY_MODE", "draft")
    monkeypatch.setenv("R_AGENT_REPLY_ALLOWED_GROUPS", "700001")
    monkeypatch.setenv("R_AGENT_REPLY_NATURAL_TRIGGER_GROUPS", "700002")
    with pytest.raises(ConfigError, match="subset"):
        _phase2_settings(settings(shadow=True, groups=frozenset({"700001", "700002"})))

    monkeypatch.setenv("R_AGENT_REPLY_NATURAL_TRIGGER_GROUPS", "700001")
    phase = _phase2_settings(settings(shadow=True, groups=frozenset({"700001"})))
    assert phase.natural_trigger_groups == frozenset({"700001"})


def test_self_memory_defaults_off_without_schema_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_REPLY_MODE", "draft")

    phase = _phase2_settings(settings(shadow=True))

    assert phase.self_memory_mode == "off"
    assert phase.self_memory_schema_v4_enabled is False


def test_self_memory_shadow_requires_explicit_schema_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_REPLY_MODE", "draft")
    monkeypatch.setenv("R_AGENT_SELF_MEMORY_MODE", "shadow")
    with pytest.raises(ConfigError, match="schema v4"):
        _phase2_settings(settings(shadow=True))

    monkeypatch.setenv("R_AGENT_SELF_MEMORY_SCHEMA_V4_ENABLED", "true")
    phase = _phase2_settings(settings(shadow=True))
    assert phase.self_memory_mode == "shadow"
    assert phase.self_memory_schema_v4_enabled is True


def test_personal_memory_defaults_off_without_schema_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_REPLY_MODE", "draft")

    phase = _phase2_settings(settings(shadow=True))

    assert phase.personal_memory_mode == "off"
    assert phase.personal_memory_schema_v5_enabled is False


def test_personal_memory_modes_require_explicit_schema_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_REPLY_MODE", "draft")
    monkeypatch.setenv("R_AGENT_PERSONAL_MEMORY_MODE", "shadow")
    with pytest.raises(ConfigError, match="schema v5"):
        _phase2_settings(settings(shadow=True))

    monkeypatch.setenv("R_AGENT_PERSONAL_MEMORY_SCHEMA_V5_ENABLED", "true")
    phase = _phase2_settings(settings(shadow=True))
    assert phase.personal_memory_mode == "shadow"
    assert phase.personal_memory_schema_v5_enabled is True

    monkeypatch.setenv("R_AGENT_PERSONAL_MEMORY_MODE", "active")
    assert _phase2_settings(settings(shadow=True)).personal_memory_mode == "active"

    monkeypatch.setenv("R_AGENT_PERSONAL_MEMORY_MODE", "automatic")
    with pytest.raises(ConfigError, match="off, shadow, or active"):
        _phase2_settings(settings(shadow=True))


def test_group_memory_defaults_off_and_requires_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_REPLY_MODE", "draft")
    phase = _phase2_settings(settings(shadow=True))
    assert phase.group_memory_enabled is False

    monkeypatch.setenv("R_AGENT_GROUP_MEMORY_ENABLED", "true")
    phase = _phase2_settings(settings(shadow=True))
    assert phase.group_memory_enabled is True

    monkeypatch.setenv("R_AGENT_GROUP_MEMORY_ENABLED", "maybe")
    with pytest.raises(ConfigError, match="must be a boolean"):
        _phase2_settings(settings(shadow=True))
