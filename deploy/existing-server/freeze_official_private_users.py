"""Finalize a bounded private-user capture without enabling the channel."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
from pathlib import Path


SAFE_ID = re.compile(r"[!-~]{1,256}\Z")


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

    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    allowlist = json.loads(allowlist_path.read_text(encoding="utf-8"))
    openids = allowlist.get("openids")
    if (
        capture.get("status") != "frozen"
        or allowlist.get("version") != 1
        or not isinstance(openids, list)
        or len(openids) != expected
        or len(set(openids)) != len(openids)
        or any(
            not isinstance(item, str)
            or "*" in item
            or not SAFE_ID.fullmatch(item)
            for item in openids
        )
    ):
        raise SystemExit("private_freeze: frozen identities are invalid")
    if (
        allowlist.get("app_id") != capture.get("app_id")
        or not SAFE_ID.fullmatch(str(allowlist.get("bot_id", "")))
    ):
        raise SystemExit("private_freeze: frozen Bot binding is invalid")

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
        raise SystemExit("private_freeze: frozen AppID does not match private configuration")
    for key, values in (
        ("R_AGENT_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS", higgs),
        ("HIGGS_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS", side),
    ):
        if values.get(key, "").strip():
            raise SystemExit("private_freeze: existing private allowlist is not empty")

    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copy2(higgs_path, backup_dir / "higgs.env")
    shutil.copy2(side_path, backup_dir / "official-qq.env")
    for path in (backup_dir / "higgs.env", backup_dir / "official-qq.env"):
        os.chmod(path, 0o600)

    joined = ",".join(openids)
    try:
        _write_env(higgs_path, "R_AGENT_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS", joined, backup_dir)
        _write_env(side_path, "HIGGS_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS", joined, backup_dir)
    except Exception:
        _rollback(higgs_path, backup_dir / "higgs.env", backup_dir)
        _rollback(side_path, backup_dir / "official-qq.env", backup_dir)
        raise
    print(len(openids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
