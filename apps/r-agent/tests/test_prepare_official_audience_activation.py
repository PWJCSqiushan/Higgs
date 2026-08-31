from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "deploy"
    / "existing-server"
    / "prepare_official_audience_activation.py"
)
SPEC = importlib.util.spec_from_file_location("prepare_official_audience_activation", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ACTIVATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ACTIVATION)


def _write_private(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")
    path.chmod(0o600)


def _fixture(tmp_path: Path, surface: str) -> tuple[Path, Path, Path, Path]:
    app_id = "123456789"
    bot_id = "bot-id"
    openids = [f"{surface}-audience"]
    fingerprint = ACTIVATION._canonical_fingerprint(
        scope=surface,
        app_id=app_id,
        bot_id=bot_id,
        version=1,
        openids=openids,
    )
    allowlist = {
        "version": 2,
        "scope": surface,
        "allowlist_version": 1,
        "epoch_id": "epoch-id",
        "nonce": "a" * 64,
        "app_id": app_id,
        "bot_id": bot_id,
        "frozen_at_ms": 1_000,
        "previous_version": None,
        "previous_fingerprint": None,
        "fingerprint": fingerprint,
        "openids": openids,
    }
    agent = tmp_path / "higgs.env"
    sidecar = tmp_path / "official-qq.env"
    allowlist_path = tmp_path / f"allowed-{surface}.json"
    backup = tmp_path / "backup"
    agent_keys = {
        "R_AGENT_OFFICIAL_QQ_ENABLED": "true",
        "R_AGENT_OFFICIAL_QQ_REPLY_ENABLED": "true",
        "R_AGENT_OFFICIAL_QQ_OWNER_OPENID": "owner-id",
        "R_AGENT_PERSONA_V2_ENABLED": "true",
        "R_AGENT_IDENTITY_SCHEMA_V2_ENABLED": "false",
        "R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED": "false",
        "R_AGENT_OFFICIAL_QQ_GROUP_ENABLED": "false",
        "R_AGENT_PERSONA_V2_ORDINARY_PRIVATE_ENABLED": "false",
        "R_AGENT_PERSONA_V2_GROUP_ENABLED": "false",
        "R_AGENT_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS": (openids[0] if surface == "private" else ""),
        "R_AGENT_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS": (openids[0] if surface == "group" else ""),
        f"R_AGENT_OFFICIAL_QQ_{surface.upper()}_ALLOWLIST_VERSION": "1",
        f"R_AGENT_OFFICIAL_QQ_{surface.upper()}_ALLOWLIST_FINGERPRINT": fingerprint,
    }
    sidecar_keys = {
        "HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED": "true",
        "HIGGS_OFFICIAL_QQ_CAPTURE_ONLY": "false",
        "HIGGS_OFFICIAL_QQ_OWNER_OPENID": "owner-id",
        "HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED": "false",
        "HIGGS_OFFICIAL_QQ_GROUP_ENABLED": "false",
        "HIGGS_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS": (openids[0] if surface == "private" else ""),
        "HIGGS_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS": (openids[0] if surface == "group" else ""),
        f"HIGGS_OFFICIAL_QQ_{surface.upper()}_ALLOWLIST_VERSION": "1",
        f"HIGGS_OFFICIAL_QQ_{surface.upper()}_ALLOWLIST_FINGERPRINT": fingerprint,
        "QQBOT_APP_ID": app_id,
    }
    _write_private(agent, "\n".join(f"{key}={value}" for key, value in agent_keys.items()) + "\n")
    _write_private(
        sidecar,
        "\n".join(f"{key}={value}" for key, value in sidecar_keys.items()) + "\n",
    )
    _write_private(allowlist_path, json.dumps(allowlist, separators=(",", ":")) + "\n")
    return agent, sidecar, allowlist_path, backup


@pytest.mark.parametrize(
    ("surface", "agent_gate", "sidecar_gate", "persona_gate"),
    [
        (
            "private",
            "R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=true",
            "HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=true",
            "R_AGENT_PERSONA_V2_ORDINARY_PRIVATE_ENABLED=true",
        ),
        (
            "group",
            "R_AGENT_OFFICIAL_QQ_GROUP_ENABLED=true",
            "HIGGS_OFFICIAL_QQ_GROUP_ENABLED=true",
            "R_AGENT_PERSONA_V2_GROUP_ENABLED=true",
        ),
    ],
)
def test_prepare_opens_only_the_selected_versioned_audience(
    tmp_path: Path,
    surface: str,
    agent_gate: str,
    sidecar_gate: str,
    persona_gate: str,
) -> None:
    agent, sidecar, allowlist, backup = _fixture(tmp_path, surface)

    ACTIVATION.prepare(
        surface=surface,
        agent_env=agent,
        sidecar_env=sidecar,
        allowlist_path=allowlist,
        other_allowlist_path=None,
        backup_dir=backup,
    )

    agent_text = agent.read_text(encoding="utf-8")
    sidecar_text = sidecar.read_text(encoding="utf-8")
    assert "R_AGENT_IDENTITY_SCHEMA_V2_ENABLED=true" in agent_text
    assert agent_gate in agent_text
    assert persona_gate in agent_text
    assert sidecar_gate in sidecar_text
    assert (backup / "higgs.env").is_file()
    assert (backup / "official-qq.env").is_file()


def test_prepare_fails_before_writing_on_allowlist_provenance_drift(tmp_path: Path) -> None:
    agent, sidecar, allowlist, backup = _fixture(tmp_path, "private")
    original_agent = agent.read_bytes()
    original_sidecar = sidecar.read_bytes()
    text = sidecar.read_text(encoding="utf-8")
    _write_private(sidecar, text.replace("_ALLOWLIST_VERSION=1", "_ALLOWLIST_VERSION=2"))

    with pytest.raises(ACTIVATION.ActivationError, match="provenance differs"):
        ACTIVATION.prepare(
            surface="private",
            agent_env=agent,
            sidecar_env=sidecar,
            allowlist_path=allowlist,
            other_allowlist_path=None,
            backup_dir=backup,
        )

    assert agent.read_bytes() == original_agent
    assert sidecar.read_bytes() != original_sidecar
    assert not backup.exists()


def test_prepare_restores_both_envs_if_the_second_atomic_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, sidecar, allowlist, backup = _fixture(tmp_path, "group")
    original_agent = agent.read_bytes()
    original_sidecar = sidecar.read_bytes()
    real_write = ACTIVATION._atomic_write
    calls = 0

    def fail_second(path: Path, content: str, failed_dir: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated")
        real_write(path, content, failed_dir)

    monkeypatch.setattr(ACTIVATION, "_atomic_write", fail_second)

    with pytest.raises(OSError, match="simulated"):
        ACTIVATION.prepare(
            surface="group",
            agent_env=agent,
            sidecar_env=sidecar,
            allowlist_path=allowlist,
            other_allowlist_path=None,
            backup_dir=backup,
        )

    assert agent.read_bytes() == original_agent
    assert sidecar.read_bytes() == original_sidecar


@pytest.mark.parametrize(("first", "second"), [("private", "group"), ("group", "private")])
def test_prepare_can_activate_the_second_audience_without_closing_the_first(
    tmp_path: Path,
    first: str,
    second: str,
) -> None:
    agent, sidecar, allowlist, backup = _fixture(tmp_path, second)
    first_openids = [f"{first}-audience"]
    first_fingerprint = ACTIVATION._canonical_fingerprint(
        scope=first,
        app_id="123456789",
        bot_id="bot-id",
        version=1,
        openids=first_openids,
    )
    first_allowlist = tmp_path / f"allowed-{first}.json"
    _write_private(
        first_allowlist,
        json.dumps(
            {
                "version": 2,
                "scope": first,
                "allowlist_version": 1,
                "epoch_id": "first-epoch",
                "nonce": "b" * 64,
                "app_id": "123456789",
                "bot_id": "bot-id",
                "frozen_at_ms": 1_001,
                "previous_version": None,
                "previous_fingerprint": None,
                "fingerprint": first_fingerprint,
                "openids": first_openids,
            },
            separators=(",", ":"),
        )
        + "\n",
    )
    agent_first = (
        "R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED"
        if first == "private"
        else "R_AGENT_OFFICIAL_QQ_GROUP_ENABLED"
    )
    sidecar_first = (
        "HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED"
        if first == "private"
        else "HIGGS_OFFICIAL_QQ_GROUP_ENABLED"
    )
    persona_first = (
        "R_AGENT_PERSONA_V2_ORDINARY_PRIVATE_ENABLED"
        if first == "private"
        else "R_AGENT_PERSONA_V2_GROUP_ENABLED"
    )
    agent_ids_first = (
        "R_AGENT_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS"
        if first == "private"
        else "R_AGENT_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS"
    )
    sidecar_ids_first = (
        "HIGGS_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS"
        if first == "private"
        else "HIGGS_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS"
    )
    _write_private(
        agent,
        agent.read_text(encoding="utf-8")
        .replace(
            "R_AGENT_IDENTITY_SCHEMA_V2_ENABLED=false",
            "R_AGENT_IDENTITY_SCHEMA_V2_ENABLED=true",
        )
        .replace(f"{agent_first}=false", f"{agent_first}=true")
        .replace(f"{persona_first}=false", f"{persona_first}=true")
        .replace(f"{agent_ids_first}=", f"{agent_ids_first}={first_openids[0]}")
        + f"R_AGENT_OFFICIAL_QQ_{first.upper()}_ALLOWLIST_VERSION=1\n"
        + f"R_AGENT_OFFICIAL_QQ_{first.upper()}_ALLOWLIST_FINGERPRINT={first_fingerprint}\n",
    )
    _write_private(
        sidecar,
        sidecar.read_text(encoding="utf-8")
        .replace(f"{sidecar_first}=false", f"{sidecar_first}=true")
        .replace(f"{sidecar_ids_first}=", f"{sidecar_ids_first}={first_openids[0]}")
        + f"HIGGS_OFFICIAL_QQ_{first.upper()}_ALLOWLIST_VERSION=1\n"
        + f"HIGGS_OFFICIAL_QQ_{first.upper()}_ALLOWLIST_FINGERPRINT={first_fingerprint}\n",
    )

    ACTIVATION.prepare(
        surface=second,
        agent_env=agent,
        sidecar_env=sidecar,
        allowlist_path=allowlist,
        other_allowlist_path=first_allowlist,
        backup_dir=backup,
    )

    assert f"{agent_first}=true" in agent.read_text(encoding="utf-8")
    assert f"{sidecar_first}=true" in sidecar.read_text(encoding="utf-8")
    assert f"{persona_first}=true" in agent.read_text(encoding="utf-8")


def test_prepare_rejects_mismatched_existing_audience_gates(tmp_path: Path) -> None:
    agent, sidecar, allowlist, backup = _fixture(tmp_path, "group")
    _write_private(
        agent,
        agent.read_text(encoding="utf-8").replace(
            "R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=false",
            "R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=true",
        ),
    )

    with pytest.raises(ACTIVATION.ActivationError, match="gates differ"):
        ACTIVATION.prepare(
            surface="group",
            agent_env=agent,
            sidecar_env=sidecar,
            allowlist_path=allowlist,
            other_allowlist_path=None,
            backup_dir=backup,
        )


def test_check_only_validates_without_writing_or_creating_backup(tmp_path: Path) -> None:
    agent, sidecar, allowlist, backup = _fixture(tmp_path, "private")
    original_agent = agent.read_bytes()
    original_sidecar = sidecar.read_bytes()

    ACTIVATION.prepare(
        surface="private",
        agent_env=agent,
        sidecar_env=sidecar,
        allowlist_path=allowlist,
        other_allowlist_path=None,
        backup_dir=backup,
        check_only=True,
    )

    assert agent.read_bytes() == original_agent
    assert sidecar.read_bytes() == original_sidecar
    assert not backup.exists()


def test_prepare_rejects_invalid_frozen_timestamp_before_writing(tmp_path: Path) -> None:
    agent, sidecar, allowlist, backup = _fixture(tmp_path, "private")
    payload = json.loads(allowlist.read_text(encoding="utf-8"))
    payload["frozen_at_ms"] = True
    _write_private(allowlist, json.dumps(payload, separators=(",", ":")) + "\n")

    with pytest.raises(ACTIVATION.ActivationError, match="metadata is invalid"):
        ACTIVATION.prepare(
            surface="private",
            agent_env=agent,
            sidecar_env=sidecar,
            allowlist_path=allowlist,
            other_allowlist_path=None,
            backup_dir=backup,
        )


def test_first_group_activation_requires_exactly_one_group(tmp_path: Path) -> None:
    agent, sidecar, allowlist, backup = _fixture(tmp_path, "group")
    payload = json.loads(allowlist.read_text(encoding="utf-8"))
    payload["openids"] = ["group-audience", "second-group"]
    payload["fingerprint"] = ACTIVATION._canonical_fingerprint(
        scope="group",
        app_id=payload["app_id"],
        bot_id=payload["bot_id"],
        version=payload["allowlist_version"],
        openids=payload["openids"],
    )
    _write_private(allowlist, json.dumps(payload, separators=(",", ":")) + "\n")
    _write_private(
        agent,
        agent.read_text(encoding="utf-8")
        .replace(
            "R_AGENT_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS=group-audience",
            "R_AGENT_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS=group-audience,second-group",
        )
        .replace(
            next(
                line
                for line in agent.read_text(encoding="utf-8").splitlines()
                if line.startswith("R_AGENT_OFFICIAL_QQ_GROUP_ALLOWLIST_FINGERPRINT=")
            ),
            f"R_AGENT_OFFICIAL_QQ_GROUP_ALLOWLIST_FINGERPRINT={payload['fingerprint']}",
        ),
    )
    _write_private(
        sidecar,
        sidecar.read_text(encoding="utf-8")
        .replace(
            "HIGGS_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS=group-audience",
            "HIGGS_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS=group-audience,second-group",
        )
        .replace(
            next(
                line
                for line in sidecar.read_text(encoding="utf-8").splitlines()
                if line.startswith("HIGGS_OFFICIAL_QQ_GROUP_ALLOWLIST_FINGERPRINT=")
            ),
            f"HIGGS_OFFICIAL_QQ_GROUP_ALLOWLIST_FINGERPRINT={payload['fingerprint']}",
        ),
    )

    with pytest.raises(ACTIVATION.ActivationError, match="exactly one group"):
        ACTIVATION.prepare(
            surface="group",
            agent_env=agent,
            sidecar_env=sidecar,
            allowlist_path=allowlist,
            other_allowlist_path=None,
            backup_dir=backup,
        )


def test_prepare_rejects_allowlist_for_another_authenticated_bot(tmp_path: Path) -> None:
    agent, sidecar, allowlist, backup = _fixture(tmp_path, "private")
    session = tmp_path / "session.json"
    _write_private(
        session,
        json.dumps(
            {"version": 1, "session": None, "bot_id": "other-bot", "updated_at_ms": 1},
            separators=(",", ":"),
        )
        + "\n",
    )

    with pytest.raises(ACTIVATION.ActivationError, match="authenticated session"):
        ACTIVATION.prepare(
            surface="private",
            agent_env=agent,
            sidecar_env=sidecar,
            allowlist_path=allowlist,
            other_allowlist_path=None,
            backup_dir=backup,
            session_state_path=session,
        )
