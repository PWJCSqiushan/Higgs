from r_agent.phase2_cli import _env_path


def test_env_path_defaults_to_working_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("R_AGENT_ENV_FILE", raising=False)
    monkeypatch.chdir(tmp_path)

    assert _env_path() == (tmp_path / ".env").resolve()


def test_env_path_supports_writable_container_config(monkeypatch, tmp_path):
    configured = tmp_path / "config" / "higgs.env"
    monkeypatch.setenv("R_AGENT_ENV_FILE", str(configured))

    assert _env_path() == configured.resolve()
