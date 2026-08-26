"""Consistent local recovery snapshots for Higgs runtime state."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import uuid
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from r_agent.trash import move_to_trash


class BackupError(RuntimeError):
    """A backup could not be created or verified."""


class BackupManager:
    """Back up known SQLite stores without copying API keys or OneBot tokens."""

    DATABASE_NAMES = (
        "identity.sqlite",
        "journal.sqlite",
        "conversation.sqlite",
        "memory.sqlite",
        "reply_audit.sqlite",
        "reminders.sqlite",
        "conversation_guard.sqlite",
        "risk_ledger.sqlite",
        "agenda.sqlite",
        "skills.sqlite",
        "transport.sqlite",
    )

    def __init__(
        self,
        *,
        data_dir: Path,
        backup_dir: Path,
        interval_minutes: int = 360,
        retention: int = 20,
        config_snapshot: Callable[[], dict[str, object]] | None = None,
    ) -> None:
        if not 15 <= interval_minutes <= 1440:
            raise BackupError("backup interval must be between 15 and 1440 minutes")
        if not 3 <= retention <= 100:
            raise BackupError("backup retention must be between 3 and 100")
        self.data_dir = data_dir.expanduser().resolve()
        self.backup_dir = backup_dir.expanduser().resolve()
        self.interval_minutes = interval_minutes
        self.retention = retention
        self.config_snapshot = config_snapshot
        self._lock = threading.Lock()

    def create(self, reason: str) -> Path:
        clean_reason = reason.strip()
        if not clean_reason or len(clean_reason) > 80:
            raise BackupError("backup reason is invalid")
        with self._lock:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
            name = f"backup-{stamp}-{uuid.uuid4().hex[:8]}"
            temporary = self.backup_dir / f".{name}.tmp"
            destination = self.backup_dir / name
            temporary.mkdir()
            try:
                backed_up: list[str] = []
                for database_name in self.DATABASE_NAMES:
                    source = self.data_dir / database_name
                    if not source.is_file():
                        continue
                    target = temporary / database_name
                    self._sqlite_backup(source, target)
                    backed_up.append(database_name)
                safe_config = self.config_snapshot() if self.config_snapshot else {}
                metadata = {
                    "schema": 1,
                    "created_at_utc": datetime.now(UTC).isoformat(),
                    "reason": clean_reason,
                    "databases": backed_up,
                    "safe_runtime_config": safe_config,
                    "secrets_included": False,
                }
                (temporary / "manifest.json").write_text(
                    json.dumps(metadata, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                temporary.rename(destination)
            except Exception as exc:
                move_to_trash(temporary, trash_root=self.backup_dir / ".trash")
                if isinstance(exc, BackupError):
                    raise
                raise BackupError("backup creation failed") from exc
            self._prune()
            return destination

    @staticmethod
    def _sqlite_backup(source: Path, target: Path) -> None:
        try:
            with (
                closing(sqlite3.connect(source, timeout=10)) as source_conn,
                closing(sqlite3.connect(target, timeout=10)) as target_conn,
            ):
                source_conn.backup(target_conn)
                result = target_conn.execute("PRAGMA quick_check").fetchone()
        except sqlite3.Error as exc:
            raise BackupError(f"SQLite backup failed for {source.name}") from exc
        if result is None or result[0] != "ok":
            raise BackupError(f"SQLite verification failed for {source.name}")

    def _prune(self) -> None:
        snapshots = sorted(
            (
                item
                for item in self.backup_dir.iterdir()
                if item.is_dir() and item.name.startswith("backup-")
            ),
            key=lambda item: item.name,
            reverse=True,
        )
        for obsolete in snapshots[self.retention :]:
            move_to_trash(obsolete, trash_root=self.backup_dir / ".trash")

    def status(self) -> dict[str, object]:
        if not self.backup_dir.is_dir():
            return {"count": 0, "latest": None, "interval_minutes": self.interval_minutes}
        snapshots = sorted(
            (
                item.name
                for item in self.backup_dir.iterdir()
                if item.is_dir() and item.name.startswith("backup-")
            ),
            reverse=True,
        )
        return {
            "count": len(snapshots),
            "latest": snapshots[0] if snapshots else None,
            "interval_minutes": self.interval_minutes,
            "retention": self.retention,
        }

    def verify_snapshot(self, snapshot: Path) -> dict[str, object]:
        """Verify a snapshot without restoring or exposing database contents."""
        resolved = snapshot.expanduser().resolve()
        try:
            resolved.relative_to(self.backup_dir)
        except ValueError as exc:
            raise BackupError("snapshot is outside the configured backup directory") from exc
        manifest_path = resolved / "manifest.json"
        if not manifest_path.is_file():
            raise BackupError("snapshot manifest is missing")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BackupError("snapshot manifest is invalid") from exc
        databases = manifest.get("databases")
        if not isinstance(databases, list) or any(
            name not in self.DATABASE_NAMES for name in databases
        ):
            raise BackupError("snapshot database list is invalid")
        verified: list[str] = []
        for name in databases:
            database = resolved / name
            if not database.is_file():
                raise BackupError(f"snapshot database is missing: {name}")
            try:
                with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as conn:
                    result = conn.execute("PRAGMA quick_check").fetchone()
            except sqlite3.Error as exc:
                raise BackupError(f"snapshot verification failed for {name}") from exc
            if result is None or result[0] != "ok":
                raise BackupError(f"snapshot verification failed for {name}")
            verified.append(name)
        return {"verified": tuple(verified), "secrets_included": False}

    def restore_to(self, snapshot: Path, destination: Path) -> dict[str, object]:
        """Restore a verified snapshot into a new empty directory.

        Runtime databases are never overwritten in place.  Operators can restore
        into a temporary directory, run acceptance checks, and then perform a
        separately approved cut-over.
        """
        verified = self.verify_snapshot(snapshot)
        target = destination.expanduser().resolve()
        if target == self.data_dir or target == self.backup_dir:
            raise BackupError("restore destination must be separate from runtime data")
        if target.exists() and any(target.iterdir()):
            raise BackupError("restore destination must be empty")
        target.mkdir(parents=True, exist_ok=True)
        restored: list[str] = []
        try:
            for name in verified["verified"]:
                source = snapshot.expanduser().resolve() / str(name)
                restored_path = target / str(name)
                self._sqlite_backup(source, restored_path)
                restored.append(str(name))
        except Exception as exc:
            move_to_trash(target, trash_root=destination.parent / ".trash")
            if isinstance(exc, BackupError):
                raise
            raise BackupError("snapshot restore verification failed") from exc
        return {"restored": tuple(restored), "secrets_included": False}

    async def run_periodically(self) -> None:
        while True:
            await asyncio.sleep(self.interval_minutes * 60)
            try:
                await asyncio.to_thread(self.create, "scheduled")
            except BackupError:
                # The caller's logging policy handles operational visibility;
                # the periodic loop must survive one failed snapshot.
                continue
