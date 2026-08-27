"""Fail-closed persistence for official QQ Gateway Resume state."""

from __future__ import annotations

import json
import os
import stat
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_MAX_FILE_BYTES = 64 * 1024
_MAX_SESSION_AGE_SECONDS = 3600.0


class OfficialQQSessionError(RuntimeError):
    """The private official QQ session store cannot be trusted."""


@dataclass(frozen=True, slots=True)
class PersistedOfficialQQSession:
    session_id: str = ""
    seq: int | None = None
    last_active: str = ""
    account_id: str | None = None

    @property
    def is_resumable(self) -> bool:
        return bool(self.session_id) and self.seq is not None

    def is_fresh(self, max_age_seconds: float = _MAX_SESSION_AGE_SECONDS) -> bool:
        if not self.last_active:
            return False
        try:
            timestamp = datetime.fromisoformat(self.last_active)
        except (TypeError, ValueError):
            return False
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        age = (datetime.now(UTC) - timestamp.astimezone(UTC)).total_seconds()
        return 0 <= age < max_age_seconds


class SecureOfficialQQSessionStore:
    """Persist only Resume state in an atomic, owner-readable JSON file.

    The upstream SDK store is intentionally not used here because its default
    file permissions follow the process umask. Gateway session IDs are login
    state and therefore receive the same private-file treatment as credentials.
    """

    def __init__(self, base_dir: str | Path, filename: str = "official_qq_sessions.json") -> None:
        if Path(filename).name != filename or not filename.endswith(".json"):
            raise OfficialQQSessionError("official QQ session filename is invalid")
        self._path = Path(base_dir) / filename
        self._lock = threading.RLock()
        self._data = self._load()

    @staticmethod
    def _validate_app_id(app_id: str) -> str:
        if not app_id.isascii() or not app_id.isdigit() or not 5 <= len(app_id) <= 32:
            raise OfficialQQSessionError("official QQ session AppID is invalid")
        return app_id

    @staticmethod
    def _validate_session_id(session_id: str) -> str:
        value = str(session_id).strip()
        if not value or len(value) > 512 or any(char in value for char in "\r\n\0"):
            raise OfficialQQSessionError("official QQ session ID is invalid")
        return value

    @staticmethod
    def _validate_account_id(account_id: object) -> str:
        value = str(account_id or "").strip()
        if (
            not value
            or len(value) > 256
            or not value.isascii()
            or any(char.isspace() or ord(char) < 33 for char in value)
        ):
            raise OfficialQQSessionError("official QQ bot account ID is invalid")
        return value

    @staticmethod
    def _validate_seq(seq: int | None) -> int | None:
        if seq is None:
            return None
        if isinstance(seq, bool) or not isinstance(seq, int) or not 0 <= seq < 2**63:
            raise OfficialQQSessionError("official QQ session sequence is invalid")
        return seq

    @staticmethod
    def _validate_last_active(value: object) -> str:
        text = str(value or "")
        if not text or len(text) > 64:
            raise OfficialQQSessionError("official QQ session timestamp is invalid")
        try:
            datetime.fromisoformat(text)
        except ValueError as exc:
            raise OfficialQQSessionError("official QQ session timestamp is invalid") from exc
        return text

    def _enforce_private_mode(self) -> None:
        if os.name != "posix":
            return
        mode = stat.S_IMODE(self._path.stat().st_mode)
        if mode != 0o600:
            os.chmod(self._path, 0o600)
        if stat.S_IMODE(self._path.stat().st_mode) != 0o600:
            raise OfficialQQSessionError("official QQ session file is not private")

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        if self._path.is_symlink() or not self._path.is_file():
            raise OfficialQQSessionError("official QQ session path is unsafe")
        try:
            if self._path.stat().st_size > _MAX_FILE_BYTES:
                raise OfficialQQSessionError("official QQ session file is too large")
            self._enforce_private_mode()
            value = json.loads(self._path.read_text(encoding="utf-8"))
        except OfficialQQSessionError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OfficialQQSessionError("official QQ session file is unreadable") from exc
        if not isinstance(value, dict):
            raise OfficialQQSessionError("official QQ session file has invalid structure")
        return value

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.tmp")
        payload = json.dumps(self._data, ensure_ascii=True, separators=(",", ":"))
        if len(payload.encode("utf-8")) > _MAX_FILE_BYTES:
            raise OfficialQQSessionError("official QQ session file is too large")
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(temporary, flags, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
            self._enforce_private_mode()
        except OSError as exc:
            raise OfficialQQSessionError("official QQ session file could not be saved") from exc

    def get(self, app_id: str) -> PersistedOfficialQQSession:
        key = self._validate_app_id(app_id)
        with self._lock:
            raw = self._data.get(key)
            if raw is None:
                return PersistedOfficialQQSession()
            if not isinstance(raw, dict):
                raise OfficialQQSessionError("official QQ session record is invalid")
            session_id = self._validate_session_id(raw.get("session_id", ""))
            seq = self._validate_seq(raw.get("seq"))
            last_active = self._validate_last_active(raw.get("last_active"))
            account_id = (
                self._validate_account_id(raw["account_id"])
                if raw.get("account_id") is not None
                else None
            )
            return PersistedOfficialQQSession(session_id, seq, last_active, account_id)

    def save(
        self,
        app_id: str,
        session: str,
        seq: int | None = None,
        intents: int = 0,
        bot_username: str = "",
    ) -> None:
        del intents, bot_username
        key = self._validate_app_id(app_id)
        record = {
            "session_id": self._validate_session_id(session),
            "seq": self._validate_seq(seq),
            "last_active": datetime.now(UTC).isoformat(),
        }
        with self._lock:
            existing = self._data.get(key)
            if isinstance(existing, dict) and existing.get("account_id") is not None:
                record["account_id"] = self._validate_account_id(existing["account_id"])
            self._data[key] = record
            self._save()

    def get_account_id(self, app_id: str) -> str | None:
        return self.get(app_id).account_id

    def set_account_id(self, app_id: str, account_id: str) -> None:
        key = self._validate_app_id(app_id)
        value = self._validate_account_id(account_id)
        with self._lock:
            record = self._data.get(key)
            if not isinstance(record, dict):
                raise OfficialQQSessionError("official QQ session record is missing")
            record["account_id"] = value
            self._save()

    def clear(self, app_id: str) -> None:
        key = self._validate_app_id(app_id)
        with self._lock:
            if key in self._data:
                del self._data[key]
                self._save()

    def touch(self, app_id: str) -> None:
        key = self._validate_app_id(app_id)
        with self._lock:
            if key in self._data:
                self._data[key]["last_active"] = datetime.now(UTC).isoformat()
                self._save()


__all__ = [
    "OfficialQQSessionError",
    "PersistedOfficialQQSession",
    "SecureOfficialQQSessionStore",
]
