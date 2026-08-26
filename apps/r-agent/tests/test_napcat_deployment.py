from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_napcat_compose_has_bounded_restart_and_atomic_shared_heartbeat() -> None:
    for relative in (
        Path("deploy/existing-server/compose.yml"),
        Path("deploy/higgs/compose.yml"),
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert 'restart: "on-failure:5"' in text
        assert "napcat-health:/run/higgs-napcat-health" in text
        assert 'printf ok > \\"$$tmp\\"' in text
        assert 'mv -f \\"$$tmp\\" \\"$$marker\\"' in text
        assert "R_AGENT_NAPCAT_HEALTH_FILE: /run/higgs-napcat-health/heartbeat" in text
        assert "napcat-health:/run/higgs-napcat-health:ro" in text
        assert "napcat-health:" in text


def test_systemd_stack_unit_restores_bounded_compose_after_host_boot() -> None:
    for relative in (
        Path("deploy/existing-server/higgs-existing.service"),
        Path("deploy/server/higgs-stack.service"),
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "Requires=docker.service" in text
        assert "WantedBy=multi-user.target" in text
        assert "docker compose" in text
        assert "up -d" in text


def test_opencloudos_build_prefetches_locked_dependencies_before_offline_sync() -> None:
    text = (ROOT / "apps/r-agent/Dockerfile.opencloudos").read_text(encoding="utf-8")
    pyproject = (ROOT / "apps/r-agent/pyproject.toml").read_text(encoding="utf-8")
    export = "uv export --frozen --no-dev --no-emit-project --no-hashes"
    install = "uv pip install"
    dependency_sync = "uv sync --frozen --no-dev --no-install-project --offline"
    project_sync = "uv sync --frozen --no-dev --offline"

    assert 'requires = ["hatchling==1.27.0"]' in pyproject
    assert "UV_DEFAULT_INDEX=${PYPI_INDEX_URL}" in text
    assert export in text
    assert "--python /tmp/build-system/bin/python" in text
    assert '"hatchling==1.27.0"' in text
    assert "--requirements /tmp/requirements.locked.txt" in text
    assert dependency_sync in text
    assert project_sync in text
    assert text.index(export) < text.index(install) < text.index(dependency_sync)
    assert text.index('"hatchling==1.27.0"') < text.index(dependency_sync)
    assert text.index(dependency_sync) < text.index(project_sync)
