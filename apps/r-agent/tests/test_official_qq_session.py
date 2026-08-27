from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from r_agent.official_qq_session import (
    OfficialQQSessionError,
    SecureOfficialQQSessionStore,
)


def test_secure_store_round_trip_and_atomic_private_file(tmp_path: Path) -> None:
    store = SecureOfficialQQSessionStore(tmp_path)
    store.save("123456", "session-id", 42, intents=7, bot_username="not-persisted")
    store.set_account_id("123456", "bot-account-id")

    path = tmp_path / "official_qq_sessions.json"
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["123456"]["session_id"] == "session-id"
    assert persisted["123456"]["seq"] == 42
    assert persisted["123456"]["account_id"] == "bot-account-id"
    assert "intents" not in persisted["123456"]
    assert "bot_username" not in persisted["123456"]
    assert not (tmp_path / ".official_qq_sessions.json.tmp").exists()
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    loaded = SecureOfficialQQSessionStore(tmp_path).get("123456")
    assert loaded.session_id == "session-id"
    assert loaded.seq == 42
    assert loaded.account_id == "bot-account-id"
    assert loaded.is_resumable is True
    assert loaded.is_fresh() is True


def test_secure_store_repairs_overbroad_posix_mode(tmp_path: Path) -> None:
    path = tmp_path / "official_qq_sessions.json"
    path.write_text(
        json.dumps(
            {
                "123456": {
                    "session_id": "session-id",
                    "seq": 1,
                    "last_active": datetime.now(UTC).isoformat(),
                }
            }
        ),
        encoding="utf-8",
    )
    if os.name == "posix":
        path.chmod(0o644)

    assert SecureOfficialQQSessionStore(tmp_path).get("123456").is_resumable is True
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_secure_store_rejects_corrupt_or_unsafe_state_without_echo(tmp_path: Path) -> None:
    secret_marker = "do-not-echo-this-session"
    path = tmp_path / "official_qq_sessions.json"
    path.write_text(f'{{"secret":"{secret_marker}"', encoding="utf-8")

    with pytest.raises(OfficialQQSessionError) as captured:
        SecureOfficialQQSessionStore(tmp_path)

    assert secret_marker not in str(captured.value)


def test_secure_store_rejects_invalid_record_and_stale_session(tmp_path: Path) -> None:
    path = tmp_path / "official_qq_sessions.json"
    stale = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    path.write_text(
        json.dumps({"123456": {"session_id": "session-id", "seq": 1, "last_active": stale}}),
        encoding="utf-8",
    )
    store = SecureOfficialQQSessionStore(tmp_path)
    assert store.get("123456").is_fresh() is False

    with pytest.raises(OfficialQQSessionError, match="sequence"):
        store.save("123456", "session-id", True)
    with pytest.raises(OfficialQQSessionError, match="session ID"):
        store.save("123456", "line\nbreak", 2)


def test_secure_store_touch_and_clear_preserve_private_container(tmp_path: Path) -> None:
    store = SecureOfficialQQSessionStore(tmp_path)
    store.save("123456", "session-id", 1)
    store.set_account_id("123456", "bot-account-id")
    store.save("123456", "replacement-session", 2)
    assert store.get_account_id("123456") == "bot-account-id"
    previous = store.get("123456").last_active
    store.touch("123456")
    assert store.get("123456").last_active >= previous

    store.clear("123456")
    assert store.get("123456").is_resumable is False
    assert (tmp_path / "official_qq_sessions.json").exists()
