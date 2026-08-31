"""Atomically prepare one governed official QQ audience for activation.

This helper changes only the two private environment files.  The caller must
first create a new backup directory under the host recycle area and must back
up ``identity.sqlite`` separately before rebuilding the Agent.  No identity or
fingerprint is printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
from pathlib import Path

SAFE_ID = re.compile(r"[!-~]{1,256}\Z")
APP_ID = re.compile(r"[0-9]{5,32}\Z")
FINGERPRINT = re.compile(r"[0-9a-f]{64}\Z")
NONCE = re.compile(r"[0-9a-f]{64}\Z")
TRUE = {"1", "true", "yes", "on"}
FALSE = {"0", "false", "no", "off"}


class ActivationError(ValueError):
    pass


def _safe_file(path: Path) -> None:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise ActivationError("private input is unavailable") from exc
    if path.is_symlink() or not path.is_file() or (os.name != "nt" and mode != 0o600):
        raise ActivationError("private input permissions are unsafe")


def _read_env(path: Path) -> tuple[list[str], dict[str, str]]:
    _safe_file(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ActivationError("private environment is unreadable") from exc
    values: dict[str, str] = {}
    for line in lines:
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in values:
            raise ActivationError("private environment contains duplicate keys")
        values[key] = value
    return lines, values


def _bool(values: dict[str, str], key: str, *, default: bool = False) -> bool:
    raw = values.get(key, "").strip().casefold()
    if not raw:
        return default
    if raw in TRUE:
        return True
    if raw in FALSE:
        return False
    raise ActivationError(f"{key} is not boolean")


def _ids(values: dict[str, str], key: str) -> list[str]:
    result = sorted({part.strip() for part in values.get(key, "").split(",") if part.strip()})
    if any(not SAFE_ID.fullmatch(value) or "*" in value for value in result):
        raise ActivationError(f"{key} contains an unsafe identity")
    return result


def _canonical_fingerprint(
    *, scope: str, app_id: str, bot_id: str, version: int, openids: list[str]
) -> str:
    payload = json.dumps(
        {
            "scope": scope,
            "app_id": app_id,
            "bot_id": bot_id,
            "allowlist_version": version,
            "openids": openids,
        },
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _read_allowlist(path: Path, scope: str) -> dict[str, object]:
    _safe_file(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ActivationError("allowlist is unreadable") from exc
    keys = {
        "version",
        "scope",
        "allowlist_version",
        "epoch_id",
        "nonce",
        "app_id",
        "bot_id",
        "frozen_at_ms",
        "previous_version",
        "previous_fingerprint",
        "fingerprint",
        "openids",
    }
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or value.get("version") != 2
        or value.get("scope") != scope
    ):
        raise ActivationError("allowlist is not governed v2")
    app_id = value.get("app_id")
    bot_id = value.get("bot_id")
    version = value.get("allowlist_version")
    openids = value.get("openids")
    fingerprint = value.get("fingerprint")
    if (
        not isinstance(app_id, str)
        or not APP_ID.fullmatch(app_id)
        or not isinstance(bot_id, str)
        or not SAFE_ID.fullmatch(bot_id)
        or "*" in bot_id
        or isinstance(version, bool)
        or not isinstance(version, int)
        or version < 1
        or not isinstance(openids, list)
        or not openids
        or len(openids) > 128
        or any(not isinstance(item, str) for item in openids)
        or openids != sorted(set(openids))
        or any(not SAFE_ID.fullmatch(item) or "*" in item for item in openids)
        or not isinstance(fingerprint, str)
        or not FINGERPRINT.fullmatch(fingerprint)
        or not isinstance(value.get("epoch_id"), str)
        or not SAFE_ID.fullmatch(value["epoch_id"])
        or not isinstance(value.get("nonce"), str)
        or not NONCE.fullmatch(value["nonce"])
    ):
        raise ActivationError("allowlist metadata is invalid")
    expected = _canonical_fingerprint(
        scope=scope,
        app_id=app_id,
        bot_id=bot_id,
        version=version,
        openids=openids,
    )
    if fingerprint != expected:
        raise ActivationError("allowlist fingerprint is invalid")
    previous_version = value.get("previous_version")
    previous_fingerprint = value.get("previous_fingerprint")
    if version == 1:
        if previous_version is not None or previous_fingerprint is not None:
            raise ActivationError("allowlist chain is invalid")
    elif (
        isinstance(previous_version, bool)
        or not isinstance(previous_version, int)
        or previous_version != version - 1
        or not isinstance(previous_fingerprint, str)
        or not FINGERPRINT.fullmatch(previous_fingerprint)
    ):
        raise ActivationError("allowlist chain is invalid")
    return value


def _metadata(values: dict[str, str], prefix: str) -> tuple[int, str]:
    version = values.get(f"{prefix}_VERSION", "").strip()
    fingerprint = values.get(f"{prefix}_FINGERPRINT", "").strip()
    if not version.isdigit() or int(version) < 1 or not FINGERPRINT.fullmatch(fingerprint):
        raise ActivationError("allowlist metadata is incomplete")
    return int(version), fingerprint


def _replace(lines: list[str], updates: dict[str, str]) -> str:
    output: list[str] = []
    remaining = dict(updates)
    for line in lines:
        if "=" in line and not line.startswith("#"):
            key = line.split("=", 1)[0]
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
                continue
        output.append(line)
    output.extend(f"{key}={value}" for key, value in remaining.items())
    return "\n".join(output) + "\n"


def _atomic_write(path: Path, content: str, failed_dir: Path) -> None:
    temporary = path.with_name(f".{path.name}.audience-activate-{os.getpid()}")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary.exists():
            os.replace(temporary, failed_dir / temporary.name)


def _restore(path: Path, backup: Path, failed_dir: Path) -> None:
    temporary = path.with_name(f".{path.name}.audience-rollback-{os.getpid()}")
    try:
        shutil.copy2(backup, temporary)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            os.replace(temporary, failed_dir / temporary.name)


def prepare(
    *,
    surface: str,
    agent_env: Path,
    sidecar_env: Path,
    allowlist_path: Path,
    backup_dir: Path,
) -> None:
    if surface not in {"private", "group"}:
        raise ActivationError("surface is invalid")
    if backup_dir.exists() or backup_dir.is_symlink():
        raise ActivationError("backup target already exists")
    agent_lines, agent = _read_env(agent_env)
    sidecar_lines, sidecar = _read_env(sidecar_env)
    allowlist = _read_allowlist(allowlist_path, surface)
    owner_agent = agent.get("R_AGENT_OFFICIAL_QQ_OWNER_OPENID", "").strip()
    owner_sidecar = sidecar.get("HIGGS_OFFICIAL_QQ_OWNER_OPENID", "").strip()
    if owner_agent != owner_sidecar or not SAFE_ID.fullmatch(owner_agent) or "*" in owner_agent:
        raise ActivationError("owner binding is unavailable")
    if not _bool(agent, "R_AGENT_OFFICIAL_QQ_ENABLED") or not _bool(
        agent, "R_AGENT_OFFICIAL_QQ_REPLY_ENABLED"
    ):
        raise ActivationError("owner passive reply baseline is unavailable")
    if not _bool(sidecar, "HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED") or _bool(
        sidecar, "HIGGS_OFFICIAL_QQ_CAPTURE_ONLY", default=True
    ):
        raise ActivationError("sidecar full-mode baseline is unavailable")
    if not _bool(agent, "R_AGENT_PERSONA_V2_ENABLED"):
        raise ActivationError("global Persona V2 is unavailable")
    closed_agent = (
        "R_AGENT_IDENTITY_SCHEMA_V2_ENABLED",
        "R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED",
        "R_AGENT_OFFICIAL_QQ_GROUP_ENABLED",
        "R_AGENT_PERSONA_V2_ORDINARY_PRIVATE_ENABLED",
        "R_AGENT_PERSONA_V2_GROUP_ENABLED",
    )
    closed_sidecar = (
        "HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED",
        "HIGGS_OFFICIAL_QQ_GROUP_ENABLED",
    )
    if any(_bool(agent, key) for key in closed_agent) or any(
        _bool(sidecar, key) for key in closed_sidecar
    ):
        raise ActivationError("audience activation baseline is not closed")

    if sidecar.get("QQBOT_APP_ID", "").strip() != allowlist["app_id"]:
        raise ActivationError("allowlist App binding differs")
    if surface == "private":
        agent_ids_key = "R_AGENT_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS"
        sidecar_ids_key = "HIGGS_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS"
        agent_meta = "R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST"
        sidecar_meta = "HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST"
        agent_channel = "R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED"
        sidecar_channel = "HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED"
        persona_channel = "R_AGENT_PERSONA_V2_ORDINARY_PRIVATE_ENABLED"
    else:
        agent_ids_key = "R_AGENT_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS"
        sidecar_ids_key = "HIGGS_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS"
        agent_meta = "R_AGENT_OFFICIAL_QQ_GROUP_ALLOWLIST"
        sidecar_meta = "HIGGS_OFFICIAL_QQ_GROUP_ALLOWLIST"
        agent_channel = "R_AGENT_OFFICIAL_QQ_GROUP_ENABLED"
        sidecar_channel = "HIGGS_OFFICIAL_QQ_GROUP_ENABLED"
        persona_channel = "R_AGENT_PERSONA_V2_GROUP_ENABLED"
    frozen_ids = allowlist["openids"]
    if _ids(agent, agent_ids_key) != frozen_ids or _ids(sidecar, sidecar_ids_key) != frozen_ids:
        raise ActivationError("allowlist identities differ")
    expected_metadata = (allowlist["allowlist_version"], allowlist["fingerprint"])
    if (
        _metadata(agent, agent_meta) != expected_metadata
        or _metadata(sidecar, sidecar_meta) != expected_metadata
    ):
        raise ActivationError("allowlist provenance differs")

    backup_dir.mkdir(mode=0o700, parents=True)
    agent_backup = backup_dir / "higgs.env"
    sidecar_backup = backup_dir / "official-qq.env"
    shutil.copy2(agent_env, agent_backup)
    shutil.copy2(sidecar_env, sidecar_backup)
    os.chmod(agent_backup, 0o600)
    os.chmod(sidecar_backup, 0o600)
    agent_updates = {
        "R_AGENT_IDENTITY_SCHEMA_V2_ENABLED": "true",
        agent_channel: "true",
        persona_channel: "true",
    }
    sidecar_updates = {sidecar_channel: "true"}
    try:
        _atomic_write(agent_env, _replace(agent_lines, agent_updates), backup_dir)
        _atomic_write(sidecar_env, _replace(sidecar_lines, sidecar_updates), backup_dir)
    except Exception:
        _restore(agent_env, agent_backup, backup_dir)
        _restore(sidecar_env, sidecar_backup, backup_dir)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--surface", choices=("private", "group"), required=True)
    parser.add_argument("--agent-env", required=True)
    parser.add_argument("--sidecar-env", required=True)
    parser.add_argument("--allowlist", required=True)
    parser.add_argument("--backup-dir", required=True)
    args = parser.parse_args()
    try:
        prepare(
            surface=args.surface,
            agent_env=Path(args.agent_env),
            sidecar_env=Path(args.sidecar_env),
            allowlist_path=Path(args.allowlist),
            backup_dir=Path(args.backup_dir),
        )
    except (ActivationError, OSError, UnicodeError, ValueError):
        print("audience_activation=failed")
        return 1
    print(f"audience_activation=prepared; surface={args.surface}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
