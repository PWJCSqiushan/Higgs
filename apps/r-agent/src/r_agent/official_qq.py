"""Fail-closed configuration for the isolated official QQ Bot transport.

Production uses the durable Node sidecar over a private Unix Socket; the
pinned Python SDK adapter remains an isolated compatibility path.  Neither
transport can silently fall back to NapCat or receive credentials belonging to
the other process.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from r_agent.config import ConfigError

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _bool_value(
    value: str | None,
    *,
    default: bool,
    name: str = "R_AGENT_OFFICIAL_QQ_ENABLED",
) -> bool:
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean")


def _safe_openid(value: str, *, name: str) -> str:
    """Normalize one bot-scoped OpenID without accepting a wildcard."""

    clean = value.strip()
    if (
        not 1 <= len(clean) <= 256
        or not clean.isascii()
        or "*" in clean
        or any(ord(char) < 33 or ord(char) > 126 for char in clean)
    ):
        raise ConfigError(f"{name} must contain printable ASCII OpenIDs")
    return clean


def _openid_set(value: str | None, *, name: str) -> frozenset[str]:
    if value is None or not value.strip():
        return frozenset()
    return frozenset(_safe_openid(item, name=name) for item in value.split(",") if item.strip())


def _bounded_int(
    value: str | None,
    *,
    default: int,
    minimum: int,
    maximum: int,
    name: str,
) -> int:
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _optional_allowlist_version(value: str | None, *, name: str) -> int | None:
    if value is None or not value.strip():
        return None
    return _bounded_int(value, default=1, minimum=1, maximum=2**31 - 1, name=name)


def _optional_allowlist_fingerprint(value: str | None, *, name: str) -> str | None:
    if value is None or not value.strip():
        return None
    clean = value.strip()
    if not _SHA256.fullmatch(clean):
        raise ConfigError(f"{name} must be a lowercase SHA-256 fingerprint")
    return clean


@dataclass(frozen=True, slots=True)
class OfficialQQConfig:
    enabled: bool
    app_id: str | None
    client_secret: str | None
    sandbox: bool = True
    owner_openid: str | None = None
    allowed_group_openids: frozenset[str] = frozenset()
    allowed_private_openids: frozenset[str] = frozenset()
    transport: str = "sdk"
    sidecar_socket_path: str = "/run/higgs-official/sidecar.sock"
    reply_enabled: bool = False
    proactive_enabled: bool = False
    ordinary_private_enabled: bool = False
    group_enabled: bool = False
    private_rate_per_minute: int = 30
    group_rate_per_minute: int = 60
    private_circuit_failure_limit: int = 5
    group_circuit_failure_limit: int = 5
    private_circuit_cooldown_seconds: int = 300
    group_circuit_cooldown_seconds: int = 300
    private_allowlist_version: int | None = None
    private_allowlist_fingerprint: str | None = None
    group_allowlist_version: int | None = None
    group_allowlist_fingerprint: str | None = None

    def __post_init__(self) -> None:
        owner_openid = (
            None
            if self.owner_openid is None or not self.owner_openid.strip()
            else _safe_openid(self.owner_openid, name="owner_openid")
        )
        private_openids = {
            _safe_openid(value, name="allowed_private_openids")
            for value in self.allowed_private_openids
        }
        if owner_openid is not None:
            # The owner is always part of the private policy.  Keeping this
            # union in the parsed config makes Python and Node fail closed on
            # the same bot-scoped identity set.
            private_openids.add(owner_openid)
        group_openids = {
            _safe_openid(value, name="allowed_group_openids")
            for value in self.allowed_group_openids
        }
        object.__setattr__(self, "owner_openid", owner_openid)
        object.__setattr__(self, "allowed_private_openids", frozenset(private_openids))
        object.__setattr__(self, "allowed_group_openids", frozenset(group_openids))
        for name in ("ordinary_private_enabled", "group_enabled"):
            if not isinstance(getattr(self, name), bool):
                raise ConfigError(f"{name} must be a boolean")
        if not self.enabled and (self.ordinary_private_enabled or self.group_enabled):
            raise ConfigError("official channel switches require an enabled transport")
        if (self.private_allowlist_version is None) != (self.private_allowlist_fingerprint is None):
            raise ConfigError(
                "private allowlist version and fingerprint must be configured together"
            )
        if self.ordinary_private_enabled and self.private_allowlist_version is None:
            raise ConfigError("ordinary private channel requires versioned allowlist metadata")
        if (self.group_allowlist_version is None) != (self.group_allowlist_fingerprint is None):
            raise ConfigError("group allowlist version and fingerprint must be configured together")
        if self.group_enabled and self.group_allowlist_version is None:
            raise ConfigError("group channel requires versioned allowlist metadata")
        for name, minimum, maximum in (
            ("private_rate_per_minute", 1, 120),
            ("group_rate_per_minute", 1, 240),
            ("private_circuit_failure_limit", 1, 20),
            ("group_circuit_failure_limit", 1, 20),
            ("private_circuit_cooldown_seconds", 1, 3600),
            ("group_circuit_cooldown_seconds", 1, 3600),
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not minimum <= value <= maximum
            ):
                raise ConfigError(f"{name} must be between {minimum} and {maximum}")
        if self.reply_enabled and (not self.enabled or self.transport != "sidecar"):
            raise ConfigError("official QQ replies require the enabled durable sidecar transport")
        if self.proactive_enabled and not self.reply_enabled:
            raise ConfigError("official QQ proactive sends require passive replies to be enabled")
        if self.enabled and self.transport == "sidecar" and self.owner_openid is None:
            raise ConfigError("enabled official QQ requires an explicit owner OpenID")
        if self.transport == "sidecar" and (
            self.app_id is not None or self.client_secret is not None
        ):
            raise ConfigError("sidecar official QQ forbids App credentials in the Agent process")

    @property
    def active_owner_openid(self) -> str | None:
        return self.owner_openid if self.enabled else None

    @property
    def active_private_openids(self) -> frozenset[str]:
        if not self.enabled:
            return frozenset()
        if self.ordinary_private_enabled:
            return self.allowed_private_openids
        return frozenset({self.owner_openid}) if self.owner_openid else frozenset()

    @property
    def private_enabled(self) -> bool:
        """Compatibility alias for callers that named the ordinary gate private."""

        return self.ordinary_private_enabled

    @property
    def active_group_openids(self) -> frozenset[str]:
        return self.allowed_group_openids if self.enabled and self.group_enabled else frozenset()

    @property
    def active_private_allowlist_version(self) -> int | None:
        return self.private_allowlist_version if self.ordinary_private_enabled else None

    @property
    def active_private_allowlist_fingerprint(self) -> str | None:
        return self.private_allowlist_fingerprint if self.ordinary_private_enabled else None

    @property
    def active_group_allowlist_version(self) -> int | None:
        return self.group_allowlist_version if self.group_enabled else None

    @property
    def active_group_allowlist_fingerprint(self) -> str | None:
        return self.group_allowlist_fingerprint if self.group_enabled else None

    def __repr__(self) -> str:
        return (
            "OfficialQQConfig("
            f"enabled={self.enabled!r}, app_id={self.app_id!r}, "
            f"client_secret={'<configured>' if self.client_secret else None!r}, "
            f"sandbox={self.sandbox!r}, "
            f"owner_openid={'<configured>' if self.owner_openid else None!r}, "
            f"allowed_private_count={len(self.allowed_private_openids)!r}, "
            f"allowed_group_count={len(self.allowed_group_openids)!r}, "
            f"transport={self.transport!r}, "
            f"sidecar_socket_path={self.sidecar_socket_path!r}, "
            f"reply_enabled={self.reply_enabled!r}, "
            f"proactive_enabled={self.proactive_enabled!r}, "
            f"ordinary_private_enabled={self.ordinary_private_enabled!r}, "
            f"group_enabled={self.group_enabled!r})"
        )

    @classmethod
    def from_env(cls) -> OfficialQQConfig:
        enabled = _bool_value(
            os.environ.get("R_AGENT_OFFICIAL_QQ_ENABLED"),
            default=False,
            name="R_AGENT_OFFICIAL_QQ_ENABLED",
        )
        app_id = os.environ.get("R_AGENT_OFFICIAL_QQ_APP_ID", "").strip() or None
        secret = os.environ.get("R_AGENT_OFFICIAL_QQ_CLIENT_SECRET", "").strip() or None
        sandbox = _bool_value(
            os.environ.get("R_AGENT_OFFICIAL_QQ_SANDBOX"),
            default=True,
            name="R_AGENT_OFFICIAL_QQ_SANDBOX",
        )
        owner_raw = os.environ.get("R_AGENT_OFFICIAL_QQ_OWNER_OPENID", "").strip()
        owner_openid = (
            _safe_openid(owner_raw, name="R_AGENT_OFFICIAL_QQ_OWNER_OPENID") if owner_raw else None
        )
        transport = os.environ.get("R_AGENT_OFFICIAL_QQ_TRANSPORT", "sdk").strip().casefold()
        socket_path = os.environ.get(
            "R_AGENT_OFFICIAL_QQ_SIDECAR_SOCKET",
            "/run/higgs-official/sidecar.sock",
        ).strip()
        reply_enabled = _bool_value(
            os.environ.get("R_AGENT_OFFICIAL_QQ_REPLY_ENABLED"),
            default=False,
            name="R_AGENT_OFFICIAL_QQ_REPLY_ENABLED",
        )
        proactive_enabled = _bool_value(
            os.environ.get("R_AGENT_OFFICIAL_QQ_PROACTIVE_ENABLED"),
            default=False,
            name="R_AGENT_OFFICIAL_QQ_PROACTIVE_ENABLED",
        )
        ordinary_private_enabled = _bool_value(
            os.environ.get("R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED"),
            default=False,
            name="R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED",
        )
        group_enabled = _bool_value(
            os.environ.get("R_AGENT_OFFICIAL_QQ_GROUP_ENABLED"),
            default=False,
            name="R_AGENT_OFFICIAL_QQ_GROUP_ENABLED",
        )
        groups = _openid_set(
            os.environ.get("R_AGENT_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS"),
            name="R_AGENT_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS",
        )
        private_openids = _openid_set(
            os.environ.get("R_AGENT_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS"),
            name="R_AGENT_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS",
        )
        private_allowlist_version = _optional_allowlist_version(
            os.environ.get("R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_VERSION"),
            name="R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_VERSION",
        )
        private_allowlist_fingerprint = _optional_allowlist_fingerprint(
            os.environ.get("R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FINGERPRINT"),
            name="R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FINGERPRINT",
        )
        group_allowlist_version = _optional_allowlist_version(
            os.environ.get("R_AGENT_OFFICIAL_QQ_GROUP_ALLOWLIST_VERSION"),
            name="R_AGENT_OFFICIAL_QQ_GROUP_ALLOWLIST_VERSION",
        )
        group_allowlist_fingerprint = _optional_allowlist_fingerprint(
            os.environ.get("R_AGENT_OFFICIAL_QQ_GROUP_ALLOWLIST_FINGERPRINT"),
            name="R_AGENT_OFFICIAL_QQ_GROUP_ALLOWLIST_FINGERPRINT",
        )
        if app_id is not None and (
            not app_id.isascii() or not app_id.isdigit() or not 5 <= len(app_id) <= 32
        ):
            raise ConfigError("R_AGENT_OFFICIAL_QQ_APP_ID must be 5-32 ASCII digits")
        if secret is not None and len(secret) < 16:
            raise ConfigError("R_AGENT_OFFICIAL_QQ_CLIENT_SECRET is too short")
        if transport not in {"sdk", "sidecar"}:
            raise ConfigError("R_AGENT_OFFICIAL_QQ_TRANSPORT must be sdk or sidecar")
        socket = PurePosixPath(socket_path)
        if (
            not socket_path
            or len(socket_path) > 240
            or not socket.is_absolute()
            or ".." in socket.parts
            or socket.name != "sidecar.sock"
        ):
            raise ConfigError("R_AGENT_OFFICIAL_QQ_SIDECAR_SOCKET must be an absolute socket path")
        if (
            enabled
            and transport == "sdk"
            and (app_id is None or secret is None or owner_openid is None)
        ):
            raise ConfigError(
                "enabled official QQ requires AppID, ClientSecret, and explicit owner OpenID"
            )
        if enabled and transport == "sidecar" and owner_openid is None:
            raise ConfigError("enabled official QQ requires an explicit owner OpenID")
        if transport == "sidecar" and (app_id is not None or secret is not None):
            raise ConfigError("sidecar official QQ forbids App credentials in the Agent process")
        if reply_enabled and not enabled:
            raise ConfigError("official QQ replies require the official transport to be enabled")
        if reply_enabled and transport != "sidecar":
            raise ConfigError("official QQ replies require the durable sidecar transport")
        if proactive_enabled and not reply_enabled:
            raise ConfigError("official QQ proactive sends require passive replies to be enabled")
        return cls(
            enabled=enabled,
            app_id=app_id,
            client_secret=secret,
            sandbox=sandbox,
            owner_openid=owner_openid,
            allowed_group_openids=groups,
            allowed_private_openids=private_openids,
            transport=transport,
            sidecar_socket_path=socket_path,
            reply_enabled=reply_enabled,
            proactive_enabled=proactive_enabled,
            ordinary_private_enabled=ordinary_private_enabled,
            group_enabled=group_enabled,
            private_rate_per_minute=_bounded_int(
                os.environ.get("R_AGENT_OFFICIAL_QQ_PRIVATE_RATE_PER_MINUTE"),
                default=30,
                minimum=1,
                maximum=120,
                name="R_AGENT_OFFICIAL_QQ_PRIVATE_RATE_PER_MINUTE",
            ),
            group_rate_per_minute=_bounded_int(
                os.environ.get("R_AGENT_OFFICIAL_QQ_GROUP_RATE_PER_MINUTE"),
                default=60,
                minimum=1,
                maximum=240,
                name="R_AGENT_OFFICIAL_QQ_GROUP_RATE_PER_MINUTE",
            ),
            private_circuit_failure_limit=_bounded_int(
                os.environ.get("R_AGENT_OFFICIAL_QQ_PRIVATE_CIRCUIT_FAILURE_LIMIT"),
                default=5,
                minimum=1,
                maximum=20,
                name="R_AGENT_OFFICIAL_QQ_PRIVATE_CIRCUIT_FAILURE_LIMIT",
            ),
            group_circuit_failure_limit=_bounded_int(
                os.environ.get("R_AGENT_OFFICIAL_QQ_GROUP_CIRCUIT_FAILURE_LIMIT"),
                default=5,
                minimum=1,
                maximum=20,
                name="R_AGENT_OFFICIAL_QQ_GROUP_CIRCUIT_FAILURE_LIMIT",
            ),
            private_circuit_cooldown_seconds=_bounded_int(
                os.environ.get("R_AGENT_OFFICIAL_QQ_PRIVATE_CIRCUIT_COOLDOWN_SECONDS"),
                default=300,
                minimum=1,
                maximum=3600,
                name="R_AGENT_OFFICIAL_QQ_PRIVATE_CIRCUIT_COOLDOWN_SECONDS",
            ),
            group_circuit_cooldown_seconds=_bounded_int(
                os.environ.get("R_AGENT_OFFICIAL_QQ_GROUP_CIRCUIT_COOLDOWN_SECONDS"),
                default=300,
                minimum=1,
                maximum=3600,
                name="R_AGENT_OFFICIAL_QQ_GROUP_CIRCUIT_COOLDOWN_SECONDS",
            ),
            private_allowlist_version=private_allowlist_version,
            private_allowlist_fingerprint=private_allowlist_fingerprint,
            group_allowlist_version=group_allowlist_version,
            group_allowlist_fingerprint=group_allowlist_fingerprint,
        )


from r_agent.official_qq_gateway import OfficialQQAdapter  # noqa: E402
from r_agent.official_qq_sidecar import OfficialQQSidecarAdapter  # noqa: E402

__all__ = ["OfficialQQAdapter", "OfficialQQConfig", "OfficialQQSidecarAdapter"]
