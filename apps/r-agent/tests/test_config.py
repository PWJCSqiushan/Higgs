import pytest

from r_agent.config import ConfigError, Settings, load_env_file


def test_owner_is_unconfigured_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("R_AGENT_OWNER_QQ", raising=False)
    settings = Settings.from_env()
    assert settings.owner_qq is None
    assert settings.allowed_private_qqs == frozenset()
    assert settings.allowed_groups == frozenset()


def test_phase_one_refuses_non_shadow_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_AGENT_SHADOW_MODE", "false")
    with pytest.raises(ConfigError, match="shadow mode"):
        Settings.from_env()


def test_phase_two_can_parse_explicit_non_shadow_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_AGENT_SHADOW_MODE", "false")
    settings = Settings.from_env(require_shadow=False)
    assert settings.shadow_mode is False


@pytest.mark.parametrize(
    "url",
    [
        "ws://example.com:3001",
        "ws://localhost.evil.example:3001",
        "ws://127.0.0.1.evil.example:3001",
        "http://127.0.0.1:3001",
        "ws://user:pass@localhost:3001",
    ],
)
def test_non_loopback_or_ambiguous_onebot_endpoint_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    monkeypatch.setenv("R_AGENT_ONEBOT_WS_URL", url)
    with pytest.raises(ConfigError, match="loopback"):
        Settings.from_env()


def test_env_file_loads_only_r_agent_keys(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / ".env"
    path.write_text("R_AGENT_OWNER_QQ=800001\n", encoding="utf-8")
    monkeypatch.delenv("R_AGENT_OWNER_QQ", raising=False)
    load_env_file(path)
    assert Settings.from_env(env_file=path).owner_qq == "800001"


def test_env_file_rejects_unscoped_key(tmp_path) -> None:
    path = tmp_path / ".env"
    path.write_text("PATH=bad\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid R_AGENT_ key"):
        load_env_file(path)


def test_private_allowlist_is_parsed_and_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_AGENT_ALLOWED_PRIVATE_QQS", "800002,800003,800002")
    settings = Settings.from_env()
    assert settings.allowed_private_qqs == frozenset({"800002", "800003"})


def test_private_allowlist_rejects_wildcards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_AGENT_ALLOWED_PRIVATE_QQS", "*")
    with pytest.raises(ConfigError, match="ASCII digits"):
        Settings.from_env()


def test_exact_trusted_container_onebot_host_requires_strong_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_ONEBOT_TRUSTED_HOST", "napcat")
    monkeypatch.setenv("R_AGENT_ONEBOT_WS_URL", "ws://napcat:3001")
    monkeypatch.setenv("R_AGENT_ONEBOT_ACCESS_TOKEN", "x" * 32)
    settings = Settings.from_env()
    assert settings.onebot_ws_url == "ws://napcat:3001"


def test_trusted_container_host_rejects_weak_token_and_lookalikes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("R_AGENT_ONEBOT_TRUSTED_HOST", "napcat")
    monkeypatch.setenv("R_AGENT_ONEBOT_WS_URL", "ws://napcat:3001")
    monkeypatch.setenv("R_AGENT_ONEBOT_ACCESS_TOKEN", "weak")
    with pytest.raises(ConfigError, match="32"):
        Settings.from_env()

    monkeypatch.setenv("R_AGENT_ONEBOT_ACCESS_TOKEN", "x" * 32)
    monkeypatch.setenv("R_AGENT_ONEBOT_WS_URL", "ws://napcat.evil.example:3001")
    with pytest.raises(ConfigError, match="explicitly trusted"):
        Settings.from_env()
