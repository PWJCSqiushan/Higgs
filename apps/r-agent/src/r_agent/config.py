"""Environment-only configuration with fail-closed defaults."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class ConfigError(ValueError):
    """Raised when configuration would weaken a runtime invariant."""


def load_env_file(path: Path) -> None:
    """Load a minimal KEY=VALUE file without overriding process env."""
    if not path.exists():
        return
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key.startswith("R_AGENT_") or not key.replace("_", "").isalnum():
            raise ConfigError(f"{path}:{line_number}: invalid R_AGENT_ key")
        os.environ.setdefault(key, value.strip())


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean")


def _qq(value: str | None, *, name: str) -> str | None:
    if value is None or not value.strip():
        return None
    clean = value.strip()
    if not clean.isascii() or not clean.isdigit() or not 5 <= len(clean) <= 12:
        raise ConfigError(f"{name} must contain 5-12 ASCII digits")
    return clean


def parse_qq_set(value: str | None, *, name: str) -> frozenset[str]:
    if value is None or not value.strip():
        return frozenset()
    parsed: set[str] = set()
    for part in value.split(","):
        item = _qq(part, name=name)
        if item is not None:
            parsed.add(item)
    return frozenset(parsed)


@dataclass(frozen=True, slots=True)
class Settings:
    shadow_mode: bool
    ingest_enabled: bool
    data_dir: Path
    onebot_ws_url: str
    onebot_access_token: str | None
    owner_qq: str | None
    allowed_private_qqs: frozenset[str]
    allowed_groups: frozenset[str]
    journal_retention_days: int

    @classmethod
    def from_env(
        cls,
        *,
        env_file: Path | None = None,
        require_shadow: bool = True,
    ) -> Settings:
        if env_file is not None:
            load_env_file(env_file)
        shadow_mode = _bool_env("R_AGENT_SHADOW_MODE", True)
        if require_shadow and not shadow_mode:
            raise ConfigError("Phase 1 only supports read-only shadow mode")

        ws_url = os.environ.get("R_AGENT_ONEBOT_WS_URL", "ws://127.0.0.1:3001").strip()
        token = os.environ.get("R_AGENT_ONEBOT_ACCESS_TOKEN")
        token = token.strip() if token and token.strip() else None
        trusted_host = os.environ.get("R_AGENT_ONEBOT_TRUSTED_HOST", "").strip().casefold()
        if trusted_host and (
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", trusted_host) is None
            or trusted_host in {"localhost", "127", "0"}
        ):
            raise ConfigError("R_AGENT_ONEBOT_TRUSTED_HOST must be one exact DNS label")
        parsed_ws_url = urlsplit(ws_url)
        loopback_hosts = {"127.0.0.1", "localhost", "::1"}
        endpoint_host = (parsed_ws_url.hostname or "").casefold()
        trusted_container_endpoint = bool(trusted_host and endpoint_host == trusted_host)
        if (
            parsed_ws_url.scheme not in {"ws", "wss"}
            or (endpoint_host not in loopback_hosts and not trusted_container_endpoint)
            or parsed_ws_url.username is not None
            or parsed_ws_url.password is not None
            or parsed_ws_url.query
            or parsed_ws_url.fragment
            or parsed_ws_url.path not in {"", "/"}
        ):
            raise ConfigError(
                "OneBot WebSocket must use loopback or the explicitly trusted internal host"
            )
        if trusted_container_endpoint and (token is None or len(token) < 32):
            raise ConfigError("trusted internal OneBot requires an access token of 32+ characters")

        retention_raw = os.environ.get("R_AGENT_JOURNAL_RETENTION_DAYS", "7").strip()
        try:
            retention = int(retention_raw)
        except ValueError as exc:
            raise ConfigError("R_AGENT_JOURNAL_RETENTION_DAYS must be an integer") from exc
        if not 1 <= retention <= 30:
            raise ConfigError("journal retention must be between 1 and 30 days")

        return cls(
            shadow_mode=shadow_mode,
            ingest_enabled=_bool_env("R_AGENT_INGEST_ENABLED", True),
            data_dir=Path(os.environ.get("R_AGENT_DATA_DIR", "./data")).resolve(),
            onebot_ws_url=ws_url,
            onebot_access_token=token,
            owner_qq=_qq(os.environ.get("R_AGENT_OWNER_QQ"), name="R_AGENT_OWNER_QQ"),
            allowed_private_qqs=parse_qq_set(
                os.environ.get("R_AGENT_ALLOWED_PRIVATE_QQS"),
                name="R_AGENT_ALLOWED_PRIVATE_QQS",
            ),
            allowed_groups=parse_qq_set(
                os.environ.get("R_AGENT_ALLOWED_GROUPS"),
                name="R_AGENT_ALLOWED_GROUPS",
            ),
            journal_retention_days=retention,
        )
