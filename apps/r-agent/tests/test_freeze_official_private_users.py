from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "deploy"
    / "existing-server"
    / "freeze_official_private_users.py"
)
SPEC = importlib.util.spec_from_file_location("freeze_official_private_users", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
FREEZE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FREEZE)


def _write_private(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8", newline="\n")
    path.chmod(0o600)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path, str]:
    app_id = "123456789"
    bot_id = "bot-id"
    member = "member-openid"
    epoch_id = "epoch-id"
    nonce = "a" * 64
    fingerprint = FREEZE._canonical_fingerprint(
        app_id=app_id,
        bot_id=bot_id,
        allowlist_version=1,
        openids=[member],
    )
    allowlist = {
        "version": 2,
        "scope": "private",
        "allowlist_version": 1,
        "epoch_id": epoch_id,
        "nonce": nonce,
        "app_id": app_id,
        "bot_id": bot_id,
        "frozen_at_ms": 2_000,
        "previous_version": None,
        "previous_fingerprint": None,
        "fingerprint": fingerprint,
        "openids": [member],
    }
    capture = {
        "version": 2,
        "scope": "private",
        "status": "frozen",
        "epoch_id": epoch_id,
        "nonce": nonce,
        "app_id": app_id,
        "bot_id": bot_id,
        "window_started_at_ms": 1_000,
        "window_deadline_at_ms": 1_900,
        "max_candidates": 1,
        "candidates": [member],
        "baseline_allowlist_version": None,
        "baseline_allowlist_fingerprint": None,
        "frozen_allowlist_version": 1,
        "frozen_allowlist_fingerprint": fingerprint,
        "history": [],
    }
    higgs = tmp_path / "higgs.env"
    sidecar = tmp_path / "official-qq.env"
    capture_path = tmp_path / "private-users-capture.json"
    allowlist_path = tmp_path / "allowed-private-openids.json"
    backup = tmp_path / "backup"
    _write_private(
        higgs,
        "\n".join(
            (
                "R_AGENT_OFFICIAL_QQ_ENABLED=true",
                "R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=false",
                "R_AGENT_OFFICIAL_QQ_GROUP_ENABLED=false",
                "R_AGENT_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS=",
                "",
            )
        ),
    )
    _write_private(
        sidecar,
        "\n".join(
            (
                "HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED=true",
                "HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=false",
                "HIGGS_OFFICIAL_QQ_GROUP_ENABLED=false",
                "HIGGS_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS=",
                f"QQBOT_APP_ID={app_id}",
                "",
            )
        ),
    )
    _write_private(capture_path, json.dumps(capture, separators=(",", ":")) + "\n")
    _write_private(allowlist_path, json.dumps(allowlist, separators=(",", ":")) + "\n")
    return higgs, sidecar, capture_path, allowlist_path, backup, member


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    paths: tuple[Path, Path, Path, Path, Path, str],
) -> None:
    higgs, sidecar, capture, allowlist, backup, _ = paths
    monkeypatch.setenv("HIGGS_ENV_FILE", os.fspath(higgs))
    monkeypatch.setenv("SIDE_ENV_FILE", os.fspath(sidecar))
    monkeypatch.setenv("CAPTURE_FILE", os.fspath(capture))
    monkeypatch.setenv("ALLOWLIST_FILE", os.fspath(allowlist))
    monkeypatch.setenv("BACKUP_DIR", os.fspath(backup))
    monkeypatch.setenv("EXPECTED_COUNT", "1")
    monkeypatch.setenv("PREVIOUS_ALLOWLIST_FILE", "")
    monkeypatch.setattr(FREEZE.os, "chown", lambda *_args: None, raising=False)
    monkeypatch.setattr(FREEZE.os, "fchmod", lambda *_args: None, raising=False)
    monkeypatch.setattr(FREEZE.os, "fsync", lambda *_args: None)
    real_open = FREEZE.os.open

    def portable_open(path: object, flags: int, mode: int = 0o777) -> int:
        candidate = Path(path) if isinstance(path, (str, os.PathLike)) else None
        if candidate is not None and candidate.is_dir():
            return real_open(os.devnull, flags)
        return real_open(path, flags, mode)

    monkeypatch.setattr(FREEZE.os, "open", portable_open)


def test_freeze_prepares_versioned_policy_while_owner_transport_stays_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _fixture(tmp_path)
    _configure(monkeypatch, paths)
    higgs, sidecar, _, _, backup, member = paths

    assert FREEZE.main() == 0

    higgs_text = higgs.read_text(encoding="utf-8")
    sidecar_text = sidecar.read_text(encoding="utf-8")
    assert "R_AGENT_OFFICIAL_QQ_ENABLED=true" in higgs_text
    assert "HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED=true" in sidecar_text
    assert f"R_AGENT_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS={member}" in higgs_text
    assert f"HIGGS_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS={member}" in sidecar_text
    assert "R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=false" in higgs_text
    assert "HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=false" in sidecar_text
    assert (backup / "higgs.env").is_file()
    assert (backup / "official-qq.env").is_file()


def test_freeze_rejects_missing_metadata_for_an_incremental_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _fixture(tmp_path)
    _configure(monkeypatch, paths)
    higgs, sidecar, capture_path, allowlist_path, _, _ = paths
    previous_path = tmp_path / "previous.json"
    previous = json.loads(allowlist_path.read_text(encoding="utf-8"))
    previous_path.write_text(json.dumps(previous), encoding="utf-8")
    previous_path.chmod(0o600)
    previous_fingerprint = previous["fingerprint"]
    member_two = "second-member"
    next_openids = sorted([previous["openids"][0], member_two])
    next_fingerprint = FREEZE._canonical_fingerprint(
        app_id=previous["app_id"],
        bot_id=previous["bot_id"],
        allowlist_version=2,
        openids=next_openids,
    )
    current = dict(previous)
    current.update(
        {
            "allowlist_version": 2,
            "previous_version": 1,
            "previous_fingerprint": previous_fingerprint,
            "fingerprint": next_fingerprint,
            "openids": next_openids,
        }
    )
    allowlist_path.write_text(json.dumps(current), encoding="utf-8")
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    capture.update(
        {
            "candidates": [member_two],
            "baseline_allowlist_version": 1,
            "baseline_allowlist_fingerprint": previous_fingerprint,
            "frozen_allowlist_version": 2,
            "frozen_allowlist_fingerprint": next_fingerprint,
        }
    )
    capture_path.write_text(json.dumps(capture), encoding="utf-8")
    monkeypatch.setenv("PREVIOUS_ALLOWLIST_FILE", os.fspath(previous_path))
    _write_private(
        higgs, higgs.read_text(encoding="utf-8").replace("OPENIDS=", "OPENIDS=member-openid")
    )
    _write_private(
        sidecar,
        sidecar.read_text(encoding="utf-8").replace("OPENIDS=", "OPENIDS=member-openid"),
    )

    with pytest.raises(SystemExit, match="metadata does not match baseline"):
        FREEZE.main()
