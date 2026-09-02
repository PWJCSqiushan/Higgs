from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from r_agent.identity import IdentityStore

MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "deploy"
    / "existing-server"
    / "prepare_official_identity_v2.py"
)
SPEC = importlib.util.spec_from_file_location("prepare_official_identity_v2", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


def _write_private(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")
    path.chmod(0o600)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    agent = tmp_path / "higgs.env"
    sidecar = tmp_path / "official-qq.env"
    session = tmp_path / "session.json"
    identity = tmp_path / "identity.sqlite"
    recycle = tmp_path / "recycle"
    _write_private(
        agent,
        "\n".join(
            (
                "R_AGENT_OFFICIAL_QQ_ENABLED=true",
                "R_AGENT_OFFICIAL_QQ_REPLY_ENABLED=true",
                "R_AGENT_OWNER_QQ=owner-qq",
                "R_AGENT_OFFICIAL_QQ_OWNER_OPENID=owner-openid",
                "R_AGENT_IDENTITY_SCHEMA_V2_ENABLED=false",
                "R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=false",
                "R_AGENT_OFFICIAL_QQ_GROUP_ENABLED=false",
                "R_AGENT_PERSONA_V2_ORDINARY_PRIVATE_ENABLED=false",
                "R_AGENT_PERSONA_V2_GROUP_ENABLED=false",
            )
        )
        + "\n",
    )
    _write_private(
        sidecar,
        "\n".join(
            (
                "HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED=true",
                "HIGGS_OFFICIAL_QQ_CAPTURE_ONLY=false",
                "HIGGS_OFFICIAL_QQ_OWNER_OPENID=owner-openid",
                "HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=false",
                "HIGGS_OFFICIAL_QQ_GROUP_ENABLED=false",
            )
        )
        + "\n",
    )
    _write_private(
        session,
        json.dumps(
            {"version": 1, "session": None, "bot_id": "bot-account", "updated_at_ms": 1},
            separators=(",", ":"),
        )
        + "\n",
    )
    store = IdentityStore(
        identity,
        owner_qq="owner-qq",
        owner_identities=(("qq_official", "owner-openid"),),
    )
    store.initialize()
    identity.chmod(0o600)
    return agent, sidecar, session, identity, recycle


def test_check_only_validates_without_changing_database_or_environment(
    tmp_path: Path,
) -> None:
    agent, sidecar, session, identity, recycle = _fixture(tmp_path)
    before_env = agent.read_bytes()

    MIGRATION.prepare(
        agent_env=agent,
        sidecar_env=sidecar,
        session_state=session,
        identity_path=identity,
        recycle_dir=recycle,
        check_only=True,
    )

    assert agent.read_bytes() == before_env
    with sqlite3.connect(identity) as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='identity_schema_meta'"
            ).fetchone()
            is None
        )


def test_migration_preserves_owner_principal_and_binds_authenticated_bot(
    tmp_path: Path,
) -> None:
    agent, sidecar, session, identity, recycle = _fixture(tmp_path)
    with sqlite3.connect(identity) as connection:
        principal_before = connection.execute(
            "SELECT principal_id FROM external_identities WHERE channel='qq'"
        ).fetchone()[0]

    MIGRATION.prepare(
        agent_env=agent,
        sidecar_env=sidecar,
        session_state=session,
        identity_path=identity,
        recycle_dir=recycle,
    )

    assert "R_AGENT_IDENTITY_SCHEMA_V2_ENABLED=true" in agent.read_text(encoding="utf-8")
    with sqlite3.connect(identity) as connection:
        assert connection.execute(
            "SELECT version FROM identity_schema_meta WHERE singleton=1"
        ).fetchone() == (2,)
        assert connection.execute(
            """
            SELECT principal_id FROM account_external_identities
            WHERE channel='qq_official' AND account_id='bot-account'
              AND external_id='owner-openid'
            """
        ).fetchone() == (principal_before,)
        assert connection.execute(
            """
            SELECT account_id FROM configured_identity_accounts
            WHERE channel='qq_official' AND external_id='owner-openid'
            """
        ).fetchone() == ("bot-account",)


@pytest.mark.parametrize(
    ("key", "source"),
    [
        ("R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED", "agent"),
        ("R_AGENT_OFFICIAL_QQ_GROUP_ENABLED", "agent"),
        ("R_AGENT_PERSONA_V2_ORDINARY_PRIVATE_ENABLED", "agent"),
        ("R_AGENT_PERSONA_V2_GROUP_ENABLED", "agent"),
        ("HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED", "sidecar"),
        ("HIGGS_OFFICIAL_QQ_GROUP_ENABLED", "sidecar"),
    ],
)
def test_migration_rejects_any_expanded_audience(tmp_path: Path, key: str, source: str) -> None:
    agent, sidecar, session, identity, recycle = _fixture(tmp_path)
    target = agent if source == "agent" else sidecar
    _write_private(
        target, target.read_text(encoding="utf-8").replace(f"{key}=false", f"{key}=true")
    )

    with pytest.raises(MIGRATION.MigrationError, match="gates must remain disabled"):
        MIGRATION.prepare(
            agent_env=agent,
            sidecar_env=sidecar,
            session_state=session,
            identity_path=identity,
            recycle_dir=recycle,
        )


def test_migration_rejects_existing_schema_gate(tmp_path: Path) -> None:
    agent, sidecar, session, identity, recycle = _fixture(tmp_path)
    _write_private(
        agent,
        agent.read_text(encoding="utf-8").replace(
            "R_AGENT_IDENTITY_SCHEMA_V2_ENABLED=false",
            "R_AGENT_IDENTITY_SCHEMA_V2_ENABLED=true",
        ),
    )

    with pytest.raises(MIGRATION.MigrationError, match="already enabled"):
        MIGRATION.prepare(
            agent_env=agent,
            sidecar_env=sidecar,
            session_state=session,
            identity_path=identity,
            recycle_dir=recycle,
        )


def test_migration_rejects_partial_schema_while_gate_is_off(tmp_path: Path) -> None:
    agent, sidecar, session, identity, recycle = _fixture(tmp_path)
    with sqlite3.connect(identity) as connection:
        connection.execute(
            """
            CREATE TABLE configured_identity_accounts (
                channel TEXT NOT NULL, external_id TEXT NOT NULL, account_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(channel, external_id)
            )
            """
        )
        connection.execute(
            "INSERT INTO configured_identity_accounts(channel, external_id, account_id) "
            "VALUES ('qq_official', 'owner-openid', 'another-bot')"
        )

    with pytest.raises(MIGRATION.MigrationError, match="tables already exist"):
        MIGRATION.prepare(
            agent_env=agent,
            sidecar_env=sidecar,
            session_state=session,
            identity_path=identity,
            recycle_dir=recycle,
        )


def test_shell_migration_is_agent_only_and_rollback_capable() -> None:
    script = (MODULE_PATH.parent / "migrate_official_identity_v2.sh").read_text(encoding="utf-8")

    assert "PRODUCTION_IDENTITY_MIGRATION_CONFIRMED" in script
    assert "prepare_official_identity_v2.py" in script
    assert "identity.sqlite" in script
    assert "--force-recreate agent" in script
    assert "--force-recreate official-qq-sidecar" not in script
    assert "--force-recreate napcat" not in script
    assert "sidecar or NapCat changed unexpectedly" in script
    assert "ordinary_audiences_remain_disabled" in script
