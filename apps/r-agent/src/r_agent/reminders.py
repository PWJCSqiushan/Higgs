# ruff: noqa: E501, RUF001
"""Owner-only durable reminders with explicit confirmation and idempotent sends."""

from __future__ import annotations

import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
_RETRY_OFFSETS_MS = (0, 5 * 60_000, 15 * 60_000, 30 * 60_000)


class ReminderError(RuntimeError):
    """Reminder validation or transition error."""


@dataclass(frozen=True, slots=True)
class ReminderJob:
    job_id: str
    owner_principal_id: str
    owner_qq: str
    content: str
    due_at_ms: int
    status: str
    created_at_ms: int
    confirmed_at_ms: int | None
    acknowledged_at_ms: int | None


@dataclass(frozen=True, slots=True)
class DueOccurrence:
    occurrence_key: str
    job_id: str
    owner_qq: str
    content: str
    attempt: int
    scheduled_at_ms: int


def parse_reminder_intent(text: str, *, now: datetime | None = None) -> tuple[int, str] | None:
    """Parse a deliberately narrow set of Chinese owner reminder expressions."""
    clean = " ".join(text.strip().split())
    if "提醒我" not in clean:
        return None
    current = now.astimezone(SHANGHAI) if now is not None else datetime.now(SHANGHAI)
    relative = re.fullmatch(r"(?P<n>\d{1,4})\s*(?P<unit>分钟|小时)后提醒我(?P<content>.+)", clean)
    if relative:
        amount = int(relative.group("n"))
        if amount <= 0:
            return None
        delta = timedelta(minutes=amount if relative.group("unit") == "分钟" else 60 * amount)
        due = current + delta
        return int(due.timestamp() * 1000), relative.group("content").strip(" 。！!")
    tomorrow = re.fullmatch(
        r"明天(?P<h>\d{1,2})(?:点|:)(?P<m>\d{1,2})?分?提醒我(?P<content>.+)", clean
    )
    if tomorrow:
        hour = int(tomorrow.group("h"))
        minute = int(tomorrow.group("m") or 0)
        if hour > 23 or minute > 59:
            return None
        due = (current + timedelta(days=1)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        return int(due.timestamp() * 1000), tomorrow.group("content").strip(" 。！!")
    absolute = re.fullmatch(
        r"(?P<date>\d{4}-\d{1,2}-\d{1,2})\s+(?P<h>\d{1,2}):(?P<m>\d{2})"
        r"\s*提醒我(?P<content>.+)",
        clean,
    )
    if absolute:
        try:
            due = datetime.strptime(
                f"{absolute.group('date')} {absolute.group('h')}:{absolute.group('m')}",
                "%Y-%m-%d %H:%M",
            ).replace(tzinfo=SHANGHAI)
        except ValueError:
            return None
        if due <= current:
            return None
        return int(due.timestamp() * 1000), absolute.group("content").strip(" 。！!")
    return None


class ReminderStore:
    STATUSES = frozenset(
        {
            "pending_confirmation",
            "scheduled",
            "awaiting_ack",
            "completed",
            "cancelled",
            "missed",
            "failed",
        }
    )

    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminder_jobs (
                    job_id TEXT PRIMARY KEY,
                    owner_principal_id TEXT NOT NULL,
                    owner_qq TEXT NOT NULL,
                    content TEXT NOT NULL,
                    due_at_ms INTEGER NOT NULL,
                    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
                    status TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    confirmed_at_ms INTEGER,
                    acknowledged_at_ms INTEGER,
                    cancelled_at_ms INTEGER,
                    updated_at_ms INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminder_occurrences (
                    occurrence_key TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES reminder_jobs(job_id),
                    attempt INTEGER NOT NULL,
                    scheduled_at_ms INTEGER NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('prepared','sent','failed','unknown')),
                    message_id TEXT,
                    prepared_at_ms INTEGER NOT NULL,
                    finished_at_ms INTEGER,
                    UNIQUE(job_id, attempt)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminder_effects (
                    effect_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurrence_key TEXT NOT NULL,
                    state TEXT NOT NULL,
                    detail_sha256 TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminder_due ON reminder_jobs(status, due_at_ms)"
            )

    @staticmethod
    def _row(row: sqlite3.Row) -> ReminderJob:
        return ReminderJob(
            str(row["job_id"]),
            str(row["owner_principal_id"]),
            str(row["owner_qq"]),
            str(row["content"]),
            int(row["due_at_ms"]),
            str(row["status"]),
            int(row["created_at_ms"]),
            int(row["confirmed_at_ms"]) if row["confirmed_at_ms"] is not None else None,
            int(row["acknowledged_at_ms"]) if row["acknowledged_at_ms"] is not None else None,
        )

    def _resolve(self, short_id: str) -> str:
        clean = short_id.strip().lower()
        if len(clean) < 6:
            raise ReminderError("提醒ID至少需要6位")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT job_id FROM reminder_jobs WHERE job_id LIKE ? LIMIT 2", (f"{clean}%",)
            ).fetchall()
        if not rows:
            raise ReminderError("未找到提醒")
        if len(rows) > 1:
            raise ReminderError("提醒ID不唯一，请输入更多位")
        return str(rows[0][0])

    def create_pending(
        self,
        *,
        owner_principal_id: str,
        owner_qq: str,
        content: str,
        due_at_ms: int,
        now_ms: int | None = None,
    ) -> ReminderJob:
        now = int(time.time() * 1000) if now_ms is None else now_ms
        clean = " ".join(content.split())
        if not 1 <= len(clean) <= 500:
            raise ReminderError("提醒内容长度必须为1到500字")
        if not now + 5_000 <= due_at_ms <= now + 366 * 86_400_000:
            raise ReminderError("提醒时间必须在5秒后到366天内")
        job_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reminder_jobs(
                    job_id, owner_principal_id, owner_qq, content, due_at_ms,
                    status, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, 'pending_confirmation', ?, ?)
                """,
                (job_id, owner_principal_id, owner_qq, clean, due_at_ms, now, now),
            )
        return self.get(job_id)

    def get(self, short_id: str) -> ReminderJob:
        job_id = self._resolve(short_id)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM reminder_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise ReminderError("未找到提醒")
        return self._row(row)

    def latest_pending(self, owner_principal_id: str) -> ReminderJob | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM reminder_jobs WHERE owner_principal_id=?
                  AND status='pending_confirmation' ORDER BY created_at_ms DESC LIMIT 1
                """,
                (owner_principal_id,),
            ).fetchone()
        return self._row(row) if row is not None else None

    def latest_awaiting_ack(self, owner_principal_id: str) -> ReminderJob | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM reminder_jobs WHERE owner_principal_id=?
                  AND status='awaiting_ack' ORDER BY due_at_ms DESC LIMIT 1
                """,
                (owner_principal_id,),
            ).fetchone()
        return self._row(row) if row is not None else None

    def _transition(self, short_id: str, *, allowed: set[str], target: str) -> ReminderJob:
        job_id = self._resolve(short_id)
        now = int(time.time() * 1000)
        marks = {
            "scheduled": "confirmed_at_ms",
            "completed": "acknowledged_at_ms",
            "cancelled": "cancelled_at_ms",
        }
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM reminder_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None or str(row[0]) not in allowed:
                raise ReminderError("当前提醒状态不允许该操作")
            column = marks.get(target)
            if column:
                conn.execute(
                    f"UPDATE reminder_jobs SET status=?, {column}=?, updated_at_ms=? WHERE job_id=?",
                    (target, now, now, job_id),
                )
            else:
                conn.execute(
                    "UPDATE reminder_jobs SET status=?, updated_at_ms=? WHERE job_id=?",
                    (target, now, job_id),
                )
        return self.get(job_id)

    def confirm(self, short_id: str) -> ReminderJob:
        return self._transition(short_id, allowed={"pending_confirmation"}, target="scheduled")

    def acknowledge(self, short_id: str) -> ReminderJob:
        return self._transition(short_id, allowed={"awaiting_ack", "scheduled"}, target="completed")

    def cancel(self, short_id: str) -> ReminderJob:
        return self._transition(
            short_id,
            allowed={"pending_confirmation", "scheduled", "awaiting_ack"},
            target="cancelled",
        )

    def snooze(self, short_id: str, minutes: int) -> ReminderJob:
        if not 1 <= minutes <= 1440:
            raise ReminderError("延后时间必须为1到1440分钟")
        job_id = self._resolve(short_id)
        now = int(time.time() * 1000)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM reminder_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None or str(row[0]) not in {"scheduled", "awaiting_ack"}:
                raise ReminderError("当前提醒不能延后")
            conn.execute(
                "UPDATE reminder_jobs SET due_at_ms=?, status='scheduled', updated_at_ms=? WHERE job_id=?",
                (now + minutes * 60_000, now, job_id),
            )
            conn.execute(
                "UPDATE reminder_occurrences SET state='failed' WHERE job_id=? AND state='prepared'",
                (job_id,),
            )
        return self.get(job_id)

    def list(self, *, limit: int = 10) -> list[ReminderJob]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reminder_jobs ORDER BY created_at_ms DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row(row) for row in rows]

    def prepare_due(self, *, now_ms: int | None = None) -> list[DueOccurrence]:
        now = int(time.time() * 1000) if now_ms is None else now_ms
        due: list[DueOccurrence] = []
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            jobs = conn.execute(
                """
                SELECT * FROM reminder_jobs
                WHERE status IN ('scheduled','awaiting_ack') AND due_at_ms <= ?
                ORDER BY due_at_ms LIMIT 50
                """,
                (now,),
            ).fetchall()
            for row in jobs:
                job_id = str(row["job_id"])
                due_at = int(row["due_at_ms"])
                if now > due_at + _RETRY_OFFSETS_MS[-1] + 60_000:
                    conn.execute(
                        "UPDATE reminder_jobs SET status='missed', updated_at_ms=? WHERE job_id=?",
                        (now, job_id),
                    )
                    continue
                eligible = [
                    attempt
                    for attempt, offset in enumerate(_RETRY_OFFSETS_MS)
                    if due_at + offset <= now
                ]
                target_attempt = max(eligible)
                existing = {
                    int(item[0])
                    for item in conn.execute(
                        "SELECT attempt FROM reminder_occurrences WHERE job_id=?", (job_id,)
                    ).fetchall()
                }
                if target_attempt in existing:
                    continue
                scheduled = due_at + _RETRY_OFFSETS_MS[target_attempt]
                key = f"{job_id}:{target_attempt}"
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO reminder_occurrences(
                        occurrence_key, job_id, attempt, scheduled_at_ms,
                        state, prepared_at_ms
                    ) VALUES (?, ?, ?, ?, 'prepared', ?)
                    """,
                    (key, job_id, target_attempt, scheduled, now),
                )
                if cursor.rowcount == 1:
                    due.append(
                        DueOccurrence(
                            key,
                            job_id,
                            str(row["owner_qq"]),
                            str(row["content"]),
                            target_attempt,
                            scheduled,
                        )
                    )
        return due

    def finish_occurrence(
        self, occurrence_key: str, *, state: str, message_id: str | None = None
    ) -> None:
        if state not in {"sent", "failed", "unknown"}:
            raise ReminderError("无效发送状态")
        now = int(time.time() * 1000)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT job_id FROM reminder_occurrences WHERE occurrence_key=? AND state='prepared'",
                (occurrence_key,),
            ).fetchone()
            if row is None:
                return
            conn.execute(
                """
                UPDATE reminder_occurrences SET state=?, message_id=?, finished_at_ms=?
                WHERE occurrence_key=? AND state='prepared'
                """,
                (state, message_id, now, occurrence_key),
            )
            if state == "sent":
                conn.execute(
                    "UPDATE reminder_jobs SET status='awaiting_ack', updated_at_ms=? WHERE job_id=?",
                    (now, str(row["job_id"])),
                )
            digest = (
                __import__("hashlib").sha256(f"{state}:{message_id or ''}".encode()).hexdigest()
            )
            conn.execute(
                "INSERT INTO reminder_effects(occurrence_key,state,detail_sha256,created_at_ms) VALUES (?,?,?,?)",
                (occurrence_key, state, digest, now),
            )


def format_job(job: ReminderJob) -> str:
    due = datetime.fromtimestamp(job.due_at_ms / 1000, SHANGHAI)
    return (
        f"提醒ID：{job.job_id[:8]}\n"
        f"内容：{job.content}\n"
        f"时间：{due:%Y-%m-%d %H:%M:%S}（北京时间）\n"
        f"状态：{job.status}\n"
        "追发：到点、+5、+15、+30分钟；明确确认收到后停止。"
    )
