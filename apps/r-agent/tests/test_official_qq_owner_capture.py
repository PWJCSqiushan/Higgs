from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from r_agent.official_qq_owner_capture import (
    OfficialQQOwnerCapture,
    OwnerCaptureError,
    OwnerCaptureTimeout,
    SecureOwnerBinding,
)
from r_agent.official_qq_owner_capture_cli import main


def _write_env(path: Path, *, enabled: str = "false", owner: str | None = None) -> None:
    lines = [
        "R_AGENT_OFFICIAL_QQ_APP_ID=123456",
        "R_AGENT_OFFICIAL_QQ_CLIENT_SECRET=a-secure-test-client-secret",
        f"R_AGENT_OFFICIAL_QQ_ENABLED={enabled}",
        "R_AGENT_OFFICIAL_QQ_SANDBOX=true",
        "R_AGENT_MODE=live",
    ]
    if owner is not None:
        lines.append(f"R_AGENT_OFFICIAL_QQ_OWNER_OPENID={owner}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


class FakeApi:
    def setup(self, _http_client: Any) -> None:
        return None

    def ensure_token_sync(self) -> str:
        return "token"

    def get_gateway_url_sync(self) -> str:
        return "wss://gateway.invalid"

    def clear_token(self) -> None:
        return None


class FakeGateway:
    def __init__(self, callbacks: Any):
        self.callbacks = callbacks
        self.started = False
        self.stopped = False

    def start(self, _gateway_url: str, _main_loop: Any) -> None:
        self.started = True

    async def async_stop(self) -> None:
        self.stopped = True


@dataclass
class FakePersistedSession:
    session_id: str = ""
    seq: int | None = None

    @property
    def is_resumable(self) -> bool:
        return bool(self.session_id) and self.seq is not None

    def is_fresh(self) -> bool:
        return True


class FakeSessionStore:
    def __init__(self) -> None:
        self.session = FakePersistedSession()
        self.account_id: str | None = None

    def get(self, _app_id: str) -> FakePersistedSession:
        return self.session

    def save(
        self,
        _app_id: str,
        session: str,
        seq: int | None = None,
        intents: int = 0,
        bot_username: str = "",
    ) -> None:
        del intents, bot_username
        self.session = FakePersistedSession(session, seq)

    def clear(self, _app_id: str) -> None:
        self.session = FakePersistedSession()
        self.account_id = None

    def touch(self, _app_id: str) -> None:
        return None

    def get_account_id(self, _app_id: str) -> str | None:
        return self.account_id

    def set_account_id(self, _app_id: str, account_id: str) -> None:
        self.account_id = account_id


def test_credentials_repr_and_errors_do_not_expose_secret(tmp_path: Path) -> None:
    env_path = tmp_path / "higgs.env"
    _write_env(env_path)
    binding = SecureOwnerBinding(env_path, backup_dir=tmp_path / "backups")

    credentials = binding.credentials()

    assert credentials.app_id == "123456"
    assert "a-secure-test-client-secret" not in repr(credentials)
    assert "<configured>" in repr(credentials)


@pytest.mark.parametrize("enabled", ["true", "1", "yes", "on"])
def test_capture_refuses_enabled_official_adapter(tmp_path: Path, enabled: str) -> None:
    env_path = tmp_path / "higgs.env"
    _write_env(env_path, enabled=enabled)

    with pytest.raises(OwnerCaptureError, match="disabled"):
        SecureOwnerBinding(env_path, backup_dir=tmp_path / "backups").credentials()


def test_capture_refuses_existing_owner_and_duplicate_credentials(tmp_path: Path) -> None:
    env_path = tmp_path / "higgs.env"
    _write_env(env_path, owner="existing-owner")
    binding = SecureOwnerBinding(env_path, backup_dir=tmp_path / "backups")
    with pytest.raises(OwnerCaptureError, match="already configured"):
        binding.credentials()

    _write_env(env_path)
    with env_path.open("a", encoding="utf-8") as handle:
        handle.write("R_AGENT_OFFICIAL_QQ_APP_ID=654321\n")
    with pytest.raises(OwnerCaptureError, match="at most once"):
        binding.credentials()


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink and mode contract")
def test_capture_rejects_symlink_and_non_private_mode(tmp_path: Path) -> None:
    actual = tmp_path / "actual.env"
    _write_env(actual)
    linked = tmp_path / "linked.env"
    linked.symlink_to(actual)
    with pytest.raises(OwnerCaptureError, match="regular file"):
        SecureOwnerBinding(linked, backup_dir=tmp_path / "backups").credentials()

    os.chmod(actual, 0o644)
    with pytest.raises(OwnerCaptureError, match="0600"):
        SecureOwnerBinding(actual, backup_dir=tmp_path / "backups").credentials()


def test_atomic_binding_preserves_disabled_state_and_creates_private_backup(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / "higgs.env"
    backup_dir = tmp_path / "backups"
    _write_env(env_path)
    original = env_path.read_bytes()
    binding = SecureOwnerBinding(env_path, backup_dir=backup_dir)

    binding.bind("captured-owner-openid")

    final = env_path.read_text(encoding="utf-8")
    assert "R_AGENT_OFFICIAL_QQ_ENABLED=false" in final
    assert final.count("R_AGENT_OFFICIAL_QQ_OWNER_OPENID=") == 1
    expected_binding = (
        "R_AGENT_OFFICIAL_QQ_OWNER_OPENID=captured-owner-openid"  # pragma: allowlist secret
    )
    assert expected_binding in final
    backups = list(backup_dir.iterdir())
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
    if os.name == "posix":
        assert env_path.stat().st_mode & 0o777 == 0o600
        assert backup_dir.stat().st_mode & 0o777 == 0o700
        assert backups[0].stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_fake_gateway_captures_only_first_ready_c2c_without_content_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    env_path = tmp_path / "higgs.env"
    _write_env(env_path)
    gateway: FakeGateway | None = None
    gateway_ready = asyncio.Event()
    parsed: Any = None

    def gateway_factory(callbacks: Any) -> FakeGateway:
        nonlocal gateway
        gateway = FakeGateway(callbacks)
        gateway_ready.set()
        return gateway

    capture = OfficialQQOwnerCapture(
        SecureOwnerBinding(env_path, backup_dir=tmp_path / "backups"),
        data_dir=tmp_path,
        api_client=FakeApi(),  # type: ignore[arg-type]
        gateway_factory=gateway_factory,
        session_store=FakeSessionStore(),
        parser=lambda _event_type, _raw: parsed,
    )
    task = asyncio.create_task(capture.run(timeout_seconds=10))
    await asyncio.wait_for(gateway_ready.wait(), timeout=2)
    assert gateway is not None

    parsed = SimpleNamespace(
        chat_scope="c2c",
        user_id="ignored-before-ready",
        chat_id="ignored-before-ready",
        content="DO_NOT_LOG_MESSAGE_BODY",
    )
    await gateway.callbacks.on_message_event("C2C_MESSAGE_CREATE", {})
    gateway.callbacks.on_connected()
    gateway.callbacks.on_ready(SimpleNamespace(user=SimpleNamespace(id="bot-openid")))

    parsed = SimpleNamespace(
        chat_scope="group",
        user_id="ignored-group-member",
        chat_id="group-openid",
        content="DO_NOT_LOG_GROUP_BODY",
    )
    await gateway.callbacks.on_message_event("GROUP_AT_MESSAGE_CREATE", {})

    parsed = SimpleNamespace(
        chat_scope="c2c",
        user_id="captured-owner-openid",
        chat_id="captured-owner-openid",
        content="DO_NOT_LOG_OWNER_BODY",
    )
    with caplog.at_level(logging.DEBUG):
        await gateway.callbacks.on_message_event("C2C_MESSAGE_CREATE", {})
    parsed = SimpleNamespace(
        chat_scope="c2c",
        user_id="second-test-user-openid",
        chat_id="second-test-user-openid",
        content="DO_NOT_LOG_SECOND_BODY",
    )
    await gateway.callbacks.on_message_event("C2C_MESSAGE_CREATE", {})
    await task

    assert gateway.stopped is True
    final = env_path.read_text(encoding="utf-8")
    expected_binding = (
        "R_AGENT_OFFICIAL_QQ_OWNER_OPENID=captured-owner-openid"  # pragma: allowlist secret
    )
    assert expected_binding in final
    assert "second-test-user-openid" not in final
    rendered_logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "DO_NOT_LOG" not in rendered_logs
    assert "captured-owner-openid" not in rendered_logs


@pytest.mark.asyncio
async def test_capture_timeout_stops_gateway_without_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_path = tmp_path / "higgs.env"
    _write_env(env_path)
    gateway: FakeGateway | None = None

    def gateway_factory(callbacks: Any) -> FakeGateway:
        nonlocal gateway
        gateway = FakeGateway(callbacks)
        return gateway

    capture = OfficialQQOwnerCapture(
        SecureOwnerBinding(env_path, backup_dir=tmp_path / "backups"),
        data_dir=tmp_path,
        api_client=FakeApi(),  # type: ignore[arg-type]
        gateway_factory=gateway_factory,
        session_store=FakeSessionStore(),
        parser=lambda _event_type, _raw: None,
    )

    async def immediate_timeout(awaitable: Any, *, timeout: float) -> None:
        del timeout
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", immediate_timeout)
    with pytest.raises(OwnerCaptureTimeout):
        await capture.run(timeout_seconds=10)
    assert gateway is not None and gateway.stopped is True
    assert "R_AGENT_OFFICIAL_QQ_OWNER_OPENID" not in env_path.read_text(encoding="utf-8")


def test_cli_requires_exact_single_test_user_confirmation(tmp_path: Path, capsys: Any) -> None:
    result = main(
        [
            "--env-file",
            str(tmp_path / "missing.env"),
            "--confirm-single-test-user",
            "not-confirmed",
        ]
    )

    assert result == 2
    output = capsys.readouterr().out
    assert "confirmation_mismatch" in output
