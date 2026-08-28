"""One-shot, fail-closed owner OpenID capture for the official QQ sandbox.

The normal Agent must stay disabled while this helper runs.  It accepts only
the first authoritative C2C sender observed after READY/RESUMED, writes no
message content, and atomically binds the sender to the private environment
file before stopping the temporary Gateway session.
"""

from __future__ import annotations

import asyncio
import os
import re
import stat
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from r_agent.official_qq import OfficialQQConfig
from r_agent.official_qq_gateway import (
    ApiClient,
    GatewayFactory,
    OfficialQQAdapter,
    Parser,
    SessionStore,
)

APP_ID_KEY = "R_AGENT_OFFICIAL_QQ_APP_ID"
SECRET_KEY = "R_AGENT_OFFICIAL_QQ_CLIENT_SECRET"  # pragma: allowlist secret
OWNER_KEY = "R_AGENT_OFFICIAL_QQ_OWNER_OPENID"
ENABLED_KEY = "R_AGENT_OFFICIAL_QQ_ENABLED"
SANDBOX_KEY = "R_AGENT_OFFICIAL_QQ_SANDBOX"
MAX_ENV_BYTES = 256 * 1024
_KEY_RE = re.compile(r"R_AGENT_[A-Z0-9_]+\Z")


class OwnerCaptureError(RuntimeError):
    """Raised when capture or private binding cannot remain fail closed."""


class OwnerCaptureTimeout(OwnerCaptureError):
    """Raised when no eligible C2C event arrives inside the operator window."""


def _safe_openid(value: str) -> str:
    clean = value.strip()
    if (
        not clean
        or len(clean) > 256
        or not clean.isascii()
        or any(char.isspace() or ord(char) < 33 for char in clean)
    ):
        raise OwnerCaptureError("captured owner identity is invalid")
    return clean


def _bool_value(value: str | None, *, default: bool, name: str) -> bool:
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise OwnerCaptureError(f"{name} must be a boolean")


@dataclass(frozen=True, slots=True)
class CaptureCredentials:
    app_id: str
    client_secret: str

    def __repr__(self) -> str:
        return "CaptureCredentials(app_id='<configured>', client_secret='<configured>')"


class SecureOwnerBinding:
    """Read and atomically update one root-only Higgs environment file."""

    def __init__(self, env_path: str | Path, *, backup_dir: str | Path) -> None:
        self.env_path = Path(env_path)
        self.backup_dir = Path(backup_dir)

    def _read(self) -> tuple[bytes, os.stat_result, list[str], dict[str, list[str]]]:
        try:
            info = self.env_path.lstat()
        except OSError as exc:
            raise OwnerCaptureError("private environment file is unavailable") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise OwnerCaptureError("private environment file must be one regular file")
        if info.st_size > MAX_ENV_BYTES:
            raise OwnerCaptureError("private environment file is too large")
        if os.name == "posix" and stat.S_IMODE(info.st_mode) != 0o600:
            raise OwnerCaptureError("private environment file must use mode 0600")
        try:
            payload = self.env_path.read_bytes()
            text = payload.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise OwnerCaptureError("private environment file cannot be read safely") from exc

        values: dict[str, list[str]] = {}
        lines = text.splitlines()
        for line_number, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise OwnerCaptureError(f"private environment line {line_number} is malformed")
            key, value = line.split("=", 1)
            key = key.strip()
            if _KEY_RE.fullmatch(key) is None:
                raise OwnerCaptureError(
                    f"private environment line {line_number} has an invalid key"
                )
            values.setdefault(key, []).append(value.strip())
        return payload, info, lines, values

    @staticmethod
    def _single(values: dict[str, list[str]], key: str) -> str | None:
        found = values.get(key, [])
        if len(found) > 1:
            raise OwnerCaptureError(f"{key} must appear at most once")
        return found[0] if found else None

    def credentials(self) -> CaptureCredentials:
        _, _, _, values = self._read()
        app_id = self._single(values, APP_ID_KEY)
        secret = self._single(values, SECRET_KEY)
        owner = self._single(values, OWNER_KEY)
        enabled = _bool_value(self._single(values, ENABLED_KEY), default=False, name=ENABLED_KEY)
        sandbox = _bool_value(self._single(values, SANDBOX_KEY), default=True, name=SANDBOX_KEY)
        if enabled:
            raise OwnerCaptureError("official QQ must remain disabled during capture")
        if not sandbox:
            raise OwnerCaptureError("owner capture is restricted to the official sandbox")
        if owner:
            raise OwnerCaptureError("official owner identity is already configured")
        if (
            app_id is None
            or not app_id.isascii()
            or not app_id.isdigit()
            or not 5 <= len(app_id) <= 32
        ):
            raise OwnerCaptureError("official AppID is missing or invalid")
        if secret is None or len(secret) < 16:
            raise OwnerCaptureError("official ClientSecret is missing or invalid")
        return CaptureCredentials(app_id, secret)

    def _prepare_backup_dir(self) -> None:
        if self.backup_dir.exists():
            info = self.backup_dir.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise OwnerCaptureError("owner capture backup directory is unsafe")
            if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
                raise OwnerCaptureError("owner capture backup directory is not private")
            return
        self.backup_dir.mkdir(parents=True, mode=0o700)
        if os.name == "posix":
            os.chmod(self.backup_dir, 0o700)

    @staticmethod
    def _sync_directory(path: Path) -> None:
        if os.name != "posix":
            return
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def bind(self, owner_openid: str) -> None:
        clean_openid = _safe_openid(owner_openid)
        original, info, lines, values = self._read()
        # Repeat all preconditions immediately before constructing the write.
        self.credentials()
        if self._single(values, OWNER_KEY) is not None:
            raise OwnerCaptureError("official owner identity is already configured")
        self._prepare_backup_dir()

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        backup = self.backup_dir / f"{self.env_path.name}.before-owner-capture-{stamp}"
        try:
            with backup.open("xb") as handle:
                handle.write(original)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(backup, 0o600)
            chown = getattr(os, "chown", None)
            if chown is not None:
                chown(backup, info.st_uid, info.st_gid)
            self._sync_directory(self.backup_dir)
        except OSError as exc:
            raise OwnerCaptureError("private environment backup failed") from exc

        updated_lines = [*lines, f"{OWNER_KEY}={clean_openid}"]
        updated = ("\n".join(updated_lines) + "\n").encode("utf-8")
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=self.env_path.parent, prefix=".official-owner.", delete=False
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(updated)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_path, 0o600)
            chown = getattr(os, "chown", None)
            if chown is not None:
                chown(temporary_path, info.st_uid, info.st_gid)
            if self.env_path.read_bytes() != original:
                raise OwnerCaptureError("private environment changed during capture")
            os.replace(temporary_path, self.env_path)
            temporary_path = None
            self._sync_directory(self.env_path.parent)
        except OwnerCaptureError:
            raise
        except OSError as exc:
            raise OwnerCaptureError("private owner binding failed") from exc
        finally:
            if temporary_path is not None and temporary_path.exists():
                abandoned = self.backup_dir / f"{temporary_path.name}.abandoned-{stamp}"
                try:
                    os.replace(temporary_path, abandoned)
                    os.chmod(abandoned, 0o600)
                except OSError:
                    # Preserve the failed temporary rather than unlinking it.
                    pass

        # Re-read without returning the identity and prove the main adapter is
        # still disabled and exactly one owner binding now exists.
        _, final_info, _, final_values = self._read()
        if os.name == "posix" and stat.S_IMODE(final_info.st_mode) != 0o600:
            raise OwnerCaptureError("private environment permissions changed")
        if _bool_value(self._single(final_values, ENABLED_KEY), default=False, name=ENABLED_KEY):
            raise OwnerCaptureError("official QQ was unexpectedly enabled")
        owners = final_values.get(OWNER_KEY, [])
        if len(owners) != 1 or owners[0] != clean_openid:
            raise OwnerCaptureError("private owner binding verification failed")


CaptureHandler = Callable[[str], Awaitable[None]]


class _OwnerCaptureAdapter(OfficialQQAdapter):
    """Official adapter variant that never creates an inbound conversation."""

    def __init__(self, *args: Any, capture_handler: CaptureHandler, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._capture_handler = capture_handler
        self._capture_claimed = False

    async def _on_message_event(self, event_type: str, raw: dict[str, Any]) -> None:
        if event_type != "C2C_MESSAGE_CREATE" or self._parser is None:
            return
        try:
            parsed = self._parser(event_type, raw)
        except Exception:
            return
        if parsed is None or str(getattr(parsed, "chat_scope", "")) != "c2c":
            return
        sender_id = str(getattr(parsed, "user_id", "") or "")
        chat_id = str(getattr(parsed, "chat_id", "") or "")
        try:
            sender_id = _safe_openid(sender_id)
        except OwnerCaptureError:
            return
        if chat_id != sender_id:
            return
        with self._lock:
            if (
                self._capture_claimed
                or not self._connected
                or not self._authenticated
                or self._account_id is None
            ):
                return
            self._capture_claimed = True
            self._last_event_at_ms = self._clock_ms()
        await self._capture_handler(sender_id)


class OfficialQQOwnerCapture:
    """Run one bounded official Gateway session and bind the first C2C sender."""

    def __init__(
        self,
        binding: SecureOwnerBinding,
        *,
        data_dir: str | Path,
        api_client: ApiClient | None = None,
        gateway_factory: GatewayFactory | None = None,
        session_store: SessionStore | None = None,
        parser: Parser | None = None,
    ) -> None:
        self.binding = binding
        self.data_dir = Path(data_dir)
        self.api_client = api_client
        self.gateway_factory = gateway_factory
        self.session_store = session_store
        self.parser = parser

    async def run(self, *, timeout_seconds: float = 300.0) -> None:
        if not 10 <= timeout_seconds <= 900:
            raise ValueError("capture timeout must be between 10 and 900 seconds")
        credentials = self.binding.credentials()
        finished = asyncio.Event()
        failure: list[Exception] = []

        async def capture(sender_id: str) -> None:
            try:
                await asyncio.to_thread(self.binding.bind, sender_id)
            except Exception as exc:
                failure.append(exc)
            finally:
                finished.set()

        adapter = _OwnerCaptureAdapter(
            OfficialQQConfig(
                enabled=True,
                app_id=credentials.app_id,
                client_secret=credentials.client_secret,
                sandbox=True,
                # The capture adapter overrides message gating and never uses
                # this sentinel as a principal or outbound target.
                owner_openid="capture-pending",
            ),
            capture_handler=capture,
            data_dir=self.data_dir,
            api_client=self.api_client,
            gateway_factory=self.gateway_factory,
            session_store=self.session_store,
            parser=self.parser,
        )
        try:
            await adapter.start()
            try:
                await asyncio.wait_for(finished.wait(), timeout=timeout_seconds)
            except TimeoutError as exc:
                raise OwnerCaptureTimeout("no eligible official C2C event arrived") from exc
        finally:
            await adapter.stop()
        if failure:
            raise OwnerCaptureError("private owner binding failed") from failure[0]


__all__ = [
    "CaptureCredentials",
    "OfficialQQOwnerCapture",
    "OwnerCaptureError",
    "OwnerCaptureTimeout",
    "SecureOwnerBinding",
]
