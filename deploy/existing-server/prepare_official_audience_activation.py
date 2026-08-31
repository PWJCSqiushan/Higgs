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
        or isinstance(value.get("frozen_at_ms"), bool)
        or not isinstance(value.get("frozen_at_ms"), int)
        or value["frozen_at_ms"] < 0
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


def _read_session_bot_id(path: Path) -> str:
    _safe_file(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ActivationError("official session state is unreadable") from exc
    bot_id = value.get("bot_id") if isinstance(value, dict) else None
    if not isinstance(bot_id, str) or not SAFE_ID.fullmatch(bot_id) or "*" in bot_id:
        raise ActivationError("official session Bot identity is unavailable")
    return bot_id


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
    try:
        content = backup.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ActivationError("private backup is unreadable") from exc
    _atomic_write(path, content, failed_dir)


def prepare(
    *,
    surface: str,
    agent_env: Path,
    sidecar_env: Path,
    allowlist_path: Path,
    other_allowlist_path: Path | None,
    backup_dir: Path,
    session_state_path: Path | None = None,
    check_only: bool = False,
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
    identity_schema_v2 = _bool(agent, "R_AGENT_IDENTITY_SCHEMA_V2_ENABLED")
    audience_state = {
        "private": (
            _bool(agent, "R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED"),
            _bool(sidecar, "HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED"),
            _bool(agent, "R_AGENT_PERSONA_V2_ORDINARY_PRIVATE_ENABLED"),
        ),
        "group": (
            _bool(agent, "R_AGENT_OFFICIAL_QQ_GROUP_ENABLED"),
            _bool(sidecar, "HIGGS_OFFICIAL_QQ_GROUP_ENABLED"),
            _bool(agent, "R_AGENT_PERSONA_V2_GROUP_ENABLED"),
        ),
    }
    for state in audience_state.values():
        if len(set(state)) != 1:
            raise ActivationError("audience and Persona gates differ")
    if any(state[0] for state in audience_state.values()) and not identity_schema_v2:
        raise ActivationError("active audience requires identity schema v2")
    if audience_state[surface][0]:
        raise ActivationError("selected audience is already active")

    current_bot_id = (
        _read_session_bot_id(session_state_path) if session_state_path is not None else None
    )
    other_surface = "group" if surface == "private" else "private"
    other_bot_id: str | None = None
    if audience_state[other_surface][0]:
        if other_allowlist_path is None:
            raise ActivationError("active audience allowlist is unavailable")
        other_allowlist = _read_allowlist(other_allowlist_path, other_surface)
        other_bot_id = str(other_allowlist["bot_id"])
        if sidecar.get("QQBOT_APP_ID", "").strip() != other_allowlist["app_id"]:
            raise ActivationError("active audience App binding differs")
        if other_surface == "private":
            other_agent_ids = "R_AGENT_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS"
            other_sidecar_ids = "HIGGS_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS"
            other_agent_meta = "R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST"
            other_sidecar_meta = "HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST"
        else:
            other_agent_ids = "R_AGENT_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS"
            other_sidecar_ids = "HIGGS_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS"
            other_agent_meta = "R_AGENT_OFFICIAL_QQ_GROUP_ALLOWLIST"
            other_sidecar_meta = "HIGGS_OFFICIAL_QQ_GROUP_ALLOWLIST"
        if (
            _ids(agent, other_agent_ids) != other_allowlist["openids"]
            or _ids(sidecar, other_sidecar_ids) != other_allowlist["openids"]
            or _metadata(agent, other_agent_meta)
            != (other_allowlist["allowlist_version"], other_allowlist["fingerprint"])
            or _metadata(sidecar, other_sidecar_meta)
            != (other_allowlist["allowlist_version"], other_allowlist["fingerprint"])
        ):
            raise ActivationError("active audience provenance differs")

    if sidecar.get("QQBOT_APP_ID", "").strip() != allowlist["app_id"]:
        raise ActivationError("allowlist App binding differs")
    if current_bot_id is not None and allowlist["bot_id"] != current_bot_id:
        raise ActivationError("allowlist Bot binding differs from the authenticated session")
    if other_bot_id is not None and allowlist["bot_id"] != other_bot_id:
        raise ActivationError("official audience Bot bindings differ")
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

    if surface == "group" and len(frozen_ids) != 1:
        raise ActivationError("first group activation requires exactly one group")
    if check_only:
        return

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
    parser.add_argument("--other-allowlist")
    parser.add_argument("--session-state", required=True)
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        prepare(
            surface=args.surface,
            agent_env=Path(args.agent_env),
            sidecar_env=Path(args.sidecar_env),
            allowlist_path=Path(args.allowlist),
            other_allowlist_path=(Path(args.other_allowlist) if args.other_allowlist else None),
            backup_dir=Path(args.backup_dir),
            session_state_path=Path(args.session_state),
            check_only=args.check_only,
        )
    except (ActivationError, OSError, UnicodeError, ValueError):
        print("audience_activation=failed")
        return 1
    print(f"audience_activation=prepared; surface={args.surface}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
