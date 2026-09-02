"""Prepare the account-scoped official identity migration without widening audience."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import stat
from pathlib import Path

SAFE_ID = re.compile(r"[!-~]{1,256}\Z")
BOOL_TRUE = {"1", "true", "yes", "on"}
BOOL_FALSE = {"0", "false", "no", "off"}


class MigrationError(ValueError):
    pass


def _read_env(path: Path) -> tuple[list[str], dict[str, str]]:
    if (
        path.is_symlink()
        or not path.is_file()
        or (os.name != "nt" and stat.S_IMODE(path.stat().st_mode) != 0o600)
    ):
        raise MigrationError("private environment is unsafe")
    lines = path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    for line in lines:
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in values:
            raise MigrationError("private environment contains a duplicate key")
        values[key] = value
    return lines, values


def _boolean(values: dict[str, str], key: str, *, default: bool = False) -> bool:
    raw = values.get(key, "").strip().casefold()
    if not raw:
        return default
    if raw in BOOL_TRUE:
        return True
    if raw in BOOL_FALSE:
        return False
    raise MigrationError(f"{key} is not boolean")


def _safe_id(values: dict[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value or "*" in value or not SAFE_ID.fullmatch(value):
        raise MigrationError(f"{key} is unavailable or unsafe")
    return value


def _session_bot_id(path: Path) -> str:
    if (
        path.is_symlink()
        or not path.is_file()
        or (os.name != "nt" and stat.S_IMODE(path.stat().st_mode) != 0o600)
    ):
        raise MigrationError("official session state is unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationError("official session state is invalid") from exc
    bot_id = payload.get("bot_id") if isinstance(payload, dict) else None
    if not isinstance(bot_id, str) or "*" in bot_id or not SAFE_ID.fullmatch(bot_id):
        raise MigrationError("authenticated Bot identity is unavailable")
    return bot_id


def _replace_key(lines: list[str], key: str, value: str) -> str:
    output: list[str] = []
    written = False
    for line in lines:
        if line.startswith(f"{key}="):
            if not written:
                output.append(f"{key}={value}")
                written = True
            continue
        output.append(line)
    if not written:
        output.append(f"{key}={value}")
    return "\n".join(output) + "\n"


def _atomic_write(path: Path, content: str, recycle_dir: Path) -> None:
    temporary = path.with_name(f".{path.name}.identity-v2-{os.getpid()}")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            original = path.stat()
            os.chown(temporary, original.st_uid, original.st_gid)
        os.replace(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary.exists():
            recycle_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            failed = recycle_dir / f"{temporary.name}.failed"
            os.replace(temporary, failed)
            os.chmod(failed, 0o600)


def _validate_disabled_audiences(
    agent: dict[str, str], sidecar: dict[str, str]
) -> None:
    for key in (
        "R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED",
        "R_AGENT_OFFICIAL_QQ_GROUP_ENABLED",
        "R_AGENT_PERSONA_V2_ORDINARY_PRIVATE_ENABLED",
        "R_AGENT_PERSONA_V2_GROUP_ENABLED",
    ):
        if _boolean(agent, key):
            raise MigrationError(
                "ordinary audience and Persona gates must remain disabled"
            )
    for key in (
        "HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED",
        "HIGGS_OFFICIAL_QQ_GROUP_ENABLED",
    ):
        if _boolean(sidecar, key):
            raise MigrationError("ordinary audience gates must remain disabled")


def _safe_identity_database(path: Path) -> None:
    if (
        path.is_symlink()
        or not path.is_file()
        or (os.name != "nt" and stat.S_IMODE(path.stat().st_mode) != 0o600)
    ):
        raise MigrationError("identity database is unsafe")


def _owner_principal(
    connection: sqlite3.Connection, *, owner_qq: str, owner_openid: str
) -> str:
    connection.row_factory = sqlite3.Row
    owner = connection.execute(
        """
        SELECT p.principal_id, p.role
        FROM external_identities e
        JOIN principals p ON p.principal_id=e.principal_id
        WHERE e.channel='qq' AND e.external_id=?
        """,
        (owner_qq,),
    ).fetchone()
    official = connection.execute(
        """
        SELECT p.principal_id, p.role
        FROM external_identities e
        JOIN principals p ON p.principal_id=e.principal_id
        WHERE e.channel='qq_official' AND e.external_id=?
        """,
        (owner_openid,),
    ).fetchone()
    if owner is None or official is None or owner["role"] != "owner":
        raise MigrationError("configured owner principal is unavailable")
    if owner["principal_id"] != official["principal_id"]:
        raise MigrationError("configured owner identities do not share one principal")
    return str(owner["principal_id"])


def _validate_database(
    path: Path, *, owner_qq: str, owner_openid: str, require_unmigrated: bool
) -> None:
    _safe_identity_database(path)
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise MigrationError("identity database integrity check failed")
        _owner_principal(connection, owner_qq=owner_qq, owner_openid=owner_openid)
        if require_unmigrated:
            present = connection.execute(
                """
                SELECT COUNT(*) FROM sqlite_master
                WHERE type='table' AND name IN (
                    'account_external_identities',
                    'configured_identity_accounts',
                    'identity_schema_meta'
                )
                """
            ).fetchone()[0]
            if present:
                raise MigrationError(
                    "identity schema v2 tables already exist while the gate is off"
                )


def _migrate_database(
    path: Path, *, owner_qq: str, owner_openid: str, bot_id: str
) -> None:
    _validate_database(
        path,
        owner_qq=owner_qq,
        owner_openid=owner_openid,
        require_unmigrated=True,
    )
    with sqlite3.connect(path) as connection:
        owner_principal = _owner_principal(
            connection, owner_qq=owner_qq, owner_openid=owner_openid
        )
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS account_external_identities (
                channel TEXT NOT NULL,
                account_id TEXT NOT NULL,
                external_id TEXT NOT NULL,
                principal_id TEXT NOT NULL REFERENCES principals(principal_id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(channel, account_id, external_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS configured_identity_accounts (
                channel TEXT NOT NULL,
                external_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(channel, external_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS identity_schema_meta (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                version INTEGER NOT NULL CHECK(version>=1)
            )
            """
        )
        existing_account = connection.execute(
            """
            SELECT account_id FROM configured_identity_accounts
            WHERE channel='qq_official' AND external_id=?
            """,
            (owner_openid,),
        ).fetchone()
        if existing_account is not None and existing_account[0] != bot_id:
            raise MigrationError(
                "configured owner identity is bound to another Bot account"
            )
        existing_scoped = connection.execute(
            """
            SELECT principal_id FROM account_external_identities
            WHERE channel='qq_official' AND account_id=? AND external_id=?
            """,
            (bot_id, owner_openid),
        ).fetchone()
        if existing_scoped is not None and existing_scoped[0] != owner_principal:
            raise MigrationError(
                "account-scoped owner identity conflicts with another principal"
            )
        connection.execute(
            """
            INSERT OR IGNORE INTO configured_identity_accounts(channel, external_id, account_id)
            VALUES ('qq_official', ?, ?)
            """,
            (owner_openid, bot_id),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO account_external_identities(
                channel, account_id, external_id, principal_id
            ) VALUES ('qq_official', ?, ?, ?)
            """,
            (bot_id, owner_openid, owner_principal),
        )
        connection.execute(
            """
            INSERT INTO identity_schema_meta(singleton, version) VALUES (1, 2)
            ON CONFLICT(singleton) DO UPDATE SET version=excluded.version
            """
        )
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise MigrationError("migrated identity database integrity check failed")


def prepare(
    *,
    agent_env: Path,
    sidecar_env: Path,
    session_state: Path,
    identity_path: Path,
    recycle_dir: Path,
    check_only: bool = False,
) -> None:
    agent_lines, agent = _read_env(agent_env)
    _, sidecar = _read_env(sidecar_env)
    if not _boolean(agent, "R_AGENT_OFFICIAL_QQ_ENABLED") or not _boolean(
        sidecar, "HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED"
    ):
        raise MigrationError("official owner transport must already be enabled")
    if not _boolean(agent, "R_AGENT_OFFICIAL_QQ_REPLY_ENABLED"):
        raise MigrationError("official owner passive replies must already be enabled")
    _validate_disabled_audiences(agent, sidecar)
    if _boolean(agent, "R_AGENT_IDENTITY_SCHEMA_V2_ENABLED"):
        raise MigrationError("identity schema v2 is already enabled")
    owner_qq = _safe_id(agent, "R_AGENT_OWNER_QQ")
    owner_openid = _safe_id(agent, "R_AGENT_OFFICIAL_QQ_OWNER_OPENID")
    if owner_openid != _safe_id(sidecar, "HIGGS_OFFICIAL_QQ_OWNER_OPENID"):
        raise MigrationError("owner identity bindings differ")
    bot_id = _session_bot_id(session_state)
    if check_only:
        _validate_database(
            identity_path,
            owner_qq=owner_qq,
            owner_openid=owner_openid,
            require_unmigrated=True,
        )
        return
    _migrate_database(
        identity_path,
        owner_qq=owner_qq,
        owner_openid=owner_openid,
        bot_id=bot_id,
    )
    _atomic_write(
        agent_env,
        _replace_key(agent_lines, "R_AGENT_IDENTITY_SCHEMA_V2_ENABLED", "true"),
        recycle_dir,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent-env", type=Path, required=True)
    parser.add_argument("--sidecar-env", type=Path, required=True)
    parser.add_argument("--session-state", type=Path, required=True)
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--recycle-dir", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    prepare(
        agent_env=args.agent_env,
        sidecar_env=args.sidecar_env,
        session_state=args.session_state,
        identity_path=args.identity,
        recycle_dir=args.recycle_dir,
        check_only=args.check_only,
    )
    print(
        "identity_v2_prepare=verified"
        if args.check_only
        else "identity_v2_migration=prepared"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
