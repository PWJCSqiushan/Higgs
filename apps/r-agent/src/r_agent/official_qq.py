"""Fail-closed configuration scaffold for the official QQ Bot channel.

This is deliberately not a live network client yet.  It establishes the
credential and adapter boundary while keeping the current NapCat login
unchanged.  Enabling it before the gateway implementation exists produces an
explicit unavailable status instead of silently sending through another
channel.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from r_agent.config import ConfigError


def _bool_value(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError("R_AGENT_OFFICIAL_QQ_ENABLED must be a boolean")


@dataclass(frozen=True, slots=True)
class OfficialQQConfig:
    enabled: bool
    app_id: str | None
    client_secret: str | None
    sandbox: bool = True
    owner_openid: str | None = None
    allowed_group_openids: frozenset[str] = frozenset()

    def __repr__(self) -> str:
        return (
            "OfficialQQConfig("
            f"enabled={self.enabled!r}, app_id={self.app_id!r}, "
            f"client_secret={'<configured>' if self.client_secret else None!r}, "
            f"sandbox={self.sandbox!r}, "
            f"owner_openid={'<configured>' if self.owner_openid else None!r}, "
            f"allowed_group_count={len(self.allowed_group_openids)!r})"
        )

    @classmethod
    def from_env(cls) -> OfficialQQConfig:
        enabled = _bool_value(os.environ.get("R_AGENT_OFFICIAL_QQ_ENABLED"), default=False)
        app_id = os.environ.get("R_AGENT_OFFICIAL_QQ_APP_ID", "").strip() or None
        secret = os.environ.get("R_AGENT_OFFICIAL_QQ_CLIENT_SECRET", "").strip() or None
        sandbox = _bool_value(os.environ.get("R_AGENT_OFFICIAL_QQ_SANDBOX"), default=True)
        owner_openid = os.environ.get("R_AGENT_OFFICIAL_QQ_OWNER_OPENID", "").strip() or None
        groups = frozenset(
            item.strip()
            for item in os.environ.get("R_AGENT_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS", "").split(",")
            if item.strip()
        )
        if app_id is not None and (
            not app_id.isascii() or not app_id.isdigit() or not 5 <= len(app_id) <= 32
        ):
            raise ConfigError("R_AGENT_OFFICIAL_QQ_APP_ID must be 5-32 ASCII digits")
        if secret is not None and len(secret) < 16:
            raise ConfigError("R_AGENT_OFFICIAL_QQ_CLIENT_SECRET is too short")
        if enabled and (app_id is None or secret is None or owner_openid is None):
            raise ConfigError(
                "enabled official QQ requires AppID, ClientSecret, and explicit owner OpenID"
            )
        return cls(
            enabled=enabled,
            app_id=app_id,
            client_secret=secret,
            sandbox=sandbox,
            owner_openid=owner_openid,
            allowed_group_openids=groups,
        )


from r_agent.official_qq_gateway import OfficialQQAdapter  # noqa: E402

__all__ = ["OfficialQQAdapter", "OfficialQQConfig"]
