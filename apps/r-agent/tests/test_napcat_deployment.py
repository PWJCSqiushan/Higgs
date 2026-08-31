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


def test_official_systemd_unit_owns_the_complete_overlay_and_preflight() -> None:
    text = (ROOT / "deploy/existing-server/higgs-existing-official.service").read_text(
        encoding="utf-8"
    )
    # The legacy unit is a RemainAfterExit oneshot whose ExecStop stops the
    # complete stack, including NapCat.  The official unit must therefore not
    # conflict with it: migration disables the legacy unit without stopping it.
    assert "Conflicts=higgs-existing.service" not in text
    assert "ExecStartPre=/bin/sh ./prepare_official_qq_runtime.sh" in text
    for command in ("ExecStart=", "ExecReload=", "ExecStop="):
        line = next(item for item in text.splitlines() if item.startswith(command))
        assert "-f compose.yml -f compose.official-qq.yml" in line
        assert "--profile official-qq" in line


def test_node_owner_binding_is_single_user_private_and_fail_closed() -> None:
    text = (ROOT / "deploy/existing-server/run_official_node_owner_bind.sh").read_text(
        encoding="utf-8"
    )
    assert "ONLY_OWNER_IS_TEST_USER" in text
    assert "another official Gateway is active" in text
    assert "HIGGS_OFFICIAL_QQ_BIND_OWNER_FILE" in text
    assert "R_AGENT_OFFICIAL_QQ_ENABLED" in text
    assert "owner is already configured" in text
    assert "official QQ remains disabled" in text
    assert "owner.openid" in text
    assert "/srv/trash/higgs-official-owner-bind-" in text
    assert "restore_private_configuration" in text
    assert "rollback_required=true" in text
    assert 'echo "$owner"' not in text
    assert 'cat "$owner_file"' not in text
    assert "\nrm " not in text
    assert ".unlink(" not in text


def test_official_stability_observer_is_anonymous_and_read_only() -> None:
    text = (ROOT / "deploy/existing-server/observe_official_stability.sh").read_text(
        encoding="utf-8"
    )
    assert "mode=ro" in text
    assert "PRAGMA query_only = ON" in text
    assert "transport_transitions" in text
    assert "official_processing_batches" in text
    assert "official_gateway_count=" in text
    assert "recreated_during_window=" in text
    assert "rejected_transition_count=" in text
    assert "fatal_transition_count=" in text
    assert "docker logs" not in text
    assert "docker restart" not in text
    assert "compose up" not in text
    assert "compose down" not in text
    assert "send_text" not in text
    assert "provider_message_id" not in text
    assert "message_id" not in text
    assert "QQBOT_APP_SECRET" not in text


def test_official_test_group_capture_is_versioned_bounded_and_non_activating() -> None:
    text = (ROOT / "deploy/existing-server/run_official_node_group_bind.sh").read_text(
        encoding="utf-8"
    )
    assert "CAPTURE_OFFICIAL_TEST_GROUP" in text
    assert "group-capture.json" in text
    assert "allowed-group-openids.json" in text
    assert "legacy group.openid requires explicit import" in text
    assert "HIGGS_OFFICIAL_QQ_GROUP_CAPTURE_BASELINE_VERSION" in text
    assert "HIGGS_OFFICIAL_QQ_GROUP_CAPTURE_BASELINE_FINGERPRINT" in text
    assert "private owner binding is absent" in text
    assert "audience, Persona, and identity gates must be disabled" in text
    assert "another official Gateway is active" in text
    assert "official_processing_batches WHERE state!='complete'" in text
    assert "compose stop -t 20 official-qq-sidecar" in text
    assert "compose up -d --no-deps official-qq-sidecar" in text
    assert "production_group_gate=unchanged" in text
    assert "agent_started=" in text
    assert "agent_restarts=" in text
    assert "napcat_started=" in text
    assert "/srv/trash/higgs-official-group-capture-before-" in text
    assert "group-capture.failed.json" in text
    assert "NapCat" not in text
    assert "R_AGENT_OFFICIAL_QQ_ENABLED" not in text
    assert "HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED" not in text
    assert 'echo "$group' not in text
    assert 'cat "$group_file"' not in text
    assert "docker logs" not in text
    assert "\nrm " not in text
    assert ".unlink(" not in text


def test_official_test_group_freeze_moves_baseline_and_syncs_metadata() -> None:
    text = (ROOT / "deploy/existing-server/freeze_official_group.sh").read_text(encoding="utf-8")
    helper = (ROOT / "deploy/existing-server/freeze_official_group.py").read_text(encoding="utf-8")
    assert "FREEZE_OFFICIAL_TEST_GROUP" in text
    assert "group-capture.json" in text
    assert "allowed-group-openids.json" in text
    assert "group.openid requires explicit import" in text
    assert "/srv/trash/higgs-official-group-freeze-" in text
    assert 'mv "$allowlist_file" "$previous_allowlist_file"' in text
    assert "group-capture.failed.json" in text
    assert "allowed-group-openids.failed.json" in text
    assert "PREVIOUS_ALLOWLIST_FILE" in text
    assert "R_AGENT_OFFICIAL_QQ_GROUP_ALLOWLIST_VERSION" in helper
    assert "R_AGENT_OFFICIAL_QQ_GROUP_ALLOWLIST_FINGERPRINT" in helper
    assert "HIGGS_OFFICIAL_QQ_GROUP_ALLOWLIST_VERSION" in helper
    assert "HIGGS_OFFICIAL_QQ_GROUP_ALLOWLIST_FINGERPRINT" in helper
    assert "audience, Persona, and identity gates must be disabled" in text
    assert "owner transport" in text
    assert "official_processing_batches WHERE state!='complete'" in text
    assert "audience_gates=unchanged" in text
    assert "rollback" in helper
    assert "print(len(openids))" in helper
    assert "R_AGENT_OFFICIAL_QQ_ENABLED" not in text
    assert "HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED" not in text
    assert 'echo "$group' not in text
    assert 'cat "$group_file"' not in text
    assert "docker logs" not in text
    assert "\nrm " not in text
    assert ".unlink(" not in text


def test_group_activation_uses_versioned_audience_gate_and_rejects_legacy_path() -> None:
    text = (ROOT / "deploy/existing-server/activate_official_test_group.sh").read_text(
        encoding="utf-8"
    )
    active_prefix = text.split("exit 2", 1)[0]
    assert "ACTIVATE_VERSIONED_TEST_GROUP" in active_prefix
    assert "PRODUCTION_AUDIENCE_CONFIRMED" in active_prefix
    assert "ACTIVATE_VERSIONED_OFFICIAL_AUDIENCE group" in active_prefix
    assert "legacy fixed-stability activation is disabled" in text
    assert "ACTIVATE_ONE_BOUND_TEST_GROUP" not in active_prefix
    assert "STABILITY_72H_ACCEPTED" not in active_prefix
    assert "docker logs" not in text
    assert "\nrm " not in text
    assert ".unlink(" not in text


def test_official_owner_proactive_activation_is_double_gated_and_reversible() -> None:
    text = (ROOT / "deploy/existing-server/activate_official_owner_proactive.sh").read_text(
        encoding="utf-8"
    )
    assert "ACTIVATE_OWNER_PROACTIVE" in text
    assert "STABILITY_72H_ACCEPTED" in text
    assert "R_AGENT_OFFICIAL_QQ_PROACTIVE_ENABLED" in text
    assert "HIGGS_OFFICIAL_QQ_PROACTIVE_ENABLED" in text
    assert "delivery_binding_version<2" in text
    assert "delivery_channel IS NULL OR delivery_channel!='qq'" in text
    assert "restore_private_configuration" in text
    assert "rollback_required=true" in text
    assert "/srv/trash/higgs-official-owner-proactive-" in text
    assert "official_processing_batches WHERE state!='complete'" in text
    assert "--force-recreate official-qq-sidecar" in text
    assert "--force-recreate agent" in text
    assert "NapCat changed unexpectedly" in text
    assert "docker logs" not in text
    assert "\nrm " not in text
    assert ".unlink(" not in text


def test_official_proactive_configuration_examples_default_off() -> None:
    agent = (ROOT / "apps/r-agent/.env.phase2.example").read_text(encoding="utf-8")
    sidecar = (ROOT / "deploy/existing-server/official-qq.env.example").read_text(encoding="utf-8")
    assert "R_AGENT_OFFICIAL_QQ_PROACTIVE_ENABLED=false" in agent
    assert "HIGGS_OFFICIAL_QQ_PROACTIVE_ENABLED=false" in sidecar


def test_opencloudos_build_prefetches_locked_dependencies_before_offline_sync() -> None:
    text = (ROOT / "apps/r-agent/Dockerfile.opencloudos").read_text(encoding="utf-8")
    pyproject = (ROOT / "apps/r-agent/pyproject.toml").read_text(encoding="utf-8")
    export = "uv export --frozen --no-dev --no-emit-project --no-hashes"
    install = "uv pip install"
    dependency_sync = "uv sync --frozen --no-dev --no-install-project --offline"
    project_sync = "uv sync --frozen --no-dev --offline --no-editable"

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


def test_official_qq_sidecar_is_opt_in_and_isolated_from_agent_data() -> None:
    compose = (ROOT / "deploy/existing-server/compose.official-qq.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "apps/official-qq-sidecar/Dockerfile").read_text(encoding="utf-8")
    package = (ROOT / "apps/official-qq-sidecar/package.json").read_text(encoding="utf-8")
    lock = (ROOT / "apps/official-qq-sidecar/package-lock.json").read_text(encoding="utf-8")
    notices = (ROOT / "apps/official-qq-sidecar/THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    stack_env = (ROOT / "deploy/existing-server/stack.env.example").read_text(encoding="utf-8")

    assert 'profiles: ["official-qq"]' in compose
    assert "official-qq.env" in compose
    assert "networks:\n      - egress" in compose
    assert "onebot" not in compose
    assert "docker.sock" not in compose.casefold()
    assert ":/var/lib/higgs\n" not in compose
    assert compose.count("official-qq-private:/var/lib/higgs-official") == 1
    assert "read_only: true" in compose
    assert 'user: "10001:10001"' in compose
    assert "official-qq-runtime:/run/higgs-official" in compose
    assert "no-new-privileges:true" in compose
    assert "cap_drop:\n      - ALL" in compose
    assert "NODE_IMAGE:" in compose
    assert "npm ci --omit=optional --ignore-scripts" in dockerfile
    assert dockerfile.startswith("ARG NODE_IMAGE\nFROM ${NODE_IMAGE}\n")
    assert "USER 10001:10001" in dockerfile
    assert '"@tencent-connect/qqbot-nodejs": "1.0.4"' in package
    assert '"version": "1.0.4"' in lock
    assert '"integrity": "sha512-' in lock
    assert "Copyright (c) 2026 Tencent" in notices
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in notices

    assert "official-qq-runtime:/run/higgs-official:ro" in compose
    assert "R_AGENT_OFFICIAL_QQ_TRANSPORT: sidecar" in compose
    assert "R_AGENT_OFFICIAL_QQ_SIDECAR_SOCKET: /run/higgs-official/sidecar.sock" in compose
    agent_overlay = compose.split("\n  official-qq-sidecar:\n", 1)[0]
    assert "r_agent.health_probe" in agent_overlay
    assert '"--max-age"' in agent_overlay
    assert '"90"' in agent_overlay
    assert "--require-qq-online" not in agent_overlay
    assert "QQBOT_APP_SECRET" not in compose
    assert "HIGGS_OFFICIAL_QQ_NODE_IMAGE=node:22-bookworm-slim@sha256:" in stack_env
    node_image = next(
        line.split("=", 1)[1]
        for line in stack_env.splitlines()
        if line.startswith("HIGGS_OFFICIAL_QQ_NODE_IMAGE=")
    )
    assert len(node_image.rsplit("@sha256:", 1)[1]) == 64

    prepare = (ROOT / "deploy/existing-server/prepare_official_qq_runtime.sh").read_text(
        encoding="utf-8"
    )
    assert "install -d -m 0700 -o 10001 -g 10001" in prepare
    assert '[ -L "$directory" ]' in prepare
