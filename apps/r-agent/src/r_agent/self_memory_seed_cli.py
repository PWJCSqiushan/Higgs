"""Fail-closed operator CLI for the curated photography self-memory seed."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import stat
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from r_agent.identity import Principal
from r_agent.memory import MemoryStore
from r_agent.persona_evolution import (
    PHOTOGRAPHY_SEED_CONFIRMATION,
    SelfMemoryService,
    photography_seed_preview,
)
from r_agent.trash import move_to_trash

MAX_DATABASE_BYTES = 512 * 1024 * 1024
SEED_IDEMPOTENCY_KEY = "seed:photography-stance-v1"


class SeedSafetyError(RuntimeError):
    """A confirmed seed could not cross the local safety boundary."""

    def __init__(self, reason: str, *, receipt: dict[str, object] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.receipt = receipt


@dataclass(frozen=True, slots=True)
class BackupRecord:
    path: Path
    sha256: str
    size_bytes: int
    permissions_0600: bool


def _path_hash(path: Path) -> str:
    return hashlib.sha256(str(path.absolute()).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _readonly_uri(path: Path) -> str:
    normalized = str(path.absolute()).replace("\\", "/")
    return f"file:{quote(normalized, safe='/:')}?mode=ro"


def _validate_regular_database(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SeedSafetyError("database_unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SeedSafetyError("database_must_be_regular_file")
    if metadata.st_size <= 0 or metadata.st_size > MAX_DATABASE_BYTES:
        raise SeedSafetyError("database_size_out_of_bounds")


def _require_existing_v4_schema(path: Path) -> None:
    try:
        with sqlite3.connect(_readonly_uri(path), uri=True, timeout=5) as conn:
            version = conn.execute(
                "SELECT 1 FROM memory_schema_versions WHERE version=4"
            ).fetchone()
            tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name LIKE 'self_memory_%'"
                )
            }
            integrity = conn.execute("PRAGMA quick_check").fetchone()
    except sqlite3.Error as exc:
        raise SeedSafetyError("database_schema_unreadable") from exc
    required = {
        "self_memory_observations",
        "self_memory_metadata",
        "self_memory_evidence",
        "self_memory_evolution_observations",
    }
    if version is None or not required <= tables:
        raise SeedSafetyError("self_memory_schema_v4_required")
    if integrity != ("ok",):
        raise SeedSafetyError("database_integrity_failed")


def _best_effort_0600(path: Path) -> bool:
    try:
        path.chmod(0o600)
    except OSError:
        return False
    if os.name == "posix":
        try:
            return stat.S_IMODE(path.stat().st_mode) == 0o600
        except OSError:
            return False
    return True


def _create_consistent_backup(path: Path, *, now_ms: int) -> BackupRecord:
    token = uuid.uuid4().hex[:12]
    backup = path.with_name(f".{path.name}.photography-seed-{now_ms}-{token}.sqlite")
    try:
        with (
            sqlite3.connect(_readonly_uri(path), uri=True, timeout=5) as source,
            sqlite3.connect(backup, timeout=5) as destination,
        ):
            source.backup(destination)
            integrity = destination.execute("PRAGMA quick_check").fetchone()
            if integrity != ("ok",):
                raise SeedSafetyError("backup_integrity_failed")
        with backup.open("r+b") as handle:
            os.fsync(handle.fileno())
        permissions_0600 = _best_effort_0600(backup)
        metadata = backup.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise SeedSafetyError("backup_must_be_regular_file")
        if backup.parent.resolve() != path.parent.resolve():
            raise SeedSafetyError("backup_must_share_database_directory")
        return BackupRecord(
            path=backup,
            sha256=_sha256_file(backup),
            size_bytes=metadata.st_size,
            permissions_0600=permissions_0600,
        )
    except (OSError, sqlite3.Error, SeedSafetyError) as exc:
        if backup.exists() or backup.is_symlink():
            with suppress(OSError):
                move_to_trash(backup, trash_root=path.parent / ".trash")
        if isinstance(exc, SeedSafetyError):
            raise
        raise SeedSafetyError("consistent_backup_failed") from exc


def _seed_hash() -> str:
    preview = photography_seed_preview()
    payload = json.dumps(
        {
            "kind": preview["kind"],
            "scope": preview["scope"],
            "original_quote": preview["original_quote"],
            "normalized_content": preview["normalized_content"],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _seed_exists(path: Path) -> bool:
    with sqlite3.connect(_readonly_uri(path), uri=True, timeout=5) as conn:
        row = conn.execute(
            "SELECT 1 FROM self_memory_evolution_observations WHERE idempotency_key=?",
            (SEED_IDEMPOTENCY_KEY,),
        ).fetchone()
    return row is not None


def import_photography_seed(
    path: Path,
    *,
    confirmation: str,
    now_ms: int | None = None,
) -> dict[str, object]:
    """Back up and import the seed, returning only content-safe receipt fields."""

    if confirmation != PHOTOGRAPHY_SEED_CONFIRMATION:
        raise SeedSafetyError("confirmation_mismatch")
    started_at_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    _validate_regular_database(path)
    _require_existing_v4_schema(path)
    backup = _create_consistent_backup(path, now_ms=started_at_ms)
    if (
        not backup.path.exists()
        or backup.path.is_symlink()
        or backup.path.parent.resolve() != path.parent.resolve()
        or _sha256_file(backup.path) != backup.sha256
    ):
        raise SeedSafetyError("verified_backup_required")

    base_receipt: dict[str, object] = {
        "database_path_sha256": _path_hash(path),
        "backup_path_sha256": _path_hash(backup.path),
        "backup_sha256": backup.sha256,
        "backup_size_bytes": backup.size_bytes,
        "backup_permissions_0600": backup.permissions_0600,
        "seed_sha256": _seed_hash(),
        "started_at_ms": started_at_ms,
        "recoverable": True,
    }
    try:
        existed = _seed_exists(path)
        result = SelfMemoryService(MemoryStore(path)).seed_photography_stance(
            actor=Principal("owner-seed-cli", "owner"),
            confirm=True,
            now_ms=started_at_ms,
        )
        if result.item_id is None:
            raise SeedSafetyError("seed_result_missing_item")
        _require_existing_v4_schema(path)
    except Exception as exc:
        failed = {
            **base_receipt,
            "mode": "failed",
            "written": False,
            "reason": "seed_import_failed",
            "finished_at_ms": int(time.time() * 1000),
        }
        if isinstance(exc, SeedSafetyError):
            raise SeedSafetyError(exc.reason, receipt=failed) from exc
        raise SeedSafetyError("seed_import_failed", receipt=failed) from exc

    return {
        **base_receipt,
        "mode": "confirmed",
        "written": not existed,
        "idempotent_replay": existed,
        "decision": result.decision.value,
        "finished_at_ms": int(time.time() * 1000),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="r-agent-self-memory-seed")
    parser.add_argument("--db", type=Path, required=True, help="private memory.sqlite path")
    parser.add_argument("--confirm", action="store_true", help="persist after a verified backup")
    parser.add_argument("--confirmation", default="", help="exact operator confirmation string")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.confirm:
        print(json.dumps(photography_seed_preview(), ensure_ascii=False, separators=(",", ":")))
        return 0
    try:
        receipt = import_photography_seed(args.db, confirmation=args.confirmation)
    except SeedSafetyError as exc:
        payload = exc.receipt or {
            "mode": "refused",
            "written": False,
            "reason": exc.reason,
        }
        print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
        return 2
    print(json.dumps(receipt, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
