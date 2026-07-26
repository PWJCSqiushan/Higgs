"""Consistent local recovery snapshots for Higgs runtime state."""

from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
import threading
import uuid
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path


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
                shutil.rmtree(temporary, ignore_errors=True)
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
            shutil.rmtree(obsolete)

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

    async def run_periodically(self) -> None:
        while True:
            await asyncio.sleep(self.interval_minutes * 60)
            try:
                await asyncio.to_thread(self.create, "scheduled")
            except BackupError:
                # The caller's logging policy handles operational visibility;
                # the periodic loop must survive one failed snapshot.
                continue
