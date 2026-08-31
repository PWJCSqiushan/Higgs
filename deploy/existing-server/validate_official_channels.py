"""Validate the Python Agent and Node sidecar official-channel contract.

The validator reads only private environment files and reports field names,
never credentials or OpenID values.  It is intended for deployment preflight;
it does not enable either channel.
"""

from __future__ import annotations

import argparse
import re
import stat
from pathlib import Path

_SAFE_ID = re.compile(r"[!-~]{1,256}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_BOOL_TRUE = {"1", "true", "yes", "on"}
_BOOL_FALSE = {"0", "false", "no", "off"}


class ContractError(ValueError):
    pass


def _read_env(path: Path) -> dict[str, str]:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise ContractError("private environment is unavailable") from exc
    if path.is_symlink() or not path.is_file() or mode != 0o600:
        raise ContractError("private environment permissions are unsafe")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in values:
            raise ContractError("duplicate private environment key")
        values[key] = value
    return values


def _bool(values: dict[str, str], key: str, *, default: bool = False) -> bool:
    value = values.get(key)
    if value is None or not value.strip():
        return default
    normalized = value.strip().casefold()
    if normalized in _BOOL_TRUE:
        return True
    if normalized in _BOOL_FALSE:
        return False
    raise ContractError(f"{key} is not boolean")


def _ids(values: dict[str, str], key: str) -> frozenset[str]:
    raw = values.get(key, "")
    result = set()
    for value in raw.split(","):
        value = value.strip()
        if not value:
            continue
        if not _SAFE_ID.fullmatch(value) or "*" in value:
            raise ContractError(f"{key} contains an unsafe identity")
        result.add(value)
    return frozenset(result)


def _int(values: dict[str, str], key: str, minimum: int, maximum: int, default: int) -> int:
    raw = values.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ContractError(f"{key} is not an integer") from exc
    if not minimum <= value <= maximum:
        raise ContractError(f"{key} is outside its safety bounds")
    return value


def _optional_version(values: dict[str, str], key: str) -> int | None:
    raw = values.get(key, "").strip()
    if not raw:
        return None
    return _int(values, key, 1, 2**31 - 1, 1)


def _optional_fingerprint(values: dict[str, str], key: str) -> str | None:
    raw = values.get(key, "").strip()
    if not raw:
        return None
    if not _SHA256.fullmatch(raw):
        raise ContractError(f"{key} is not a lowercase SHA-256 fingerprint")
    return raw


def validate(agent: dict[str, str], sidecar: dict[str, str], *, release: bool) -> None:
    agent_enabled = _bool(agent, "R_AGENT_OFFICIAL_QQ_ENABLED")
    sidecar_enabled = _bool(sidecar, "HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED")
    if agent_enabled != sidecar_enabled:
        raise ContractError("official enabled switches differ")

    agent_owner = agent.get("R_AGENT_OFFICIAL_QQ_OWNER_OPENID", "").strip()
    side_owner = sidecar.get("HIGGS_OFFICIAL_QQ_OWNER_OPENID", "").strip()
    if agent_owner != side_owner:
        raise ContractError("owner identity bindings differ")
    if agent_owner and (not _SAFE_ID.fullmatch(agent_owner) or "*" in agent_owner):
        raise ContractError("owner identity binding is unsafe")

    ordinary_agent = _bool(agent, "R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED")
    ordinary_sidecar = _bool(sidecar, "HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED")
    if ordinary_agent != ordinary_sidecar:
        raise ContractError("ordinary private switches differ")
    group_agent = _bool(agent, "R_AGENT_OFFICIAL_QQ_GROUP_ENABLED")
    group_sidecar = _bool(sidecar, "HIGGS_OFFICIAL_QQ_GROUP_ENABLED")
    if group_agent != group_sidecar:
        raise ContractError("group switches differ")

    private_agent = set(_ids(agent, "R_AGENT_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS"))
    private_sidecar = set(_ids(sidecar, "HIGGS_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS"))
    if agent_owner:
        private_agent.add(agent_owner)
        private_sidecar.add(agent_owner)
    if private_agent != private_sidecar:
        raise ContractError("private allowlists differ")

    private_version_agent = _optional_version(
        agent, "R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_VERSION"
    )
    private_version_sidecar = _optional_version(
        sidecar, "HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_VERSION"
    )
    private_fingerprint_agent = _optional_fingerprint(
        agent, "R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FINGERPRINT"
    )
    private_fingerprint_sidecar = _optional_fingerprint(
        sidecar, "HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FINGERPRINT"
    )
    if (private_version_agent is None) != (private_fingerprint_agent is None):
        raise ContractError("Agent private allowlist metadata is incomplete")
    if (private_version_sidecar is None) != (private_fingerprint_sidecar is None):
        raise ContractError("sidecar private allowlist metadata is incomplete")
    if (
        private_version_agent != private_version_sidecar
        or private_fingerprint_agent != private_fingerprint_sidecar
    ):
        raise ContractError("private allowlist metadata differs")
    if ordinary_agent and private_version_agent is None:
        raise ContractError("ordinary private channel requires versioned allowlist metadata")

    groups_agent = _ids(agent, "R_AGENT_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS")
    groups_sidecar = _ids(sidecar, "HIGGS_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS")
    if groups_agent != groups_sidecar:
        raise ContractError("group allowlists differ")

    identity_schema_v2 = _bool(agent, "R_AGENT_IDENTITY_SCHEMA_V2_ENABLED")
    if (ordinary_agent or group_agent) and not identity_schema_v2:
        raise ContractError("ordinary official audiences require identity schema v2")
    if _bool(agent, "R_AGENT_PERSONA_V2_ORDINARY_PRIVATE_ENABLED") and not ordinary_agent:
        raise ContractError("ordinary Persona V2 requires the ordinary private channel")
    if _bool(agent, "R_AGENT_PERSONA_V2_GROUP_ENABLED") and not group_agent:
        raise ContractError("group Persona V2 requires the official group channel")

    for agent_key, sidecar_key, minimum, maximum, default in (
        (
            "R_AGENT_OFFICIAL_QQ_PRIVATE_RATE_PER_MINUTE",
            "HIGGS_OFFICIAL_QQ_PRIVATE_RATE_PER_MINUTE",
            1,
            120,
            30,
        ),
        (
            "R_AGENT_OFFICIAL_QQ_GROUP_RATE_PER_MINUTE",
            "HIGGS_OFFICIAL_QQ_GROUP_RATE_PER_MINUTE",
            1,
            240,
            60,
        ),
        (
            "R_AGENT_OFFICIAL_QQ_PRIVATE_CIRCUIT_FAILURE_LIMIT",
            "HIGGS_OFFICIAL_QQ_PRIVATE_CIRCUIT_FAILURE_LIMIT",
            1,
            20,
            5,
        ),
        (
            "R_AGENT_OFFICIAL_QQ_GROUP_CIRCUIT_FAILURE_LIMIT",
            "HIGGS_OFFICIAL_QQ_GROUP_CIRCUIT_FAILURE_LIMIT",
            1,
            20,
            5,
        ),
        (
            "R_AGENT_OFFICIAL_QQ_PRIVATE_CIRCUIT_COOLDOWN_SECONDS",
            "HIGGS_OFFICIAL_QQ_PRIVATE_CIRCUIT_COOLDOWN_SECONDS",
            1,
            3600,
            300,
        ),
        (
            "R_AGENT_OFFICIAL_QQ_GROUP_CIRCUIT_COOLDOWN_SECONDS",
            "HIGGS_OFFICIAL_QQ_GROUP_CIRCUIT_COOLDOWN_SECONDS",
            1,
            3600,
            300,
        ),
    ):
        if _int(agent, agent_key, minimum, maximum, default) != _int(
            sidecar, sidecar_key, minimum, maximum, default
        ):
            raise ContractError(f"{agent_key} and {sidecar_key} differ")

    proactive_agent = _bool(agent, "R_AGENT_OFFICIAL_QQ_PROACTIVE_ENABLED")
    proactive_sidecar = _bool(sidecar, "HIGGS_OFFICIAL_QQ_PROACTIVE_ENABLED")
    if proactive_agent != proactive_sidecar:
        raise ContractError("proactive switches differ")
    if proactive_agent and not _bool(agent, "R_AGENT_OFFICIAL_QQ_REPLY_ENABLED"):
        raise ContractError("proactive replies are not enabled")
    if _bool(agent, "R_AGENT_OFFICIAL_QQ_REPLY_ENABLED") and (
        not agent_enabled or not sidecar_enabled
    ):
        raise ContractError("passive replies require both official transports")

    capture_only = _bool(sidecar, "HIGGS_OFFICIAL_QQ_CAPTURE_ONLY", default=True)
    if release:
        if not agent_enabled or not sidecar_enabled:
            raise ContractError("release requires enabled official transports")
        if capture_only:
            raise ContractError("release forbids capture-only sidecar")
        if not _bool(agent, "R_AGENT_OFFICIAL_QQ_REPLY_ENABLED"):
            raise ContractError("release requires passive replies")
    if ordinary_agent and capture_only:
        raise ContractError("ordinary private channel cannot run in capture-only mode")
    if agent_enabled and not agent_owner:
        raise ContractError("enabled official transport requires an owner binding")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent-env", default="/srv/secrets/higgs/higgs.env")
    parser.add_argument("--sidecar-env", default="/srv/secrets/higgs/official-qq.env")
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()
    try:
        validate(
            _read_env(Path(args.agent_env)),
            _read_env(Path(args.sidecar_env)),
            release=args.release,
        )
    except (ContractError, OSError, UnicodeError) as exc:
        print(f"official-contract=failed; reason={exc}")
        return 1
    print(f"official-contract=passed; release={str(args.release).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
