"""Finalize a bounded private-user capture without enabling the channel."""

from __future__ import annotations

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
SCHEMA_VERSION = 2
MAX_ALLOWLIST_ENTRIES = 128


def _fail(message: str) -> None:
    raise SystemExit(f"private_freeze: {message}")


def _canonical_fingerprint(
    *, app_id: str, bot_id: str, allowlist_version: int, openids: list[str]
) -> str:
    payload = json.dumps(
        {
            "scope": "private",
            "app_id": app_id,
            "bot_id": bot_id,
            "allowlist_version": allowlist_version,
            "openids": openids,
        },
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _safe_openids(value: object, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_ALLOWLIST_ENTRIES:
        _fail("frozen identities are invalid")
    if not allow_empty and not value:
        _fail("frozen identities are invalid")
    if any(
        not isinstance(item, str) or not SAFE_ID.fullmatch(item) or "*" in item
        for item in value
    ):
        _fail("frozen identities are invalid")
    if len(set(value)) != len(value) or value != sorted(value):
        _fail("frozen identities are invalid")
    return value


def _read_v2_allowlist(
    path: Path, *, required: bool = True
) -> dict[str, object] | None:
    if not path.exists():
        if required:
            _fail("frozen allowlist is missing")
        return None
    if path.is_symlink() or not path.is_file():
        _fail("frozen allowlist is unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _fail("frozen allowlist is invalid")
    if isinstance(value, dict) and value.get("version") == 1:
        _fail("legacy v1 allowlist requires explicit import")
    required_keys = {
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
        or set(value) != required_keys
        or value.get("version") != SCHEMA_VERSION
        or value.get("scope") != "private"
    ):
        _fail("frozen allowlist is not v2")
    app_id = value.get("app_id")
    bot_id = value.get("bot_id")
    allowlist_version = value.get("allowlist_version")
    if (
        not isinstance(app_id, str)
        or not APP_ID.fullmatch(app_id)
        or not isinstance(bot_id, str)
        or not SAFE_ID.fullmatch(bot_id)
        or "*" in bot_id
        or isinstance(allowlist_version, bool)
        or not isinstance(allowlist_version, int)
        or allowlist_version < 1
        or isinstance(value.get("frozen_at_ms"), bool)
        or not isinstance(value.get("frozen_at_ms"), int)
        or value.get("frozen_at_ms") < 0
        or not isinstance(value.get("epoch_id"), str)
        or not SAFE_ID.fullmatch(value["epoch_id"])
        or not isinstance(value.get("nonce"), str)
        or not NONCE.fullmatch(value["nonce"])
    ):
        _fail("frozen allowlist is invalid")
    openids = _safe_openids(value.get("openids"))
    previous_version = value.get("previous_version")
    previous_fingerprint = value.get("previous_fingerprint")
    if allowlist_version == 1:
        if previous_version is not None or previous_fingerprint is not None:
            _fail("frozen allowlist chain is invalid")
    elif (
        isinstance(previous_version, bool)
        or not isinstance(previous_version, int)
        or previous_version != allowlist_version - 1
        or not isinstance(previous_fingerprint, str)
        or not FINGERPRINT.fullmatch(previous_fingerprint)
    ):
        _fail("frozen allowlist chain is invalid")
    fingerprint = value.get("fingerprint")
    if not isinstance(fingerprint, str) or not FINGERPRINT.fullmatch(fingerprint):
        _fail("frozen allowlist fingerprint is invalid")
    if fingerprint != _canonical_fingerprint(
        app_id=app_id,
        bot_id=bot_id,
        allowlist_version=allowlist_version,
        openids=openids,
    ):
        _fail("frozen allowlist fingerprint is invalid")
    return value


def _read_v2_capture(path: Path, expected_count: int) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        _fail("a closed private capture is required")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _fail("capture state is invalid")
    if isinstance(value, dict) and value.get("version") == 1:
        _fail("legacy v1 capture requires explicit import")
    required_keys = {
        "version",
        "scope",
        "status",
        "epoch_id",
        "nonce",
        "app_id",
        "bot_id",
        "window_started_at_ms",
        "window_deadline_at_ms",
        "max_candidates",
        "candidates",
        "baseline_allowlist_version",
        "baseline_allowlist_fingerprint",
        "frozen_allowlist_version",
        "frozen_allowlist_fingerprint",
        "history",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required_keys
        or value.get("version") != SCHEMA_VERSION
        or value.get("scope") != "private"
        or value.get("status") != "frozen"
    ):
        _fail("capture state is not frozen v2")
    app_id = value.get("app_id")
    bot_id = value.get("bot_id")
    if (
        not isinstance(app_id, str)
        or not APP_ID.fullmatch(app_id)
        or not isinstance(bot_id, str)
        or not SAFE_ID.fullmatch(bot_id)
        or "*" in bot_id
        or not isinstance(value.get("epoch_id"), str)
        or not SAFE_ID.fullmatch(value["epoch_id"])
        or not isinstance(value.get("nonce"), str)
        or not NONCE.fullmatch(value["nonce"])
    ):
        _fail("capture state is invalid")
    max_candidates = value.get("max_candidates")
    if (
        isinstance(max_candidates, bool)
        or not isinstance(max_candidates, int)
        or not 1 <= max_candidates <= MAX_ALLOWLIST_ENTRIES
    ):
        _fail("capture state is invalid")
    candidates = _safe_openids(value.get("candidates"))
    if len(candidates) != expected_count or len(candidates) > max_candidates:
        _fail("capture candidate count mismatch")
    for version_key, fingerprint_key in (
        ("baseline_allowlist_version", "baseline_allowlist_fingerprint"),
        ("frozen_allowlist_version", "frozen_allowlist_fingerprint"),
    ):
        version = value.get(version_key)
        fingerprint = value.get(fingerprint_key)
        if version is None:
            if fingerprint is not None:
                _fail("capture allowlist metadata is invalid")
        elif (
            isinstance(version, bool)
            or not isinstance(version, int)
            or version < 1
            or not isinstance(fingerprint, str)
            or not FINGERPRINT.fullmatch(fingerprint)
        ):
            _fail("capture allowlist metadata is invalid")
    if value.get("frozen_allowlist_version") is None:
        _fail("capture state is not frozen v2")
    return value


def _env_ids(values: dict[str, str], key: str) -> list[str]:
    raw = values.get(key, "").strip()
    if not raw:
        return []
    return _safe_openids([part.strip() for part in raw.split(",")])


def _env_metadata(
    values: dict[str, str], version_key: str, fingerprint_key: str
) -> tuple[int, str] | None:
    version = values.get(version_key, "").strip()
    fingerprint = values.get(fingerprint_key, "").strip()
    if not version and not fingerprint:
        return None
    if (
        not version.isdigit()
        or int(version) < 1
        or not FINGERPRINT.fullmatch(fingerprint)
    ):
        _fail("private allowlist metadata is invalid")
    return int(version), fingerprint


def _read_env(path: Path) -> tuple[list[str], dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    for line in lines:
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in values:
            raise SystemExit("private_freeze: duplicate private configuration key")
        values[key] = value
    return lines, values


def _require_disabled(values: dict[str, str], key: str) -> None:
    value = values.get(key, "false").strip().casefold()
    if value not in {"false", "0", "no", "off"}:
        raise SystemExit("private_freeze: channel gate is not disabled")


def _write_env(path: Path, key: str, value: str, backup_dir: Path) -> None:
    lines, _ = _read_env(path)
    output: list[str] = []
    written = False
    for line in lines:
        if line.startswith(f"{key}="):
            if not written:
                output.append(f"{key}={value}")
                written = True
            continue
        output.append(line)
    if not written:
        output.append(f"{key}={value}")
    temporary = path.with_name(f".{path.name}.private-freeze-{os.getpid()}")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(output) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        original = path.stat()
        os.chown(temporary, original.st_uid, original.st_gid)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            os.replace(temporary, backup_dir / temporary.name)


def _rollback(path: Path, backup: Path, backup_dir: Path) -> None:
    temporary = path.with_name(f".{path.name}.private-freeze-rollback-{os.getpid()}")
    try:
        shutil.copy2(backup, temporary)
        original = path.stat()
        os.chown(temporary, original.st_uid, original.st_gid)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            os.replace(temporary, backup_dir / temporary.name)


def main() -> int:
    higgs_path = Path(os.environ["HIGGS_ENV_FILE"])
    side_path = Path(os.environ["SIDE_ENV_FILE"])
    capture_path = Path(os.environ["CAPTURE_FILE"])
    allowlist_path = Path(os.environ["ALLOWLIST_FILE"])
    backup_dir = Path(os.environ["BACKUP_DIR"])
    expected = int(os.environ["EXPECTED_COUNT"])

    if not 1 <= expected <= MAX_ALLOWLIST_ENTRIES:
        _fail("candidate count is invalid")
    capture = _read_v2_capture(capture_path, expected)
    allowlist = _read_v2_allowlist(allowlist_path)
    assert allowlist is not None
    openids = _safe_openids(allowlist["openids"])
    candidates = _safe_openids(capture["candidates"])
    if any(candidate not in openids for candidate in candidates):
        _fail("capture candidates are absent from frozen allowlist")
    if (
        allowlist["app_id"] != capture["app_id"]
        or allowlist["bot_id"] != capture["bot_id"]
        or allowlist["epoch_id"] != capture["epoch_id"]
        or allowlist["nonce"] != capture["nonce"]
        or capture["frozen_allowlist_version"] != allowlist["allowlist_version"]
        or capture["frozen_allowlist_fingerprint"] != allowlist["fingerprint"]
        or capture["baseline_allowlist_version"] != allowlist["previous_version"]
        or capture["baseline_allowlist_fingerprint"]
        != allowlist["previous_fingerprint"]
    ):
        _fail("capture and frozen allowlist metadata do not match")

    _, higgs = _read_env(higgs_path)
    _, side = _read_env(side_path)
    for key in (
        "R_AGENT_OFFICIAL_QQ_ENABLED",
        "R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED",
        "R_AGENT_OFFICIAL_QQ_GROUP_ENABLED",
    ):
        _require_disabled(higgs, key)
    for key in (
        "HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED",
        "HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED",
        "HIGGS_OFFICIAL_QQ_GROUP_ENABLED",
    ):
        _require_disabled(side, key)
    app_id = side.get("QQBOT_APP_ID", "").strip()
    if app_id != allowlist.get("app_id") or not re.fullmatch(r"[0-9]{5,32}", app_id):
        _fail("frozen AppID does not match private configuration")

    previous_path_value = os.environ.get("PREVIOUS_ALLOWLIST_FILE", "").strip()
    previous = None
    if allowlist["previous_version"] is None:
        if previous_path_value:
            _fail("unexpected previous allowlist for initial freeze")
    else:
        if not previous_path_value:
            _fail("previous v2 allowlist is required for incremental freeze")
        previous = _read_v2_allowlist(Path(previous_path_value))
        assert previous is not None
        if (
            previous["app_id"] != allowlist["app_id"]
            or previous["bot_id"] != allowlist["bot_id"]
            or previous["allowlist_version"] != allowlist["previous_version"]
            or previous["fingerprint"] != allowlist["previous_fingerprint"]
        ):
            _fail("previous allowlist chain does not match")

    expected_previous_ids = (
        [] if previous is None else _safe_openids(previous["openids"])
    )
    for key, values in (
        ("R_AGENT_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS", higgs),
        ("HIGGS_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS", side),
    ):
        if _env_ids(values, key) != expected_previous_ids:
            _fail("existing private allowlist does not match baseline")

    metadata_keys = (
        (
            "R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_VERSION",
            "R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FINGERPRINT",
            higgs,
        ),
        (
            "HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_VERSION",
            "HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FINGERPRINT",
            side,
        ),
    )
    expected_previous_metadata = (
        None
        if previous is None
        else (previous["allowlist_version"], previous["fingerprint"])
    )
    existing_metadata = [
        _env_metadata(values, version_key, fingerprint_key)
        for version_key, fingerprint_key, values in metadata_keys
    ]
    if existing_metadata != [None, None] and any(
        metadata != expected_previous_metadata for metadata in existing_metadata
    ):
        _fail("existing private allowlist metadata does not match baseline")

    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copy2(higgs_path, backup_dir / "higgs.env")
    shutil.copy2(side_path, backup_dir / "official-qq.env")
    for path in (backup_dir / "higgs.env", backup_dir / "official-qq.env"):
        os.chmod(path, 0o600)

    joined = ",".join(openids)
    next_metadata = {
        "R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_VERSION": str(
            allowlist["allowlist_version"]
        ),
        "R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FINGERPRINT": str(
            allowlist["fingerprint"]
        ),
        "HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_VERSION": str(
            allowlist["allowlist_version"]
        ),
        "HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FINGERPRINT": str(
            allowlist["fingerprint"]
        ),
    }
    try:
        _write_env(
            higgs_path,
            "R_AGENT_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS",
            joined,
            backup_dir,
        )
        _write_env(
            side_path, "HIGGS_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS", joined, backup_dir
        )
        _write_env(
            higgs_path,
            "R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_VERSION",
            next_metadata["R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_VERSION"],
            backup_dir,
        )
        _write_env(
            higgs_path,
            "R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FINGERPRINT",
            next_metadata["R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FINGERPRINT"],
            backup_dir,
        )
        _write_env(
            side_path,
            "HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_VERSION",
            next_metadata["HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_VERSION"],
            backup_dir,
        )
        _write_env(
            side_path,
            "HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FINGERPRINT",
            next_metadata["HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FINGERPRINT"],
            backup_dir,
        )
    except Exception:
        _rollback(higgs_path, backup_dir / "higgs.env", backup_dir)
        _rollback(side_path, backup_dir / "official-qq.env", backup_dir)
        raise
    print(len(openids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
